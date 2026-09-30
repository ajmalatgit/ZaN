from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Order, OrderItem, User, Category, Product, ProductImage

# Configure Custom User display in Admin
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'role', 'company_name', 'is_staff', 'is_active']
    list_filter = ['role', 'is_staff', 'is_active']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('ZAN Role & Details', {'fields': ('role', 'phone_number', 'company_name')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('ZAN Role & Details', {'fields': ('role', 'phone_number', 'company_name')}),
    )


# Inline gallery images inside the Product edit page
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'price', 'is_active', 'created_at']
    list_filter = ['is_active', 'category']
    search_fields = ['title', 'description']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ProductImageInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'product_title', 'price', 'quantity']
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'public_id',
        'full_name',
        'total_amount',
        'status',
        'payment_status',
        'razorpay_order_id',
        'created_at',
    ]
    list_filter = ['status', 'payment_status', 'created_at']
    search_fields = ['public_id', 'full_name', 'email', 'razorpay_order_id', 'payment_reference']
    readonly_fields = ['public_id', 'razorpay_order_id', 'created_at', 'total_amount']
    inlines = [OrderItemInline]