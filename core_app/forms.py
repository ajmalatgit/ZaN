from django import forms
from django.utils.text import slugify
from .models import Order, Product, ProductImage


class CheckoutForm(forms.ModelForm):
    payment_method = forms.ChoiceField(
        choices=Order.PaymentMethod.choices,
        widget=forms.RadioSelect,
        initial=Order.PaymentMethod.RAZORPAY,
        required=False,
    )

    class Meta:
        model = Order
        fields = [
            'full_name',
            'email',
            'address',
            'city',
            'postal_code',
            'payment_method',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'name'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
            'address': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'autocomplete': 'street-address'}),
            'city': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'address-level2'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'postal-code'}),
        }

    def clean_payment_method(self):
        return self.cleaned_data.get('payment_method') or Order.PaymentMethod.RAZORPAY

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['category', 'title', 'description', 'price', 'stock', 'primary_image', 'is_active']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-input'}),
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 4}),
            'price': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-input', 'min': 0, 'step': 1}),
            'primary_image': forms.FileInput(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        title_changed = (
            instance.pk
            and Product.objects.filter(pk=instance.pk)
            .exclude(title=instance.title)
            .exists()
        )
        if not instance.slug or title_changed:
            base_slug = slugify(instance.title)
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            instance.slug = slug

        if commit:
            instance.save()
        return instance