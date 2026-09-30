from decimal import Decimal, InvalidOperation

from core_app.models import Product


class Cart:
    def __init__(self, request):
        self.session = request.session
        stored_cart = self.session.get('cart', {})
        self.cart = self._normalize(stored_cart)

        if self.cart != stored_cart:
            self.session['cart'] = self.cart
            self.save()

    @staticmethod
    def _normalize(stored_cart):
        if not isinstance(stored_cart, dict):
            return {}

        cart = {}
        for product_id, item in stored_cart.items():
            if not str(product_id).isdecimal() or not isinstance(item, dict):
                continue

            try:
                quantity = int(item['quantity'])
                price = Decimal(str(item['price']))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue

            if quantity < 1 or not price.is_finite() or price < 0:
                continue

            cart[str(product_id)] = {
                'quantity': quantity,
                'price': str(price),
            }

        return cart

    def add(self, product, quantity=1, override_quantity=False):
        product_id = str(product.pk)
        current_item = self.cart.get(product_id)

        if current_item is None:
            self.cart[product_id] = {
                'quantity': 0,
                'price': str(product.price),
            }

        if override_quantity:
            self.cart[product_id]['quantity'] = int(quantity)
        else:
            self.cart[product_id]['quantity'] += int(quantity)

        self.save()

    def save(self):
        self.session['cart'] = self.cart
        self.session.modified = True

    def remove(self, product_id):
        product_id = str(getattr(product_id, 'pk', product_id))
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def __iter__(self):
        products = Product.objects.filter(id__in=self.cart.keys())
        found_ids = set()

        for product in products:
            product_id = str(product.pk)
            found_ids.add(product_id)
            item = self.cart[product_id].copy()
            item['product'] = product
            item['price'] = Decimal(item['price'])
            item['total_price'] = item['price'] * item['quantity']
            yield item

        missing_ids = self.cart.keys() - found_ids
        if missing_ids:
            for product_id in missing_ids:
                del self.cart[product_id]
            self.save()

    def __len__(self):
        return sum(item['quantity'] for item in self.cart.values())

    def get_total_price(self):
        return sum(
            Decimal(item['price']) * item['quantity']
            for item in self.cart.values()
        )

    def clear(self):
        self.cart.clear()
        self.save()
