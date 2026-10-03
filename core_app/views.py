import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO

import razorpay
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Avg, Count, DecimalField, F, Max, Min, Prefetch, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .cart import Cart
from .forms import (
    CheckoutForm,
    ProductForm,
    ProductReviewForm,
    RegisterForm,
    UserProfileForm,
)
from .decorators import admin_required, seller_required
from .models import (
    Category,
    Order,
    OrderItem,
    Product,
    ProductImage,
    ProductReview,
    ProductReviewImage,
    SellerInvitation,
    User,
)

logger = logging.getLogger(__name__)


class InventoryUnavailable(Exception):
    pass


class CartPriceChanged(Exception):
    def __init__(self, product_id, price):
        self.product_id = str(product_id)
        self.price = price


def get_razorpay_client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise ImproperlyConfigured('Razorpay API credentials are not configured.')
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
    )


def mark_order_paid(order, payment_id):
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.payment_status == Order.PaymentStatus.PAID:
            return locked_order
        locked_order.payment_status = Order.PaymentStatus.PAID
        locked_order.payment_reference = payment_id or locked_order.payment_reference
        locked_order.paid_at = timezone.now()
        if locked_order.status == Order.Status.PENDING:
            locked_order.status = Order.Status.PROCESSING
        locked_order.save(update_fields=[
            'payment_status',
            'payment_reference',
            'paid_at',
            'status',
        ])
        return locked_order


def release_order_inventory(order, payment_status):
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.payment_status in {
            Order.PaymentStatus.PAID,
            Order.PaymentStatus.FAILED,
        }:
            return locked_order

        for item in locked_order.items.select_related('product'):
            if item.product_id:
                Product.objects.filter(pk=item.product_id).update(
                    stock=F('stock') + item.quantity,
                )
            item.fulfillment_status = OrderItem.FulfillmentStatus.CANCELLED
            item.save(update_fields=['fulfillment_status'])

        locked_order.payment_status = payment_status
        locked_order.status = Order.Status.CANCELLED
        locked_order.save(update_fields=['payment_status', 'status'])
        return locked_order


