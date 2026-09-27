from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('seller/dashboard/', views.seller_dashboard, name='seller_dashboard'),
    path('executive/admin-panel/', views.admin_dashboard, name='admin_dashboard'),
    path('seller/products/add/', views.add_product, name='add_product'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
]