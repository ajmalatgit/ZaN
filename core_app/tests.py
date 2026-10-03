from decimal import Decimal
from datetime import timedelta
import hashlib
import hmac
import json
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .cart import Cart
from .models import (
    Category,
    Order,
    OrderItem,
    Product,
    ProductReview,
    ProductReviewImage,
    SellerInvitation,
    User,
)


def make_test_image(name='photo.jpg'):
    buffer = BytesIO()
    Image.new('RGB', (2, 2), color='gold').save(buffer, format='JPEG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/jpeg')


class SessionCartTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.product = Product.objects.create(
            category=self.category,
            title='Leather Wallet',
            slug='leather-wallet',
            price=Decimal('125.50'),
            stock=100,
            primary_image='products/wallet.jpg',
        )
        self.other_product = Product.objects.create(
            category=self.category,
            title='Leather Belt',
            slug='leather-belt',
            price=Decimal('200.00'),
            stock=100,
            primary_image='products/belt.jpg',
        )

    def test_guest_can_add_product_to_session_cart(self):
        response = self.client.post(reverse('cart_add', args=[self.product.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {
            'success': True,
            'message': 'Added Leather Wallet to bag.',
            'cart_count': 1,
            'total_price': '125.50',
            'cart_items_html': response.json()['cart_items_html'],
            'item': {
                'product_id': self.product.pk,
                'name': 'Leather Wallet',
                'quantity': 1,
            },
        })
        self.assertEqual(
            self.client.session['cart'][str(self.product.pk)],
            {'quantity': 1, 'price': '125.50'},
        )
        self.assertIn('Leather Wallet', response.json()['cart_items_html'])

    def test_guest_can_increment_and_set_cart_quantity(self):
        add_url = reverse('cart_add', args=[self.product.pk])
        self.client.post(add_url, {'quantity': '2'})
        incremented = self.client.post(add_url, {'quantity': '3'})

        self.assertEqual(incremented.json()['cart_count'], 5)
        self.assertEqual(incremented.json()['total_price'], '627.50')

        updated = self.client.post(add_url, {'quantity': '4', 'override': 'true'})

        self.assertEqual(updated.json()['cart_count'], 4)
        self.assertEqual(updated.json()['total_price'], '502.00')
        self.assertEqual(
            self.client.session['cart'][str(self.product.pk)]['quantity'],
            4,
        )

    def test_add_and_quantity_update_cannot_exceed_stock(self):
        self.product.stock = 2
        self.product.save(update_fields=['stock'])
        add_url = reverse('cart_add', args=[self.product.pk])

        added = self.client.post(add_url, {'quantity': 2})
        rejected = self.client.post(add_url)

        self.assertEqual(added.status_code, 200)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['quantity'], 2)

    def test_add_rejects_invalid_quantity_and_inactive_product(self):
        add_url = reverse('cart_add', args=[self.product.pk])
        for quantity in ('0', '-1', 'invalid'):
            with self.subTest(quantity=quantity):
                response = self.client.post(add_url, {'quantity': quantity})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()['success'])

        self.product.is_active = False
        self.product.save(update_fields=['is_active'])
        response = self.client.post(add_url)
        self.assertEqual(response.status_code, 404)

    def test_remove_updates_session_and_totals(self):
        self.client.post(reverse('cart_add', args=[self.product.pk]))
        self.client.post(reverse('cart_add', args=[self.other_product.pk]))

        response = self.client.post(reverse('cart_remove', args=[self.product.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cart_count'], 1)
        self.assertEqual(response.json()['total_price'], '200.00')
        self.assertNotIn(str(self.product.pk), self.client.session['cart'])
        self.assertIn('Leather Belt', response.json()['cart_items_html'])
        self.assertNotIn('Leather Wallet', response.json()['cart_items_html'])

    def test_remove_is_idempotent_for_missing_product(self):
        response = self.client.post(reverse('cart_remove', args=[99999]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['is_empty'])

    def test_cart_detail_displays_guest_items_and_line_totals(self):
        self.client.post(reverse('cart_add', args=[self.product.pk]), {'quantity': 2})

        response = self.client.get(reverse('cart_detail'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Leather Wallet')
        self.assertContains(response, 'Qty: <span class="zan-item-quantity">2</span>')
        self.assertContains(response, '₹251.00')
        self.assertContains(response, 'cartPageSubtotal')

    def test_guest_cart_is_available_from_storefront_and_product_detail(self):
        home_response = self.client.get(reverse('home'))
        detail_response = self.client.get(
            reverse('product_detail', args=[self.product.slug])
        )

        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, 'id="cartDrawer"')
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(
            detail_response,
            f'action="{reverse("cart_add", args=[self.product.pk])}"',
        )

        self.client.post(reverse('cart_add', args=[self.product.pk]))
        refreshed_home = self.client.get(reverse('home'))
        self.assertContains(refreshed_home, 'Leather Wallet')

    def test_cart_discards_malformed_and_deleted_session_entries(self):
        session = self.client.session
        session['cart'] = {
            'not-an-id': {'quantity': 1, 'price': '1.00'},
            str(self.product.pk): {'quantity': 'bad', 'price': '1.00'},
            '99999': {'quantity': 1, 'price': '2.00'},
        }
        session.save()

        cart = Cart(type('Request', (), {'session': session})())
        self.assertEqual(list(cart), [])
        self.assertEqual(cart.cart, {})


class CatalogTests(TestCase):
    def setUp(self):
        self.accessories = Category.objects.create(name='Accessories', slug='accessories')
        self.apparel = Category.objects.create(name='Apparel', slug='apparel')
        self.wallet = Product.objects.create(
            category=self.accessories,
            title='Leather Wallet',
            slug='catalog-leather-wallet',
            description='Handcrafted full grain leather accessory.',
            price=Decimal('125.50'),
            stock=5,
            primary_image='products/wallet.jpg',
        )
        self.belt = Product.objects.create(
            category=self.accessories,
            title='Leather Belt',
            slug='catalog-leather-belt',
            description='Durable everyday belt.',
            price=Decimal('200.00'),
            stock=4,
            primary_image='products/belt.jpg',
        )
        self.shirt = Product.objects.create(
            category=self.apparel,
            title='Cotton Shirt',
            slug='catalog-cotton-shirt',
            description='Lightweight summer clothing.',
            price=Decimal('800.00'),
            stock=3,
            primary_image='products/shirt.jpg',
        )

    def test_catalog_search_matches_title_or_description(self):
        title_match = self.client.get(reverse('catalog'), {'q': 'wallet'})
        description_match = self.client.get(reverse('catalog'), {'q': 'summer clothing'})

        self.assertEqual(title_match.status_code, 200)
        self.assertContains(title_match, 'Leather Wallet')
        self.assertNotContains(title_match, 'Leather Belt')
        self.assertContains(title_match, 'id="navSearchQuery"')
        self.assertEqual(description_match.status_code, 200)
        self.assertContains(description_match, 'Cotton Shirt')
        self.assertNotContains(description_match, 'Leather Wallet')

    def test_catalog_filters_category_and_price_range_together(self):
        response = self.client.get(reverse('catalog'), {
            'category': self.accessories.slug,
            'min_price': '150',
            'max_price': '250',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Leather Belt')
        self.assertNotContains(response, 'Leather Wallet')
        self.assertNotContains(response, 'Cotton Shirt')
        self.assertContains(response, 'name="min_price"')

    def test_catalog_ignores_inactive_products(self):
        self.shirt.is_active = False
        self.shirt.save(update_fields=['is_active'])

        response = self.client.get(reverse('catalog'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Cotton Shirt')
        self.assertNotContains(response, 'Apparel')

    def test_catalog_invalid_price_range_reports_validation_and_shows_products(self):
        response = self.client.get(reverse('catalog'), {
            'min_price': '500',
            'max_price': '10',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a valid minimum and maximum price.')
        self.assertContains(response, 'Leather Wallet')

    def test_catalog_paginates_ten_products_and_preserves_filters(self):
        for index in range(11):
            Product.objects.create(
                category=self.accessories,
                title=f'Catalog Item {index:02}',
                slug=f'catalog-item-{index}',
                description='Pagination test item',
                price=Decimal('50.00'),
                stock=1,
                primary_image='products/item.jpg',
            )

        first_page = self.client.get(reverse('catalog'), {
            'q': 'pagination',
            'category': self.accessories.slug,
            'min_price': '0',
            'max_price': '100',
        })
        second_page = self.client.get(reverse('catalog'), {
            'q': 'pagination',
            'category': self.accessories.slug,
            'min_price': '0',
            'max_price': '100',
            'page': '2',
        })

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.context['page_obj'].paginator.per_page, 10)
        self.assertEqual(len(first_page.context['products']), 10)
        self.assertEqual(first_page.context['page_obj'].number, 1)
        self.assertEqual(second_page.context['page_obj'].number, 2)
        self.assertEqual(len(second_page.context['products']), 1)
        self.assertContains(first_page, 'category=accessories')
        self.assertContains(first_page, 'min_price=0')

    def test_navigation_search_is_available_on_storefront(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('catalog'))
        self.assertContains(response, 'Search products')
        self.assertContains(response, 'id="toastStack"')
        self.assertContains(response, 'Dismiss notification')
        self.assertContains(response, 'class="mobile-menu-toggle"')
        self.assertContains(response, 'aria-controls="mainNavigation"')
        self.assertContains(response, 'class="nav-utilities"')
        self.assertContains(response, 'id="navCartCount"')
        self.assertContains(response, 'placeholder="Search products..."')
        self.assertContains(response, 'class="mobile-search-toggle"')
        self.assertContains(response, 'class="account-menu-toggle"')
        self.assertContains(response, 'aria-label="Account menu"')
        self.assertContains(response, 'id="accountMenu"')
        self.assertNotContains(response, 'name="role"')
        self.assertContains(response, 'class="notification-menu"')
        self.assertContains(response, 'aria-controls="notificationPanel"')
        self.assertContains(response, 'id="notificationPanel"')
        self.assertContains(response, 'class="notification-unread-dot"')

    def test_homepage_shows_eight_latest_active_products_and_links_to_catalog(self):
        for index in range(9):
            Product.objects.create(
                category=self.accessories,
                title=f'Home Feature {index:02}',
                slug=f'home-feature-{index}',
                description='Featured collection test.',
                price=Decimal('25.00'),
                stock=0 if index == 8 else 1,
                primary_image='products/feature.jpg',
            )

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['products']), 8)
        self.assertContains(response, reverse('catalog'))
        self.assertContains(response, 'Out of Stock')
        self.assertNotContains(response, 'Home Feature 00')


class CheckoutTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.product = Product.objects.create(
            category=self.category,
            title='Leather Wallet',
            slug='leather-wallet',
            price=Decimal('125.50'),
            stock=100,
            primary_image='products/wallet.jpg',
        )
        self.checkout_url = reverse('checkout')

    def add_product_to_cart(self, quantity=1):
        return self.client.post(
            reverse('cart_add', args=[self.product.pk]),
            {'quantity': quantity},
        )

    def test_checkout_get_shows_shipping_form_and_cart_total(self):
        self.add_product_to_cart(quantity=2)

        response = self.client.get(self.checkout_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order summary')
        self.assertContains(response, '₹251.00')

    @override_settings(RAZORPAY_KEY_ID='test_key_id', RAZORPAY_KEY_SECRET='test_key_secret')
    @patch('core_app.views.get_razorpay_client')
    def test_guest_checkout_creates_provider_order(self, get_client):
        self.add_product_to_cart(quantity=2)
        get_client.return_value.order.create.return_value = {'id': 'order_test123'}
        response = self.client.post(self.checkout_url, {
            **self.checkout_data(),
            'payment_method': Order.PaymentMethod.RAZORPAY,
        })

        order = Order.objects.get()
        item = OrderItem.objects.get(order=order)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['amount'], 25100)
        self.assertEqual(response.json()['currency'], 'INR')
        self.assertEqual(response.json()['razorpay_order_id'], 'order_test123')
        self.assertIsNone(order.user)
        self.assertEqual(order.total_amount, Decimal('251.00'))
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(order.payment_method, Order.PaymentMethod.RAZORPAY)
        self.assertEqual(order.razorpay_order_id, 'order_test123')
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.product_title, 'Leather Wallet')
        self.assertEqual(item.price, Decimal('125.50'))
        self.assertEqual(item.quantity, 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 98)
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['quantity'], 2)
        create_order_data = get_client.return_value.order.create.call_args.args[0]
        self.assertEqual(create_order_data['amount'], 25100)
        self.assertEqual(create_order_data['currency'], 'INR')

    def test_cash_on_delivery_creates_order_without_gateway_and_clears_cart(self):
        self.add_product_to_cart(quantity=2)

        response = self.client.post(self.checkout_url, {
            **self.checkout_data(),
            'payment_method': Order.PaymentMethod.CASH_ON_DELIVERY,
        })

        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse('order_confirmation', args=[order.public_id]),
        )
        self.assertEqual(order.payment_method, Order.PaymentMethod.CASH_ON_DELIVERY)
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertFalse(order.is_paid)
        self.assertEqual(order.total_amount, Decimal('251.00'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 98)
        self.assertIsNone(order.razorpay_order_id)
        self.assertEqual(self.client.session.get('cart'), {})
        self.assertContains(
            self.client.get(reverse('order_confirmation', args=[order.public_id])),
            'Pay ₹251.00 when it is delivered.',
        )

    @staticmethod
    def checkout_data():
        return {
            'full_name': 'Asha Example',
            'email': 'asha@example.com',
            'address': '12 Market Road',
            'city': 'Mumbai',
            'postal_code': '400001',
        }

    @override_settings(RAZORPAY_KEY_ID='test_key_id', RAZORPAY_KEY_SECRET='test_key_secret')
    @patch('core_app.views.get_razorpay_client')
    def test_authenticated_checkout_attaches_user(self, get_client):
        user = User.objects.create_user(username='buyer', password='safe-password')
        self.client.force_login(user)
        self.add_product_to_cart()
        get_client.return_value.order.create.return_value = {'id': 'order_test456'}

        response = self.client.post(self.checkout_url, self.checkout_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.get().user, user)

    def test_invalid_checkout_keeps_cart_and_creates_no_order(self):
        self.add_product_to_cart()

        response = self.client.post(self.checkout_url, {
            'full_name': '',
            'email': 'not-an-email',
            'address': '',
            'city': '',
            'postal_code': '',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['quantity'], 1)

    def test_unavailable_product_prevents_order_creation(self):
        self.add_product_to_cart()
        self.product.is_active = False
        self.product.save(update_fields=['is_active'])

        response = self.client.post(self.checkout_url, {
            'full_name': 'Asha Example',
            'email': 'asha@example.com',
            'address': '12 Market Road',
            'city': 'Mumbai',
            'postal_code': '400001',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertIn('no longer available', response.json()['errors']['__all__'][0]['message'])
        self.assertEqual(Order.objects.count(), 0)
        self.assertIn(str(self.product.pk), self.client.session['cart'])

    def test_checkout_rejects_quantity_when_stock_changes_after_cart_add(self):
        self.add_product_to_cart(quantity=2)
        self.product.stock = 1
        self.product.save(update_fields=['stock'])

        response = self.client.post(self.checkout_url, {
            **self.checkout_data(),
            'payment_method': Order.PaymentMethod.CASH_ON_DELIVERY,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertIn('available quantity changed', response.json()['errors']['__all__'][0]['message'])
        self.assertEqual(Order.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['quantity'], 2)

    def test_checkout_updates_cart_when_product_price_changes(self):
        self.add_product_to_cart()
        self.product.price = Decimal('130.00')
        self.product.save(update_fields=['price'])

        response = self.client.post(self.checkout_url, {
            **self.checkout_data(),
            'payment_method': Order.PaymentMethod.CASH_ON_DELIVERY,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertIn('price changed', response.json()['errors']['__all__'][0]['message'])
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['price'], '130.00')
        self.assertEqual(Order.objects.count(), 0)

    def test_empty_cart_cannot_checkout(self):
        response = self.client.get(self.checkout_url)

        self.assertRedirects(response, reverse('cart_detail'))
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_rejects_unknown_payment_method(self):
        self.add_product_to_cart()

        response = self.client.post(self.checkout_url, {
            **self.checkout_data(),
            'payment_method': 'UNSUPPORTED',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.assertIn(str(self.product.pk), self.client.session['cart'])

    def test_order_confirmation_uses_unpredictable_public_id(self):
        self.add_product_to_cart()
        response = self.checkout_order()
        order = Order.objects.get()

        confirmation = self.client.get(
            reverse('order_confirmation', args=[order.public_id])
        )

        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, str(order.public_id))
        self.assertContains(confirmation, 'awaiting payment confirmation')

    def test_order_item_snapshot_survives_product_deletion(self):
        self.add_product_to_cart(quantity=2)
        self.checkout_order()
        order = Order.objects.get()
        self.product.delete()

        item = OrderItem.objects.get(order=order)
        self.assertIsNone(item.product)
        self.assertEqual(item.product_title, 'Leather Wallet')
        self.assertEqual(item.price, Decimal('125.50'))
        self.assertEqual(item.line_total, Decimal('251.00'))

    @override_settings(RAZORPAY_KEY_ID='test_key_id', RAZORPAY_KEY_SECRET='test_key_secret')
    @patch('core_app.views.get_razorpay_client')
    def test_checkout_failure_keeps_cart_and_reports_gateway_error(self, get_client):
        self.add_product_to_cart()
        get_client.return_value.order.create.side_effect = RuntimeError('gateway unavailable')

        response = self.client.post(self.checkout_url, self.checkout_data())

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()['success'])
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['quantity'], 1)
        self.assertEqual(Order.objects.get().payment_status, Order.PaymentStatus.FAILED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 100)

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_checkout_explains_missing_gateway_configuration_without_creating_order(self):
        self.add_product_to_cart()

        response = self.client.post(self.checkout_url, self.checkout_data())

        self.assertEqual(response.status_code, 503)
        self.assertIn('RAZORPAY_KEY_ID', response.json()['error'])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(self.client.session['cart'][str(self.product.pk)]['quantity'], 1)

    @override_settings(RAZORPAY_KEY_ID='test_key_id', RAZORPAY_KEY_SECRET='test_key_secret')
    @patch('core_app.views.get_razorpay_client')
    def checkout_order(self, get_client):
        get_client.return_value.order.create.return_value = {'id': 'order_confirmation'}
        return self.client.post(self.checkout_url, self.checkout_data())


@override_settings(
    RAZORPAY_KEY_ID='test_key_id',
    RAZORPAY_KEY_SECRET='test_key_secret',
    RAZORPAY_WEBHOOK_SECRET='test_webhook_secret',
)
class RazorpayPaymentTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.product = Product.objects.create(
            category=self.category,
            title='Leather Wallet',
            slug='leather-wallet',
            price=Decimal('125.50'),
            stock=3,
            primary_image='products/wallet.jpg',
        )
        self.order = Order.objects.create(
            full_name='Asha Example',
            email='asha@example.com',
            address='12 Market Road',
            city='Mumbai',
            postal_code='400001',
            total_amount=Decimal('251.00'),
            razorpay_order_id='order_test123',
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_title=self.product.title,
            price=self.product.price,
            quantity=2,
        )

    def webhook(self, payload, signature=None):
        body = json.dumps(payload).encode('utf-8')
        if signature is None:
            signature = hmac.new(
                b'test_webhook_secret',
                body,
                hashlib.sha256,
            ).hexdigest()
        return self.client.post(
            reverse('payment_webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

    def payment_captured_payload(self, amount=25100):
        return {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_test123',
                        'order_id': 'order_test123',
                        'amount': amount,
                        'currency': 'INR',
                        'status': 'captured',
                    },
                },
            },
        }

    def test_webhook_signature_and_amount_mark_order_paid(self):
        response = self.webhook(self.payment_captured_payload())

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.order.payment_reference, 'pay_test123')
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(self.order.status, Order.Status.PROCESSING)

    def test_webhook_rejects_invalid_signature(self):
        response = self.webhook(self.payment_captured_payload(), signature='invalid')

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_webhook_rejects_amount_mismatch(self):
        response = self.webhook(self.payment_captured_payload(amount=25099))

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_order_paid_webhook_marks_order_paid(self):
        payload = {
            'event': 'order.paid',
            'payload': {
                'order': {
                    'entity': {
                        'id': 'order_test123',
                        'amount_paid': 25100,
                        'currency': 'INR',
                        'status': 'paid',
                    },
                },
                'payment': {
                    'entity': {
                        'id': 'pay_test_order_paid',
                    },
                },
            },
        }

        response = self.webhook(payload)

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.order.payment_reference, 'pay_test_order_paid')

    def test_webhook_is_idempotent(self):
        self.webhook(self.payment_captured_payload())
        paid_at = Order.objects.get(pk=self.order.pk).paid_at
        response = self.webhook(self.payment_captured_payload())

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.paid_at, paid_at)
        self.assertEqual(self.order.payment_reference, 'pay_test123')

    def test_payment_failed_webhook_updates_payment_state(self):
        self.product.stock = 1
        self.product.save(update_fields=['stock'])
        payload = {
            'event': 'payment.failed',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_failed123',
                        'order_id': 'order_test123',
                        'amount': 25100,
                        'currency': 'INR',
                        'status': 'failed',
                    },
                },
            },
        }

        response = self.webhook(payload)

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.FAILED)
        self.assertEqual(self.order.payment_reference, 'pay_failed123')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    @override_settings(RAZORPAY_WEBHOOK_SECRET='')
    def test_webhook_reports_missing_signing_secret(self):
        response = self.webhook(self.payment_captured_payload())

        self.assertEqual(response.status_code, 503)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    @patch('core_app.views.get_razorpay_client')
    def test_payment_callback_verifies_signature_and_captured_amount(self, get_client):
        client = get_client.return_value
        client.payment.fetch.return_value = {
            'id': 'pay_test123',
            'order_id': 'order_test123',
            'amount': 25100,
            'currency': 'INR',
            'status': 'captured',
        }

        response = self.client.post(reverse('payment_verify'), {
            'razorpay_payment_id': 'pay_test123',
            'razorpay_order_id': 'order_test123',
            'razorpay_signature': 'valid',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(Order.objects.get(pk=self.order.pk).is_paid)
        client.utility.verify_payment_signature.assert_called_once()

    @patch('core_app.views.get_razorpay_client')
    def test_payment_callback_does_not_mark_uncaptured_payment_paid(self, get_client):
        get_client.return_value.payment.fetch.return_value = {
            'id': 'pay_test123',
            'order_id': 'order_test123',
            'amount': 25100,
            'currency': 'INR',
            'status': 'authorized',
        }

        response = self.client.post(reverse('payment_verify'), {
            'razorpay_payment_id': 'pay_test123',
            'razorpay_order_id': 'order_test123',
            'razorpay_signature': 'valid',
        })

        self.assertEqual(response.status_code, 409)
        self.assertFalse(Order.objects.get(pk=self.order.pk).is_paid)


class BuyerProfileAndInvoiceTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            username='invoicebuyer',
            password='safe-password',
        )
        self.other_buyer = User.objects.create_user(
            username='otherbuyer',
            password='safe-password',
        )
        self.order = Order.objects.create(
            user=self.buyer,
            full_name='Invoice Buyer',
            email='invoice@example.com',
            address='22 Delivery Lane',
            city='Pune',
            postal_code='411001',
            total_amount=Decimal('251.00'),
            payment_status=Order.PaymentStatus.PAID,
        )
        category = Category.objects.create(name='Accessories', slug='buyer-order-accessories')
        product = Product.objects.create(
            category=category,
            title='Buyer History Wallet',
            slug='buyer-history-wallet',
            price=Decimal('125.50'),
            stock=2,
            primary_image='products/wallet.jpg',
        )
        OrderItem.objects.create(
            order=self.order,
            product=product,
            product_title='Leather Wallet',
            seller=None,
            price=Decimal('125.50'),
            quantity=2,
        )
        self.other_order = Order.objects.create(
            user=self.other_buyer,
            full_name='Other Buyer',
            email='other@example.com',
            address='1 Other Road',
            city='Delhi',
            postal_code='110001',
            total_amount=Decimal('50.00'),
            payment_status=Order.PaymentStatus.PAID,
        )

    def test_profile_requires_authentication(self):
        response = self.client.get(reverse('buyer_profile'))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("buyer_profile")}',
        )

    def test_profile_shows_only_current_users_orders_and_addresses(self):
        self.client.force_login(self.buyer)

        response = self.client.get(reverse('buyer_profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(self.order.public_id))
        self.assertContains(response, 'Payment: Paid')
        self.assertContains(response, 'Tracking: Pending')
        self.assertContains(response, '22 Delivery Lane')
        self.assertContains(response, 'order-product-thumb')
        self.assertContains(response, 'products/wallet.jpg')
        self.assertNotContains(response, str(self.other_order.public_id))
        self.assertNotContains(response, '1 Other Road')
        self.assertContains(
            response,
            reverse('order_invoice', args=[self.order.public_id]),
        )

    def test_invoice_is_downloadable_for_paid_order_owner(self):
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse('order_invoice', args=[self.order.public_id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_invoice_is_not_available_to_other_users_or_for_unpaid_orders(self):
        unpaid_order = Order.objects.create(
            user=self.buyer,
            full_name='Invoice Buyer',
            email='invoice@example.com',
            address='22 Delivery Lane',
            city='Pune',
            postal_code='411001',
            total_amount=Decimal('25.00'),
        )

        self.client.force_login(self.other_buyer)
        private_response = self.client.get(
            reverse('order_invoice', args=[self.order.public_id])
        )
        self.assertEqual(private_response.status_code, 404)

        self.client.force_login(self.buyer)
        unpaid_response = self.client.get(
            reverse('order_invoice', args=[unpaid_order.public_id])
        )
        self.assertEqual(unpaid_response.status_code, 404)

    def test_invoice_requires_authentication(self):
        response = self.client.get(
            reverse('order_invoice', args=[self.order.public_id])
        )

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("order_invoice", args=[self.order.public_id])}',
        )


class ProductManagementTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.seller = User.objects.create_user(
            username='sellerone',
            password='safe-password',
            role=User.Role.SELLER,
        )
        self.other_seller = User.objects.create_user(
            username='sellertwo',
            password='safe-password',
            role=User.Role.SELLER,
        )
        self.admin = User.objects.create_user(
            username='catalogadmin',
            password='safe-password',
            role=User.Role.ADMIN,
        )
        self.owned_product = Product.objects.create(
            category=self.category,
            seller=self.seller,
            title='Seller Wallet',
            slug='seller-wallet',
            price=Decimal('100.00'),
            primary_image='products/wallet.jpg',
        )
        self.other_product = Product.objects.create(
            category=self.category,
            seller=self.other_seller,
            title='Other Seller Belt',
            slug='other-seller-belt',
            price=Decimal('200.00'),
            primary_image='products/belt.jpg',
        )
        self.unassigned_product = Product.objects.create(
            category=self.category,
            title='Legacy Product',
            slug='legacy-product',
            price=Decimal('50.00'),
            primary_image='products/legacy.jpg',
        )

    def test_seller_dashboard_shows_only_owned_products_with_actions(self):
        self.client.force_login(self.seller)

        response = self.client.get(reverse('seller_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Seller Wallet')
        self.assertContains(response, reverse('edit_product', args=[self.owned_product.pk]))
        self.assertContains(response, reverse('delete_product', args=[self.owned_product.pk]))
        self.assertContains(response, 'Other Seller Belt')
        self.assertNotContains(response, 'Legacy Product')

    def test_seller_can_edit_owned_product_and_slug_tracks_title(self):
        self.client.force_login(self.seller)

        response = self.client.post(
            reverse('edit_product', args=[self.owned_product.pk]),
            {
                'category': self.category.pk,
                'title': 'Updated Seller Wallet',
                'description': 'Updated description',
                'price': '110.00',
                'stock': 5,
                'is_active': 'on',
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('seller_dashboard'))
        self.assertContains(response, 'toast-success')
        self.assertContains(response, "Product &#x27;Updated Seller Wallet&#x27; updated successfully.")
        self.owned_product.refresh_from_db()
        self.assertEqual(self.owned_product.title, 'Updated Seller Wallet')
        self.assertEqual(self.owned_product.slug, 'updated-seller-wallet')
        self.assertEqual(self.owned_product.seller, self.seller)

    def test_seller_can_manage_other_sellers_products_but_not_unassigned_products(self):
        self.client.force_login(self.seller)
        edit_response = self.client.post(
            reverse('edit_product', args=[self.other_product.pk]),
            {
                'category': self.category.pk,
                'title': 'Updated Belt',
                'description': 'Updated by another seller',
                'price': '205.00',
                'stock': 3,
                'is_active': 'on',
            },
        )
        self.assertRedirects(edit_response, reverse('seller_dashboard'))
        self.other_product.refresh_from_db()
        self.assertEqual(self.other_product.title, 'Updated Belt')
        self.assertEqual(self.other_product.seller, self.other_seller)

        delete_response = self.client.post(
            reverse('delete_product', args=[self.other_product.pk])
        )
        self.assertRedirects(delete_response, reverse('seller_dashboard'))
        self.assertFalse(Product.objects.filter(pk=self.other_product.pk).exists())

        legacy_edit_response = self.client.get(
            reverse('edit_product', args=[self.unassigned_product.pk])
        )
        legacy_delete_response = self.client.post(
            reverse('delete_product', args=[self.unassigned_product.pk])
        )
        self.assertEqual(legacy_edit_response.status_code, 404)
        self.assertEqual(legacy_delete_response.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=self.unassigned_product.pk).exists())

    def test_seller_delete_requires_post(self):
        self.client.force_login(self.seller)

        response = self.client.get(reverse('delete_product', args=[self.owned_product.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Product.objects.filter(pk=self.owned_product.pk).exists())

    def test_admin_can_edit_and_delete_any_product(self):
        self.client.force_login(self.admin)

        edit_response = self.client.get(reverse('edit_product', args=[self.other_product.pk]))
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, 'Edit Product')

        delete_response = self.client.post(
            reverse('delete_product', args=[self.unassigned_product.pk])
        )
        self.assertRedirects(delete_response, reverse('admin_dashboard'))
        self.assertFalse(Product.objects.filter(pk=self.unassigned_product.pk).exists())

    def test_admin_catalog_shows_small_product_images(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'product-list-thumb')
        self.assertContains(response, 'products/wallet.jpg')
        self.assertContains(response, 'products/belt.jpg')

    def test_admin_can_deactivate_seller_and_hide_products_without_losing_orders(self):
        order = Order.objects.create(
            full_name='Buyer',
            email='buyer@example.com',
            address='1 Main St',
            city='Pune',
            postal_code='411001',
            total_amount=Decimal('100.00'),
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.owned_product,
            seller=self.seller,
            product_title=self.owned_product.title,
            price=self.owned_product.price,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('set_seller_active', args=[self.seller.pk]),
            {'is_active': 'false'},
        )

        self.assertRedirects(response, reverse('admin_dashboard'))
        self.seller.refresh_from_db()
        self.owned_product.refresh_from_db()
        item.refresh_from_db()
        self.assertFalse(self.seller.is_active)
        self.assertFalse(self.owned_product.is_active)
        self.assertEqual(item.seller_id, self.seller.pk)
        self.assertEqual(item.product_id, self.owned_product.pk)
        self.client.force_login(self.seller)
        blocked = self.client.get(reverse('seller_dashboard'))
        self.assertRedirects(blocked, reverse('login'))

    def test_seller_dashboard_lists_manageable_products_from_other_sellers(self):
        self.client.force_login(self.seller)

        response = self.client.get(reverse('seller_dashboard'))

        self.assertContains(response, 'Other Seller Belt')
        self.assertContains(
            response,
            reverse('edit_product', args=[self.other_product.pk]),
        )

    def test_seller_can_add_optional_product_video_during_edit(self):
        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                self.client.force_login(self.seller)
                response = self.client.post(
                    reverse('edit_product', args=[self.owned_product.pk]),
                    {
                        'category': self.category.pk,
                        'title': self.owned_product.title,
                        'description': self.owned_product.description,
                        'price': '100.00',
                        'stock': 2,
                        'is_active': 'on',
                        'video': SimpleUploadedFile(
                            'product.mp4',
                            b'test video data',
                            content_type='video/mp4',
                        ),
                    },
                )

                self.assertRedirects(response, reverse('seller_dashboard'))
                self.owned_product.refresh_from_db()
                self.assertTrue(self.owned_product.video.name.endswith('.mp4'))

    def test_authenticated_navigation_links_to_buyer_profile(self):
        self.client.force_login(self.seller)

        response = self.client.get(reverse('seller_dashboard'))

        self.assertContains(response, 'class="account-menu-toggle"')
        self.assertContains(response, 'aria-label="Account: sellerone"')
        self.assertContains(response, 'class="account-menu-username">sellerone</span>')
        self.assertContains(response, reverse('buyer_profile'))
        self.assertContains(response, 'Logout (sellerone)')


class SellerInvitationAndProfileTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='inviteadmin',
            password='safe-password',
            role=User.Role.ADMIN,
        )

    def registration_data(self, username='newuser'):
        return {
            'username': username,
            'email': f'{username}@example.com',
            'phone_number': '5551234567',
            'company_name': 'Example Company',
            'password': 'strong-password-123',
            'confirm_password': 'strong-password-123',
        }

    def test_public_registration_cannot_create_seller_by_posting_role(self):
        response = self.client.post(
            reverse('register'),
            {**self.registration_data(), 'role': User.Role.SELLER},
        )

        self.assertRedirects(response, reverse('home'))
        user = User.objects.get(username='newuser')
        self.assertEqual(user.role, User.Role.BUYER)
        self.assertNotContains(self.client.get(reverse('register')), 'name="role"')

    def test_admin_generated_seller_invitation_is_single_use(self):
        self.client.force_login(self.admin)
        create_response = self.client.post(reverse('create_seller_invitation'), follow=True)

        self.assertEqual(create_response.status_code, 200)
        invite_link = create_response.context['seller_invite_link']
        self.assertTrue(invite_link)
        invite_path = '/' + invite_link.split('/', 3)[3]
        registration = self.client.get(invite_path)
        self.assertEqual(registration.status_code, 200)
        self.assertContains(registration, 'Create Seller Account')

        created = self.client.post(invite_path, self.registration_data('invitedseller'))

        self.assertRedirects(created, reverse('home'))
        seller = User.objects.get(username='invitedseller')
        self.assertEqual(seller.role, User.Role.SELLER)
        self.assertEqual(
            SellerInvitation.objects.filter(used_at__isnull=False).count(),
            1,
        )
        reused = self.client.get(invite_path)
        self.assertRedirects(reused, reverse('register'))

    def test_expired_invitation_cannot_create_seller(self):
        import hashlib
        from django.utils import timezone

        token = 'expired-seller-token'
        SellerInvitation.objects.create(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get(reverse('seller_register', args=[token]))

        self.assertRedirects(response, reverse('register'))
        self.assertFalse(User.objects.filter(username='expiredseller').exists())

    def test_buyer_can_add_profile_photo_later(self):
        user = User.objects.create_user(
            username='photobuyer',
            password='safe-password',
        )
        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                self.client.force_login(user)
                response = self.client.post(
                    reverse('buyer_profile'),
                    {'profile_photo': make_test_image()},
                )

                self.assertRedirects(response, reverse('buyer_profile'))
                user.refresh_from_db()
                self.assertTrue(user.profile_photo.name.startswith('profiles/'))
                self.assertTrue(user.profile_photo.storage.exists(user.profile_photo.name))


class ProductReviewTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Reviews', slug='reviews')
        self.seller = User.objects.create_user(
            username='review-seller',
            password='safe-password',
            role=User.Role.SELLER,
        )
        self.buyer = User.objects.create_user(
            username='review-buyer',
            password='safe-password',
        )
        self.other_buyer = User.objects.create_user(
            username='other-buyer',
            password='safe-password',
        )
        self.product = Product.objects.create(
            category=self.category,
            seller=self.seller,
            title='Reviewed Wallet',
            slug='reviewed-wallet',
            price=Decimal('40.00'),
            stock=4,
            primary_image='products/review-wallet.jpg',
        )
        order = Order.objects.create(
            user=self.buyer,
            full_name='Review Buyer',
            email='review-buyer@example.com',
            address='1 Test Lane',
            city='Pune',
            postal_code='411001',
            total_amount=Decimal('40.00'),
            payment_status=Order.PaymentStatus.PAID,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            seller=self.seller,
            product_title=self.product.title,
            price=self.product.price,
            fulfillment_status=OrderItem.FulfillmentStatus.COMPLETED,
        )

    def test_signed_in_buyer_can_create_and_edit_one_review(self):
        self.client.force_login(self.buyer)
        review_url = reverse('save_product_review', args=[self.product.slug])

        created = self.client.post(review_url, {'rating': '5', 'body': 'Excellent quality.'})
        self.assertRedirects(created, reverse('product_detail', args=[self.product.slug]))
        review = ProductReview.objects.get(product=self.product, user=self.buyer)
        self.assertEqual(review.rating, 5)

        updated = self.client.post(review_url, {'rating': '4', 'body': 'Still excellent.'})
        self.assertRedirects(updated, reverse('product_detail', args=[self.product.slug]))
        review.refresh_from_db()
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.body, 'Still excellent.')
        self.assertEqual(
            ProductReview.objects.filter(product=self.product, user=self.buyer).count(),
            1,
        )

    def test_review_uploads_photos_and_video_and_product_page_displays_them(self):
        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                self.client.force_login(self.buyer)
                response = self.client.post(
                    reverse('save_product_review', args=[self.product.slug]),
                    {
                        'rating': '5',
                        'body': 'See my photos and video.',
                        'images': [make_test_image('review.jpg')],
                        'video': SimpleUploadedFile(
                            'review.mp4',
                            b'test review video',
                            content_type='video/mp4',
                        ),
                    },
                )
                self.assertRedirects(response, reverse('product_detail', args=[self.product.slug]))
                review = ProductReview.objects.get(product=self.product, user=self.buyer)
                self.assertEqual(review.images.count(), 1)
                self.assertTrue(review.video.name.endswith('.mp4'))

                detail = self.client.get(reverse('product_detail', args=[self.product.slug]))
                self.assertContains(detail, 'Customer reviews')
                self.assertContains(detail, 'mediaViewer')
                self.assertContains(detail, 'class="star-choice"')
                self.assertContains(detail, 'name="rating" value="5"')
                self.assertContains(detail, 'Share your experience, or leave this blank to rate only.')
                self.assertContains(detail, 'data-review-suggestion=')
                self.assertRegex(
                    detail.content.decode(),
                    r'product_reviews(?:\.[0-9a-f]+)?\.js',
                )
                self.assertContains(detail, 'review.mp4')
                self.assertContains(detail, 'review.jpg')

    def test_review_images_can_be_removed_and_owner_can_delete_review(self):
        review = ProductReview.objects.create(
            product=self.product,
            user=self.buyer,
            rating=3,
            body='Average',
        )
        photo = ProductReviewImage.objects.create(
            review=review,
            image='reviews/images/old.jpg',
        )
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse('save_product_review', args=[self.product.slug]),
            {'rating': '4', 'body': 'Updated', 'remove_images': [str(photo.pk)]},
        )

        self.assertRedirects(response, reverse('product_detail', args=[self.product.slug]))
        self.assertFalse(ProductReviewImage.objects.filter(pk=photo.pk).exists())
        review.refresh_from_db()
        self.assertEqual(review.rating, 4)

        response = self.client.post(reverse('delete_product_review', args=[review.pk]))
        self.assertRedirects(response, reverse('product_detail', args=[self.product.slug]))
        self.assertFalse(ProductReview.objects.filter(pk=review.pk).exists())

    def test_users_cannot_delete_other_reviews_and_sellers_cannot_review_own_products(self):
        review = ProductReview.objects.create(
            product=self.product,
            user=self.buyer,
            rating=5,
            body='Great',
        )
        self.client.force_login(self.other_buyer)
        response = self.client.post(reverse('delete_product_review', args=[review.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ProductReview.objects.filter(pk=review.pk).exists())

        self.client.force_login(self.seller)
        self.client.post(
            reverse('save_product_review', args=[self.product.slug]),
            {'rating': '5', 'body': 'Self review'},
        )
        self.assertEqual(ProductReview.objects.filter(product=self.product).count(), 1)

    def test_review_is_blocked_until_delivered_but_admin_can_review_for_testing(self):
        OrderItem.objects.filter(
            order__user=self.buyer,
            product=self.product,
        ).update(fulfillment_status=OrderItem.FulfillmentStatus.SHIPPED)
        self.client.force_login(self.other_buyer)
        response = self.client.post(
            reverse('save_product_review', args=[self.product.slug]),
            {'rating': '5', 'body': ''},
        )
        self.assertRedirects(response, reverse('product_detail', args=[self.product.slug]))
        self.assertFalse(
            ProductReview.objects.filter(product=self.product, user=self.other_buyer).exists()
        )
        self.assertContains(
            self.client.get(reverse('product_detail', args=[self.product.slug])),
            'Reviews are available after your order has been delivered.',
        )

        admin = User.objects.create_user(
            username='review-admin',
            password='safe-password',
            role=User.Role.ADMIN,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse('save_product_review', args=[self.product.slug]),
            {'rating': '4', 'body': ''},
        )
        self.assertRedirects(response, reverse('product_detail', args=[self.product.slug]))
        self.assertTrue(
            ProductReview.objects.filter(product=self.product, user=admin, body='').exists()
        )



class SellerInventoryAndOrderTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.seller = User.objects.create_user(
            username='inventoryseller',
            password='safe-password',
            role=User.Role.SELLER,
        )
        self.other_seller = User.objects.create_user(
            username='otherseller',
            password='safe-password',
            role=User.Role.SELLER,
        )
        self.product = Product.objects.create(
            category=self.category,
            seller=self.seller,
            title='Canvas Bag',
            slug='canvas-bag',
            price=Decimal('20.00'),
            stock=8,
            primary_image='products/bag.jpg',
        )
        self.other_product = Product.objects.create(
            category=self.category,
            seller=self.other_seller,
            title='Wool Scarf',
            slug='wool-scarf',
            price=Decimal('50.00'),
            stock=8,
            primary_image='products/scarf.jpg',
        )
        self.order = Order.objects.create(
            full_name='Buyer Name',
            email='buyer@example.com',
            address='10 Example Road',
            city='Pune',
            postal_code='411001',
            total_amount=Decimal('90.00'),
            payment_method=Order.PaymentMethod.CASH_ON_DELIVERY,
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            seller=self.seller,
            product_title=self.product.title,
            price=Decimal('20.00'),
            quantity=2,
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.other_product,
            seller=self.other_seller,
            product_title=self.other_product.title,
            price=Decimal('50.00'),
            quantity=1,
        )

    def test_dashboard_shows_seller_inventory_metrics_and_recent_orders(self):
        self.order.payment_status = Order.PaymentStatus.PAID
        self.order.save(update_fields=['payment_status'])
        self.client.force_login(self.seller)

        response = self.client.get(reverse('seller_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '₹40.00')
        self.assertContains(response, '2')
        self.assertContains(response, 'Stock')
        self.assertContains(response, 'View and process orders')
        self.assertContains(response, 'Order ' + str(self.order.public_id))
        self.assertContains(response, 'product-list-thumb')
        self.assertContains(response, 'products/bag.jpg')
        self.assertContains(response, 'Wool Scarf')

    def test_metrics_exclude_unpaid_orders(self):
        self.client.force_login(self.seller)

        response = self.client.get(reverse('seller_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '₹0.00')
        self.assertContains(response, 'Items sold')

    def test_seller_can_progress_only_their_items_through_delivery(self):
        self.client.force_login(self.seller)
        order_history = self.client.get(reverse('seller_orders'))
        self.assertContains(order_history, 'order-product-thumb')
        self.assertContains(order_history, 'products/bag.jpg')

        item = self.order.items.get(seller=self.seller)
        url = reverse(
            'update_seller_order_item_status',
            args=[self.order.public_id, item.pk],
        )

        for expected in (
            OrderItem.FulfillmentStatus.PROCESSING,
            OrderItem.FulfillmentStatus.SHIPPED,
            OrderItem.FulfillmentStatus.COMPLETED,
        ):
            response = self.client.post(url)
            self.assertRedirects(response, reverse('seller_orders'))
            item.refresh_from_db()
            self.assertEqual(item.fulfillment_status, expected)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(
            self.order.items.get(seller=self.other_seller).fulfillment_status,
            OrderItem.FulfillmentStatus.PENDING,
        )

    def test_seller_cannot_update_other_seller_item(self):
        self.client.force_login(self.seller)
        other_item = self.order.items.get(seller=self.other_seller)
        response = self.client.post(reverse(
            'update_seller_order_item_status',
            args=[self.order.public_id, other_item.pk],
        ))

        self.assertEqual(response.status_code, 404)
        other_item.refresh_from_db()
        self.assertEqual(other_item.fulfillment_status, OrderItem.FulfillmentStatus.PENDING)

    def test_seller_order_history_survives_product_deletion(self):
        self.product.delete()
        self.client.force_login(self.seller)

        response = self.client.get(reverse('seller_orders'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Canvas Bag')
        self.assertContains(response, 'order-product-thumb')
        self.assertContains(response, 'No image')
        self.assertNotContains(response, 'Wool Scarf')
        self.assertContains(response, reverse(
            'update_seller_order_item_status',
            args=[self.order.public_id, self.order.items.get(seller=self.seller).pk],
        ))

    def test_unpaid_online_order_cannot_be_processed(self):
        self.order.payment_method = Order.PaymentMethod.RAZORPAY
        self.order.save(update_fields=['payment_method'])
        self.client.force_login(self.seller)
        item = self.order.items.get(seller=self.seller)

        response = self.client.post(reverse(
            'update_seller_order_item_status',
            args=[self.order.public_id, item.pk],
        ))

        self.assertRedirects(response, reverse('seller_orders'))
        item.refresh_from_db()
        self.assertEqual(item.fulfillment_status, OrderItem.FulfillmentStatus.PENDING)
