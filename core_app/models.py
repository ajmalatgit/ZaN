import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def validate_image_size(upload):
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError('Image files must be 10 MB or smaller.')


def validate_video_size(upload):
    if upload.size > 50 * 1024 * 1024:
        raise ValidationError('Video files must be 50 MB or smaller.')


video_validators = [
    FileExtensionValidator(allowed_extensions=['mp4', 'webm', 'mov']),
    validate_video_size,
]


def seller_invitation_expiration():
    return timezone.now() + timedelta(days=7)

class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        limit_choices_to={'role': 'SELLER'},
    )
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    primary_image = models.ImageField(upload_to='products/%Y/%m/')
    video = models.FileField(
        upload_to='products/videos/%Y/%m/',
        blank=True,
        validators=video_validators,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='gallery_images')
    image = models.ImageField(upload_to='products/gallery/%Y/%m/')
    alt_text = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Gallery Image for {self.product.title}"


class ProductReview(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_reviews',
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    body = models.TextField(max_length=3000, blank=True)
    video = models.FileField(
        upload_to='reviews/videos/%Y/%m/',
        blank=True,
        validators=video_validators,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name='product_review_rating_between_one_and_five',
            ),
            models.UniqueConstraint(
                fields=['product', 'user'],
                name='one_review_per_user_product',
            ),
        ]

    def __str__(self):
        return f'{self.rating}/5 review by {self.user} for {self.product}'


class ProductReviewImage(models.Model):
    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name='images',
    )
    image = models.ImageField(
        upload_to='reviews/images/%Y/%m/',
        validators=[validate_image_size],
    )


class SellerInvitation(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='seller_invitations',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=seller_invitation_expiration)
    used_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        SHIPPED = 'SHIPPED', 'Shipped'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    class PaymentMethod(models.TextChoices):
        RAZORPAY = 'RAZORPAY', 'Pay online with Razorpay'
        CASH_ON_DELIVERY = 'COD', 'Pay on delivery'

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    full_name = models.CharField(max_length=100)
    email = models.EmailField()
    address = models.TextField()
    city = models.CharField(max_length=50)
    postal_code = models.CharField(max_length=20)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.RAZORPAY,
    )
    razorpay_order_id = models.CharField(
        max_length=40,
        unique=True,
        null=True,
        blank=True,
    )
    payment_reference = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name='order_total_non_negative',
            ),
        ]

    @property
    def is_paid(self):
        return self.payment_status == self.PaymentStatus.PAID

    def __str__(self):
        return f'Order {self.public_id}'


class OrderItem(models.Model):
    class FulfillmentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Received'
        PROCESSING = 'PROCESSING', 'Processing'
        SHIPPED = 'SHIPPED', 'Out for delivery'
        COMPLETED = 'COMPLETED', 'Delivered'
        CANCELLED = 'CANCELLED', 'Cancelled'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sold_order_items',
    )
    product_title = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    fulfillment_status = models.CharField(
        max_length=12,
        choices=FulfillmentStatus.choices,
        default=FulfillmentStatus.PENDING,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name='order_item_quantity_at_least_one',
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name='order_item_price_non_negative',
            ),
        ]

    @property
    def line_total(self):
        return self.price * self.quantity

    def __str__(self):
        return f'{self.quantity} × {self.product_title}'


from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        SELLER = 'SELLER', 'Seller'
        BUYER = 'BUYER', 'Buyer'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.BUYER)
    phone_number = models.CharField(max_length=15, blank=True)
    company_name = models.CharField(max_length=100, blank=True)
    profile_photo = models.ImageField(
        upload_to='profiles/%Y/%m/',
        blank=True,
        validators=[validate_image_size],
    )

    def save(self, *args, **kwargs):
        # Automatically classify superusers as ADMIN role
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)