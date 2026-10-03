from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from .models import (
    Order,
    Product,
    ProductReview,
    User,
    validate_image_size,
)


class RegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))

    class Meta:
        model = User
        fields = ['username', 'email', 'phone_number', 'company_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'username'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'tel'}),
            'company_name': forms.TextInput(attrs={'class': 'form-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('password') != cleaned_data.get('confirm_password'):
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['profile_photo']
        widgets = {
            'profile_photo': forms.ClearableFileInput(attrs={
                'class': 'form-input',
                'accept': 'image/*',
            }),
        }


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
        fields = [
            'category', 'title', 'description', 'price', 'stock',
            'primary_image', 'video', 'is_active',
        ]
        widgets = {
            'category': forms.Select(attrs={'class': 'form-input'}),
            'title': forms.TextInput(attrs={'class': 'form-input'}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 4}),
            'price': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'form-input', 'min': 0, 'step': 1}),
            'primary_image': forms.FileInput(attrs={'class': 'form-input'}),
            'video': forms.ClearableFileInput(attrs={
                'class': 'form-input',
                'accept': 'video/mp4,video/webm,video/quicktime',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        old_video = None
        if instance.pk:
            old_video = Product.objects.only('video').get(pk=instance.pk).video
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
            if (
                old_video
                and old_video.name
                and old_video.name != instance.video.name
            ):
                old_video.storage.delete(old_video.name)
        return instance


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super().clean(file, initial) for file in files]


class ProductReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[(value, f'{value} star{"s" if value != 1 else ""}') for value in range(1, 6)],
        coerce=int,
        widget=forms.RadioSelect,
    )
    images = MultipleImageField(
        required=False,
        validators=[validate_image_size],
        widget=MultipleImageInput(attrs={
            'class': 'form-input',
            'accept': 'image/*',
            'multiple': True,
        }),
    )
    clear_video = forms.BooleanField(required=False)

    class Meta:
        model = ProductReview
        fields = ['rating', 'body', 'video']
        widgets = {
            'body': forms.Textarea(attrs={'class': 'form-input', 'rows': 4, 'maxlength': 3000}),
            'video': forms.ClearableFileInput(attrs={
                'class': 'form-input',
                'accept': 'video/mp4,video/webm,video/quicktime',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['body'].required = False
        self.fields['video'].required = False

    def clean_images(self):
        images = self.cleaned_data['images']
        if len(images) > 5:
            raise ValidationError('Upload no more than 5 review photos at a time.')
        return images