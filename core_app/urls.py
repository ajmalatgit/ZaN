from django.urls import path
from . import views

urlpatterns = [
    # Storefront & Auth
    path('', views.home, name='home'),
    path('shop/', views.catalog, name='catalog'),
    path('register/', views.register_view, name='register'),
    path('register/seller/<str:invitation_token>/', views.register_view, name='seller_register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboards
    path('seller/dashboard/', views.seller_dashboard, name='seller_dashboard'),
    path('executive/admin-panel/', views.admin_dashboard, name='admin_dashboard'),
    path('executive/admin-panel/seller-invitations/create/', views.create_seller_invitation, name='create_seller_invitation'),
    path('executive/admin-panel/sellers/<int:seller_id>/active/', views.set_seller_active, name='set_seller_active'),
    path('seller/products/add/', views.add_product, name='add_product'),
    path('seller/orders/', views.seller_orders, name='seller_orders'),
    path('seller/orders/<uuid:public_id>/items/<int:item_id>/status/', views.update_seller_order_item_status, name='update_seller_order_item_status'),
    path('products/<int:product_id>/edit/', views.edit_product, name='edit_product'),
    path('products/<int:product_id>/delete/', views.delete_product, name='delete_product'),

    # Product Detail
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('product/<slug:slug>/reviews/', views.save_product_review, name='save_product_review'),
    path('product/reviews/<int:review_id>/delete/', views.delete_product_review, name='delete_product_review'),

    # Session Shopping Cart Endpoints
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/remove/<int:product_id>/', views.cart_remove, name='cart_remove'),
    path('checkout/', views.checkout, name='checkout'),
    path('profile/', views.buyer_profile, name='buyer_profile'),
    path(
        'orders/<uuid:public_id>/invoice/',
        views.order_invoice,
        name='order_invoice',
    ),
    path('orders/<uuid:public_id>/', views.order_confirmation, name='order_confirmation'),
    path('payment/verify/', views.payment_verify, name='payment_verify'),
    path('payment/webhook/', views.payment_webhook, name='payment_webhook'),
]