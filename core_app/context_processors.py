# core_app/context_processors.py
from core_app.cart import Cart

def cart_context(request):
    return {
        'cart': Cart(request)
    }