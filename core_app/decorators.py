from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

def seller_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_active:
            messages.error(request, "This account is inactive. Contact an administrator for help.")
            return redirect('login')
        if request.user.role in [request.user.Role.SELLER, request.user.Role.ADMIN]:
            return view_func(request, *args, **kwargs)
        messages.error(request, "Access restricted to Seller accounts.")
        return redirect('home')
    return _wrapped_view

def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role == request.user.Role.ADMIN or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        messages.error(request, "Access restricted to Administrators.")
        return redirect('home')
    return _wrapped_view