def get_seller_metrics(user):
    metrics = OrderItem.objects.filter(
        seller=user,
        order__payment_status=Order.PaymentStatus.PAID,
    ).aggregate(
        revenue=Sum(
            F('price') * F('quantity'),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        items_sold=Sum('quantity'),
    )
    return {
        'revenue': metrics['revenue'] or Decimal('0.00'),
        'items_sold': metrics['items_sold'] or 0,
    }


def get_seller_order_groups(user, limit=None):
    order_ids = None
    if limit is not None:
        order_ids = list(
            OrderItem.objects.filter(seller=user)
            .order_by()
            .values_list('order_id', flat=True)
            .distinct()
            .order_by('-order__created_at')[:limit]
        )
    order_items = OrderItem.objects.filter(
        seller=user,
    ).select_related('order', 'product').order_by('-order__created_at')
    if order_ids is not None:
        order_items = order_items.filter(order_id__in=order_ids)

    groups = {}
    for item in order_items:
        group = groups.setdefault(item.order_id, {
            'order': item.order,
            'items': [],
            'subtotal': Decimal('0.00'),
        })
        group['items'].append(item)
        group['subtotal'] += item.line_total
    return list(groups.values())


def update_order_status_from_items(order):
    statuses = list(order.items.values_list('fulfillment_status', flat=True))
    if not statuses:
        return
    if all(status == OrderItem.FulfillmentStatus.COMPLETED for status in statuses):
        order.status = Order.Status.COMPLETED
    elif any(status in {
        OrderItem.FulfillmentStatus.SHIPPED,
        OrderItem.FulfillmentStatus.COMPLETED,
    } for status in statuses):
        order.status = Order.Status.SHIPPED
    elif any(status == OrderItem.FulfillmentStatus.PROCESSING for status in statuses):
        order.status = Order.Status.PROCESSING
    elif all(status == OrderItem.FulfillmentStatus.CANCELLED for status in statuses):
        order.status = Order.Status.CANCELLED
    else:
        order.status = Order.Status.PENDING
    order.save(update_fields=['status'])


def create_order_from_cart(request, form, cart, products):
    total_amount = Decimal('0.00')
    order_items = []
    with transaction.atomic():
        for product_id, cart_item in cart.cart.items():
            product = Product.objects.select_for_update().filter(
                pk=products[product_id].pk,
                is_active=True,
            ).first()
            if product is None:
                raise InventoryUnavailable(products[product_id].title)
            current_price = product.price
            if Decimal(cart_item['price']) != current_price:
                raise CartPriceChanged(product_id, current_price)

            quantity = cart_item['quantity']
            updated = Product.objects.filter(
                pk=product.pk,
                is_active=True,
                stock__gte=quantity,
            ).update(stock=F('stock') - quantity)
            if updated != 1:
                raise InventoryUnavailable(product.title)

            order_items.append(OrderItem(
                product=product,
                seller=product.seller,
                product_title=product.title,
                price=current_price,
                quantity=quantity,
            ))
            total_amount += current_price * quantity

        order = form.save(commit=False)
        order.user = request.user if request.user.is_authenticated else None
        order.total_amount = total_amount
        order.save()
        for item in order_items:
            item.order = order
        OrderItem.objects.bulk_create(order_items)
    return order, total_amount
from .models import Product

def home(request):
    products = Product.objects.filter(
        is_active=True,
    ).select_related('category').order_by('-created_at', '-pk')[:8]
    return render(request, 'core_app/home.html', {'products': products})


def catalog(request):
    products = Product.objects.filter(is_active=True).select_related('category')
    categories = Category.objects.filter(
        products__is_active=True,
    ).distinct().order_by('name')
    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    price_bounds = products.aggregate(minimum=Min('price'), maximum=Max('price'))
    catalog_min_price = price_bounds['minimum'] or Decimal('0.00')
    catalog_max_price = price_bounds['maximum'] or Decimal('0.00')

    products = products.filter(
        Q(title__icontains=query) | Q(description__icontains=query)
    ) if query else products

    if category_slug:
        products = products.filter(category__slug=category_slug)

    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    price_error = ''
    try:
        parsed_min_price = Decimal(min_price) if min_price else None
        parsed_max_price = Decimal(max_price) if max_price else None
        if (
            (parsed_min_price is not None and (
                not parsed_min_price.is_finite() or parsed_min_price < 0
            ))
            or (parsed_max_price is not None and (
                not parsed_max_price.is_finite() or parsed_max_price < 0
            ))
            or (
                parsed_min_price is not None
                and parsed_max_price is not None
                and parsed_min_price > parsed_max_price
            )
        ):
            raise ValidationError('Choose a valid minimum and maximum price.')
    except (InvalidOperation, ValidationError):
        parsed_min_price = parsed_max_price = None
        price_error = 'Choose a valid minimum and maximum price.'

    if parsed_min_price is not None:
        products = products.filter(price__gte=parsed_min_price)
    if parsed_max_price is not None:
        products = products.filter(price__lte=parsed_max_price)

    paginator = Paginator(products.order_by('title', 'pk'), 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    selected_min_price = parsed_min_price if parsed_min_price is not None else Decimal('0.00')
    selected_max_price = (
        parsed_max_price
        if parsed_max_price is not None
        else catalog_max_price
    )
    price_slider_max = max(catalog_max_price, Decimal('1.00'))

    return render(request, 'core_app/catalog.html', {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'categories': categories,
        'query': query,
        'category_slug': category_slug,
        'selected_min_price': selected_min_price,
        'selected_max_price': selected_max_price,
        'catalog_min_price': catalog_min_price,
        'catalog_max_price': catalog_max_price,
        'price_slider_max': price_slider_max,
        'price_error': price_error,
    })


from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages

def get_valid_seller_invitation(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    return SellerInvitation.objects.filter(
        token_hash=token_hash,
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()


def register_view(request, invitation_token=None):
    invitation = (
        get_valid_seller_invitation(invitation_token)
        if invitation_token
        else None
    )
    if invitation_token and invitation is None:
        messages.error(request, 'This seller invitation is invalid, expired, or already used.')
        return redirect('register')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                if invitation_token:
                    token_hash = hashlib.sha256(invitation_token.encode('utf-8')).hexdigest()
                    invitation = SellerInvitation.objects.select_for_update().filter(
                        token_hash=token_hash,
                        used_at__isnull=True,
                        expires_at__gt=timezone.now(),
                    ).first()
                    if invitation is None:
                        messages.error(request, 'This seller invitation is invalid, expired, or already used.')
                        return redirect('register')

                user = form.save(commit=False)
                user.role = User.Role.SELLER if invitation_token else User.Role.BUYER
                user.set_password(form.cleaned_data['password'])
                user.save()
                if invitation:
                    invitation.used_at = timezone.now()
                    invitation.save(update_fields=['used_at'])

            login(request, user)
            messages.success(request, f"Welcome to ZAN, {user.username}!")
            return redirect('home')
    else:
        form = RegisterForm()
    return render(request, 'core_app/register.html', {
        'form': form,
        'seller_invitation': invitation is not None,
    })

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if user.role == User.Role.ADMIN:
                return redirect('admin_dashboard')
            elif user.role == User.Role.SELLER:
                return redirect('seller_dashboard')
            return redirect('home')
    else:
        form = AuthenticationForm()
    return render(request, 'core_app/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('home')

# Gated Seller Dashboard
@seller_required
def seller_dashboard(request):
    own_products = Product.objects.filter(seller=request.user).select_related('category')
    products = Product.objects.filter(seller__isnull=False).select_related(
        'category',
        'seller',
    ).order_by('title')
    return render(request, 'core_app/seller_dashboard.html', {
        'products': products,
        'low_stock_count': own_products.filter(stock__lte=5).count(),
        **get_seller_metrics(request.user),
        'recent_orders': get_seller_order_groups(request.user, limit=5),
    })


@seller_required
def seller_orders(request):
    return render(request, 'core_app/seller_orders.html', {
        'order_groups': get_seller_order_groups(request.user),
    })


@seller_required
@require_POST
def update_seller_order_item_status(request, public_id, item_id):
    item = get_object_or_404(
        OrderItem.objects.select_related('order', 'product'),
        pk=item_id,
        order__public_id=public_id,
        seller=request.user,
    )
    transitions = {
        OrderItem.FulfillmentStatus.PENDING: OrderItem.FulfillmentStatus.PROCESSING,
        OrderItem.FulfillmentStatus.PROCESSING: OrderItem.FulfillmentStatus.SHIPPED,
        OrderItem.FulfillmentStatus.SHIPPED: OrderItem.FulfillmentStatus.COMPLETED,
    }
    next_status = transitions.get(item.fulfillment_status)
    if (
        not next_status
        or item.order.payment_status in {
            Order.PaymentStatus.FAILED,
            Order.PaymentStatus.REFUNDED,
        }
        or (
            item.order.payment_method == Order.PaymentMethod.RAZORPAY
            and not item.order.is_paid
        )
    ):
        messages.error(request, 'This order item cannot be advanced to the next delivery stage.')
        return redirect('seller_orders')

    item.fulfillment_status = next_status
    item.save(update_fields=['fulfillment_status'])
    update_order_status_from_items(item.order)
    messages.success(
        request,
        f'{item.product_title} marked as {item.get_fulfillment_status_display().lower()}.',
    )
    return redirect('seller_orders')

# Gated Executive Admin Dashboard
@admin_required
def admin_dashboard(request):
    stats = {
        'total_users': User.objects.count(),
        'total_sellers': User.objects.filter(
            role=User.Role.SELLER,
            is_active=True,
        ).count(),
        'total_products': Product.objects.count(),
    }
    products = Product.objects.select_related('category', 'seller').order_by('title')
    sellers = User.objects.filter(role=User.Role.SELLER).order_by('username')
    seller_invitations = SellerInvitation.objects.filter(
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by('-created_at')
    return render(request, 'core_app/admin_dashboard.html', {
        'stats': stats,
        'products': products,
        'sellers': sellers,
        'seller_invitations': seller_invitations,
        'seller_invite_link': request.session.pop('seller_invite_link', ''),
    })


@admin_required
@require_POST
def create_seller_invitation(request):
    raw_token = secrets.token_urlsafe(32)
    SellerInvitation.objects.create(
        token_hash=hashlib.sha256(raw_token.encode('utf-8')).hexdigest(),
        created_by=request.user,
        expires_at=timezone.now() + timedelta(days=7),
    )
    invite_path = reverse('seller_register', args=[raw_token])
    request.session['seller_invite_link'] = request.build_absolute_uri(invite_path)
    messages.success(request, 'Seller invitation created. It expires in 7 days and can be used once.')
    return redirect('admin_dashboard')


@admin_required
@require_POST
def set_seller_active(request, seller_id):
    seller = get_object_or_404(User, pk=seller_id, role=User.Role.SELLER)
    is_active = request.POST.get('is_active') == 'true'
    seller.is_active = is_active
    seller.save(update_fields=['is_active'])
    if not is_active:
        Product.objects.filter(seller=seller).update(is_active=False)
        messages.success(request, f'{seller.username} was deactivated and their products were hidden.')
    else:
        messages.success(request, f'{seller.username} was reactivated. Review and republish their products as needed.')
    return redirect('admin_dashboard')


@seller_required
def add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        gallery_files = request.FILES.getlist('gallery_images')  # Multiple extra gallery files

        if form.is_valid():
            product = form.save()
            if request.user.role == User.Role.SELLER:
                product.seller = request.user
                product.save(update_fields=['seller'])

            # Save extra gallery images
            for file in gallery_files:
                ProductImage.objects.create(
                    product=product,
                    image=file,
                    alt_text=product.title
                )

            messages.success(request, f"Product '{product.title}' listed successfully!")
            return redirect(
                'admin_dashboard'
                if request.user.role == User.Role.ADMIN or request.user.is_superuser
                else 'seller_dashboard'
            )
    else:
        form = ProductForm()

    return render(request, 'core_app/add_product.html', {'form': form})


def product_management_queryset(user):
    products = Product.objects.select_related('category', 'seller')
    if user.role == User.Role.ADMIN or user.is_superuser:
        return products
    return products.filter(seller__isnull=False)


@seller_required
def edit_product(request, product_id):
    product = get_object_or_404(product_management_queryset(request.user), pk=product_id)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            updated_product = form.save()
            for image in request.FILES.getlist('gallery_images'):
                ProductImage.objects.create(
                    product=updated_product,
                    image=image,
                    alt_text=updated_product.title,
                )
            messages.success(request, f"Product '{updated_product.title}' updated successfully.")
            return redirect(
                'admin_dashboard'
                if request.user.role == User.Role.ADMIN or request.user.is_superuser
                else 'seller_dashboard'
            )
    else:
        form = ProductForm(instance=product)

    return render(request, 'core_app/add_product.html', {
        'form': form,
        'product': product,
        'is_edit': True,
    })


@seller_required
@require_POST
def delete_product(request, product_id):
    product = get_object_or_404(product_management_queryset(request.user), pk=product_id)
    title = product.title
    product.delete()
    messages.success(request, f"Product '{title}' deleted successfully.")
    return redirect(
        'admin_dashboard'
        if request.user.role == User.Role.ADMIN or request.user.is_superuser
        else 'seller_dashboard'
    )

def product_detail(request, slug):
    # Retrieve product by slug or raise 404
    product = get_object_or_404(Product, slug=slug, is_active=True)

    # Fetch related products from the same category (excluding current item)
    related_products = Product.objects.filter(
        category=product.category,
        is_active=True
    ).exclude(id=product.id)[:4]

    user_review = (
        product.reviews.filter(user=request.user).prefetch_related('images').first()
        if request.user.is_authenticated
        else None
    )
    has_delivered_product = (
        request.user.is_authenticated
        and OrderItem.objects.filter(
            product=product,
            order__user=request.user,
            fulfillment_status=OrderItem.FulfillmentStatus.COMPLETED,
        ).exists()
    )
    is_admin = (
        request.user.is_authenticated
        and (request.user.role == User.Role.ADMIN or request.user.is_superuser)
    )
    context = {
        'product': product,
        'related_products': related_products,
        'reviews': product.reviews.select_related('user').prefetch_related('images'),
        'review_form': ProductReviewForm(instance=user_review),
        'review_summary': product.reviews.aggregate(
            average_rating=Avg('rating'),
            review_count=Count('pk'),
        ),
        'user_review': user_review,
        'can_review': is_admin or has_delivered_product or user_review is not None,
        'can_write_review': (
            request.user.is_authenticated
            and (product.seller_id != request.user.pk or is_admin)
            and (is_admin or has_delivered_product or user_review is not None)
        ),
    }
    return render(request, 'core_app/product_detail.html', context)


@login_required(login_url='login')
@require_POST
def save_product_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    is_admin = request.user.role == User.Role.ADMIN or request.user.is_superuser
    if product.seller_id == request.user.pk and not is_admin:
        messages.error(request, 'You cannot review your own product.')
        return redirect('product_detail', slug=slug)

    with transaction.atomic():
        Product.objects.select_for_update().get(pk=product.pk)
        review = ProductReview.objects.filter(product=product, user=request.user).first()
        has_delivered_product = OrderItem.objects.filter(
            product=product,
            order__user=request.user,
            fulfillment_status=OrderItem.FulfillmentStatus.COMPLETED,
        ).exists()
        if not (is_admin or has_delivered_product or review):
            messages.error(request, 'You can review this product after your order is delivered.')
            return redirect('product_detail', slug=slug)

        form = ProductReviewForm(
            request.POST,
            request.FILES,
            instance=review,
        )
        if not form.is_valid():
            for error in form.non_field_errors():
                messages.error(request, error)
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect('product_detail', slug=slug)

        remove_ids = request.POST.getlist('remove_images')
        existing_images = (
            review.images.exclude(pk__in=remove_ids).count()
            if review else 0
        )
        new_images = form.cleaned_data['images']
        if existing_images + len(new_images) > 5:
            messages.error(request, 'A review can include up to 5 photos.')
            return redirect('product_detail', slug=slug)

        review = form.save(commit=False)
        review.product = product
        review.user = request.user
        old_video_name = review.video.name if review.video else ''
        clear_existing_video = (
            form.cleaned_data['clear_video']
            and 'video' not in request.FILES
            and review.video
        )
        if clear_existing_video:
            review.video.delete(save=False)
            review.video = ''
        review.save()
        if remove_ids:
            removed_images = review.images.filter(pk__in=remove_ids)
            for image in removed_images:
                image.image.storage.delete(image.image.name)
            removed_images.delete()
        if (
            old_video_name
            and old_video_name != review.video.name
            and not clear_existing_video
        ):
            review.video.storage.delete(old_video_name)
        ProductReviewImage.objects.bulk_create([
            ProductReviewImage(review=review, image=image)
            for image in new_images
        ])

    messages.success(request, 'Your product review was saved.')
    return redirect('product_detail', slug=slug)


@login_required(login_url='login')
@require_POST
def delete_product_review(request, review_id):
    review = get_object_or_404(ProductReview, pk=review_id, user=request.user)
    slug = review.product.slug
    for image in review.images.all():
        image.image.storage.delete(image.image.name)
    if review.video:
        review.video.delete(save=False)
    review.delete()
    messages.success(request, 'Your product review was deleted.')
    return redirect('product_detail', slug=slug)


@require_POST
def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id, is_active=True)

    try:
        quantity = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        return JsonResponse({
            'success': False,
            'error': 'Invalid quantity parameter.'
        }, status=400)

    if quantity < 1:
        return JsonResponse({
            'success': False,
            'error': 'Quantity must be at least 1.'
        }, status=400)

    override_value = request.POST.get('override', 'false').lower()
    if override_value not in {'true', 'false', '1', '0'}:
        return JsonResponse({
            'success': False,
            'error': 'Invalid quantity update mode.'
        }, status=400)
    override = override_value in {'true', '1'}

    current_quantity = cart.cart.get(str(product.pk), {}).get('quantity', 0)
    requested_total = quantity if override else current_quantity + quantity
    if requested_total > product.stock:
        return JsonResponse({
            'success': False,
            'error': f'Only {product.stock} unit(s) are currently available.',
        }, status=400)

    cart.add(product, quantity=quantity, override_quantity=override)

    cart_items_html = render_to_string(
        'core_app/cart_items.html',
        {'cart': cart},
        request=request,
    )
    total_price = cart.get_total_price()

    return JsonResponse({
        'success': True,
        'message': f'Added {product.title} to bag.',
        'cart_count': len(cart),
        'total_price': f'{total_price:,.2f}',
        'cart_items_html': cart_items_html,
        'item': {
            'product_id': product.id,
            'name': product.title,
            'quantity': cart.cart[str(product.id)]['quantity'],
        }
    })

@require_POST
def cart_remove(request, product_id):
    cart = Cart(request)
    cart.remove(product_id)
    total_price = cart.get_total_price()
    cart_items_html = render_to_string(
        'core_app/cart_items.html',
        {'cart': cart},
        request=request,
    )

    return JsonResponse({
        'success': True,
        'product_id': product_id,
        'cart_count': len(cart),
        'total_price': f'{total_price:,.2f}',
        'cart_items_html': cart_items_html,
        'is_empty': len(cart) == 0,
    })


def cart_detail(request):
    return render(request, 'core_app/cart_detail.html', {'cart': Cart(request)})


def checkout(request):
    cart = Cart(request)
    if not cart.cart:
        return redirect('cart_detail')

    form = CheckoutForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            product_ids = [int(product_id) for product_id in cart.cart]
        except ValueError:
            cart.clear()
            return redirect('cart_detail')
        products = {
            str(product.pk): product
            for product in Product.objects.filter(pk__in=product_ids, is_active=True)
        }
        unavailable = set(cart.cart) - products.keys()
        if unavailable:
            form.add_error(
                None,
                'One or more items in your cart are no longer available. Review your cart and try again.',
            )
        elif (
            form.cleaned_data['payment_method'] == Order.PaymentMethod.RAZORPAY
            and (not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET)
        ):
            logger.error('Razorpay API credentials are not configured.')
            return JsonResponse({
                'success': False,
                'error': (
                    'Razorpay test credentials are not configured. Set '
                    'RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env, then restart the server.'
                ),
            }, status=503)
        else:
            try:
                order, total_amount = create_order_from_cart(
                    request,
                    form,
                    cart,
                    products,
                )
            except InventoryUnavailable as exc:
                form.add_error(
                    None,
                    f'{exc} is out of stock or the available quantity changed. Update your cart and try again.',
                )
            except CartPriceChanged as exc:
                cart.cart[exc.product_id]['price'] = str(exc.price)
                cart.save()
                form.add_error(
                    None,
                    'A product price changed. Your cart total has been updated; review it and submit again.',
                )
            else:
                if order.payment_method == Order.PaymentMethod.CASH_ON_DELIVERY:
                    cart.clear()
                    return redirect('order_confirmation', public_id=order.public_id)

                try:
                    gateway_order = get_razorpay_client().order.create({
                        'amount': int((total_amount * 100).quantize(Decimal('1'))),
                        'currency': 'INR',
                        'receipt': order.public_id.hex,
                        'notes': {'order_public_id': str(order.public_id)},
                    })
                    gateway_order_id = gateway_order.get('id')
                    if not gateway_order_id:
                        raise ValueError('Razorpay did not return an order ID.')
                    order.razorpay_order_id = gateway_order_id
                    order.save(update_fields=['razorpay_order_id'])
                except Exception:
                    logger.exception('Unable to create Razorpay order for order %s', order.public_id)
                    release_order_inventory(order, Order.PaymentStatus.FAILED)
                    return JsonResponse({
                        'success': False,
                        'error': 'Payment setup failed. Please try again later.',
                    }, status=502)

                request.session[f'checkout_cart_{order.public_id}'] = cart.cart
                return JsonResponse({
                    'success': True,
                    'key_id': settings.RAZORPAY_KEY_ID,
                    'razorpay_order_id': gateway_order_id,
                    'amount': int((total_amount * 100).quantize(Decimal('1'))),
                    'currency': 'INR',
                    'name': 'ZAN',
                    'description': f'Order {order.public_id}',
                    'prefill': {
                        'name': order.full_name,
                        'email': order.email,
                    },
                    'verify_url': reverse('payment_verify'),
                    'confirmation_url': reverse(
                        'order_confirmation',
                        kwargs={'public_id': order.public_id},
                    ),
                })

    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'error': 'Please correct the checkout form and try again.',
                'errors': form.errors.get_json_data(),
            }, status=400)

    return render(request, 'core_app/checkout.html', {
        'form': form,
        'cart': cart,
        'total_amount': cart.get_total_price(),
    }, status=400 if request.method == 'POST' else 200)


def order_confirmation(request, public_id):
    order = get_object_or_404(
        Order.objects.prefetch_related('items'),
        public_id=public_id,
    )
    return render(request, 'core_app/order_confirmation.html', {'order': order})


@login_required(login_url='login')
def buyer_profile(request):
    profile_form = UserProfileForm(instance=request.user)
    if request.method == 'POST':
        profile_form = UserProfileForm(
            request.POST,
            request.FILES,
            instance=request.user,
        )
        if profile_form.is_valid():
            old_photo = request.user.profile_photo
            profile_form.save()
            if (
                old_photo
                and old_photo.name != request.user.profile_photo.name
            ):
                old_photo.storage.delete(old_photo.name)
            messages.success(request, 'Your profile photo was updated.')
            return redirect('buyer_profile')
        messages.error(request, 'Please choose a valid profile photo.')

    orders = list(
        Order.objects.filter(user=request.user)
        .prefetch_related(
            Prefetch(
                'items',
                queryset=OrderItem.objects.select_related('product'),
            )
        )
        .order_by('-created_at')
    )
    addresses = []
    seen_addresses = set()
    for order in orders:
        address = (order.full_name, order.address, order.city, order.postal_code)
        if address not in seen_addresses:
            seen_addresses.add(address)
            addresses.append({
                'full_name': order.full_name,
                'address': order.address,
                'city': order.city,
                'postal_code': order.postal_code,
            })

    return render(request, 'core_app/profile.html', {
        'orders': orders,
        'addresses': addresses,
        'profile_form': profile_form,
    })


@login_required(login_url='login')
def order_invoice(request, public_id):
    order = get_object_or_404(
        Order.objects.prefetch_related('items'),
        public_id=public_id,
        user=request.user,
        payment_status=Order.PaymentStatus.PAID,
    )
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f'Invoice {order.public_id}',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='InvoiceRight',
        parent=styles['Normal'],
        alignment=TA_RIGHT,
    ))
    story = [
        Paragraph('INVOICE', styles['Title']),
        Spacer(1, 6 * mm),
        Paragraph(f'<b>Seller:</b> {escape(settings.INVOICE_BUSINESS_NAME)}', styles['Normal']),
    ]
    if settings.INVOICE_BUSINESS_ADDRESS:
        story.append(Paragraph(
            escape(settings.INVOICE_BUSINESS_ADDRESS).replace('\n', '<br/>'),
            styles['Normal'],
        ))
    story.extend([
        Paragraph(
            f'<b>GSTIN:</b> {escape(settings.INVOICE_BUSINESS_GSTIN or "Not configured")}',
            styles['Normal'],
        ),
        Paragraph(f'<b>Order reference:</b> {escape(str(order.public_id))}', styles['Normal']),
        Paragraph(f'<b>Invoice date:</b> {order.created_at:%d %b %Y}', styles['Normal']),
        Paragraph(f'<b>Payment status:</b> {escape(order.get_payment_status_display())}', styles['Normal']),
        Spacer(1, 5 * mm),
        Paragraph('<b>Bill to</b>', styles['Heading2']),
        Paragraph(escape(order.full_name), styles['Normal']),
        Paragraph(escape(order.email), styles['Normal']),
        Paragraph(escape(order.address).replace('\n', '<br/>'), styles['Normal']),
        Paragraph(
            f'{escape(order.city)}, {escape(order.postal_code)}',
            styles['Normal'],
        ),
        Spacer(1, 7 * mm),
    ])

    rows = [[
        Paragraph('<b>Item</b>', styles['Normal']),
        Paragraph('<b>Qty</b>', styles['InvoiceRight']),
        Paragraph('<b>Unit price (INR)</b>', styles['InvoiceRight']),
        Paragraph('<b>Amount (INR)</b>', styles['InvoiceRight']),
    ]]
    for item in order.items.all():
        rows.append([
            Paragraph(escape(item.product_title), styles['Normal']),
            Paragraph(str(item.quantity), styles['InvoiceRight']),
            Paragraph(f'{item.price:,.2f}', styles['InvoiceRight']),
            Paragraph(f'{item.line_total:,.2f}', styles['InvoiceRight']),
        ])

    table = Table(rows, colWidths=[88 * mm, 15 * mm, 35 * mm, 35 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eee7d2')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#b8b1a0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([
        table,
        Spacer(1, 5 * mm),
        Paragraph(
            f'<b>Total paid (INR): {order.total_amount:,.2f}</b>',
            styles['InvoiceRight'],
        ),
        Spacer(1, 5 * mm),
        Paragraph(
            'Order invoice only. GST/tax registration and tax breakdown are not '
            'configured; do not use this document as a statutory GST tax invoice.',
            styles['Italic'],
        ),
    ])
    document.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice-{order.public_id}.pdf"'
    return response


@require_POST
def payment_verify(request):
    payment_id = request.POST.get('razorpay_payment_id', '')
    gateway_order_id = request.POST.get('razorpay_order_id', '')
    signature = request.POST.get('razorpay_signature', '')
    if not payment_id or not gateway_order_id or not signature:
        return JsonResponse({'success': False, 'error': 'Missing payment verification data.'}, status=400)

    order = get_object_or_404(
        Order,
        razorpay_order_id=gateway_order_id,
        payment_method=Order.PaymentMethod.RAZORPAY,
    )
    try:
        client = get_razorpay_client()
        client.utility.verify_payment_signature({
            'razorpay_payment_id': payment_id,
            'razorpay_order_id': gateway_order_id,
            'razorpay_signature': signature,
        })
        payment = client.payment.fetch(payment_id)
    except razorpay.errors.SignatureVerificationError:
        return JsonResponse({'success': False, 'error': 'Payment signature is invalid.'}, status=400)
    except Exception:
        logger.exception('Unable to verify Razorpay payment for order %s', order.public_id)
        return JsonResponse({'success': False, 'error': 'Payment verification failed.'}, status=502)

    expected_amount = int((order.total_amount * 100).quantize(Decimal('1')))
    if (
        payment.get('id') != payment_id
        or payment.get('order_id') != gateway_order_id
        or payment.get('amount') != expected_amount
        or payment.get('currency') != 'INR'
        or payment.get('status') != 'captured'
    ):
        return JsonResponse({
            'success': False,
            'error': 'Payment is not captured for this order yet.',
        }, status=409)

    mark_order_paid(order, payment_id)
    snapshot_key = f'checkout_cart_{order.public_id}'
    cart_snapshot = request.session.get(snapshot_key)
    cart = Cart(request)
    if cart_snapshot is not None and cart.cart == cart_snapshot:
        cart.clear()
    request.session.pop(snapshot_key, None)

    return JsonResponse({
        'success': True,
        'redirect_url': reverse(
            'order_confirmation',
            kwargs={'public_id': order.public_id},
        ),
    })


@csrf_exempt
@require_POST
def payment_webhook(request):
    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    signature = request.headers.get('X-Razorpay-Signature', '')
    if not webhook_secret:
        logger.error('Razorpay webhook secret is not configured.')
        return JsonResponse({'error': 'Webhook is not configured.'}, status=503)

    expected_signature = hmac.new(
        webhook_secret.encode('utf-8'),
        request.body,
        hashlib.sha256,
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected_signature, signature):
        return JsonResponse({'error': 'Invalid webhook signature.'}, status=400)

    try:
        event_data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid webhook payload.'}, status=400)

    if not isinstance(event_data, dict) or not isinstance(event_data.get('payload'), dict):
        return JsonResponse({'error': 'Invalid webhook payload.'}, status=400)

    event = event_data.get('event')
    if not isinstance(event, str):
        return JsonResponse({'error': 'Invalid webhook event.'}, status=400)
    payload = event_data.get('payload', {})
    payment_payload = payload.get('payment', {})
    order_payload = payload.get('order', {})
    payment_entity = (
        payment_payload.get('entity', {})
        if isinstance(payment_payload, dict)
        else {}
    )
    order_entity = (
        order_payload.get('entity', {})
        if isinstance(order_payload, dict)
        else {}
    )
    if not isinstance(payment_entity, dict) or not isinstance(order_entity, dict):
        return JsonResponse({'error': 'Invalid webhook payload.'}, status=400)

    if event in {'payment.captured', 'payment.failed'}:
        gateway_order_id = payment_entity.get('order_id')
        payment_id = payment_entity.get('id', '')
        amount = payment_entity.get('amount')
        currency = payment_entity.get('currency')
        is_captured = payment_entity.get('status') == 'captured'
    elif event == 'order.paid':
        gateway_order_id = order_entity.get('id')
        payment_id = payment_entity.get('id', '')
        amount = order_entity.get('amount_paid')
        currency = order_entity.get('currency')
        is_captured = order_entity.get('status') == 'paid'
    else:
        return JsonResponse({'status': 'ignored'})

    if not gateway_order_id:
        return JsonResponse({'error': 'Invalid captured payment payload.'}, status=400)

    try:
        order = Order.objects.get(
            razorpay_order_id=gateway_order_id,
            payment_method=Order.PaymentMethod.RAZORPAY,
        )
    except Order.DoesNotExist:
        logger.warning('Razorpay webhook references unknown order %s', gateway_order_id)
        return JsonResponse({'error': 'Unknown order.'}, status=404)

    expected_amount = int((order.total_amount * 100).quantize(Decimal('1')))
    if event == 'payment.failed':
        if (
            payment_entity.get('status') != 'failed'
            or isinstance(amount, bool)
            or amount != expected_amount
            or currency != 'INR'
        ):
            return JsonResponse({'error': 'Payment amount or currency does not match.'}, status=400)
        failed_order = release_order_inventory(order, Order.PaymentStatus.FAILED)
        if failed_order.payment_status == Order.PaymentStatus.FAILED and payment_id:
            Order.objects.filter(pk=failed_order.pk).update(payment_reference=payment_id)
        return JsonResponse({'status': 'ok'})

    if not is_captured:
        return JsonResponse({'error': 'Invalid captured payment payload.'}, status=400)
    if isinstance(amount, bool) or amount != expected_amount or currency != 'INR':
        logger.error('Razorpay webhook amount mismatch for order %s', order.public_id)
        return JsonResponse({'error': 'Payment amount or currency does not match.'}, status=400)

    mark_order_paid(order, payment_id)
    return JsonResponse({'status': 'ok'})