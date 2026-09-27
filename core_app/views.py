from django.shortcuts import render
from .models import Product

def home(request):
    products = Product.objects.filter(is_active=True).select_related('category')
    return render(request, 'core_app/home.html', {'products': products})


from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import User, Product
from .decorators import seller_required, admin_required
from django import forms

# Registration Form
class RegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'email', 'phone_number', 'role', 'company_name']

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('password') != cleaned_data.get('confirm_password'):
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            login(request, user)
            messages.success(request, f"Welcome to ZAN, {user.username}!")
            return redirect('home')
    else:
        form = RegisterForm()
    return render(request, 'core_app/register.html', {'form': form})

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
    # Sellers only see their associated products or brand metrics
    products = Product.objects.all() 
    return render(request, 'core_app/seller_dashboard.html', {'products': products})

# Gated Executive Admin Dashboard
@admin_required
def admin_dashboard(request):
    stats = {
        'total_users': User.objects.count(),
        'total_sellers': User.objects.filter(role=User.Role.SELLER).count(),
        'total_products': Product.objects.count(),
    }
    return render(request, 'core_app/admin_dashboard.html', {'stats': stats})

from django.shortcuts import render, redirect
from django.contrib import messages
from .decorators import seller_required
from .forms import ProductForm

from django.shortcuts import render, redirect
from django.contrib import messages
from .decorators import seller_required
from .forms import ProductForm
from .models import ProductImage

@seller_required
def add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        gallery_files = request.FILES.getlist('gallery_images')  # Multiple extra gallery files
        
        if form.is_valid():
            product = form.save()
            
            # Save extra gallery images
            for file in gallery_files:
                ProductImage.objects.create(
                    product=product,
                    image=file,
                    alt_text=product.title
                )
                
            messages.success(request, f"Product '{product.title}' listed successfully!")
            return redirect('seller_dashboard')
    else:
        form = ProductForm()
    
    return render(request, 'core_app/add_product.html', {'form': form})

from django.shortcuts import render, get_object_or_404
from .models import Product

def product_detail(request, slug):
    # Retrieve product by slug or raise 404
    product = get_object_or_404(Product, slug=slug, is_active=True)
    
    # Fetch related products from the same category (excluding current item)
    related_products = Product.objects.filter(
        category=product.category, 
        is_active=True
    ).exclude(id=product.id)[:4]

    context = {
        'product': product,
        'related_products': related_products,
    }
    return render(request, 'core_app/product_detail.html', context)