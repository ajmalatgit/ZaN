document.addEventListener('DOMContentLoaded', () => {
    // Helper: Get CSRF token from DOM input or cookies
    function getCSRFToken() {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfInput && csrfInput.value) return csrfInput.value;

        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    // Helper: Execute AJAX POST request to Django cart_add endpoint
    function handleAddToCart(productId, buttonElement, quantity = 1) {
        if (!productId) {
            console.error('Cart Error: Missing Product ID');
            return;
        }

        const originalText = buttonElement.textContent;
        const csrfToken = getCSRFToken();

        // UI State: Loading
        buttonElement.disabled = true;
        buttonElement.textContent = 'Adding...';

        fetch(`/cart/add/${productId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: new URLSearchParams({
                'quantity': quantity
            })
        })
        .then(response => {
            return response.json()
                .catch(() => ({}))
                .then(data => {
                    if (!response.ok || !data.success) {
                        throw new Error(data.error || `Unable to update your cart (HTTP ${response.status}).`);
                    }
                    return data;
                });
        })
        .then(data => {
            if (typeof syncCartUI === 'function') syncCartUI(data);

            buttonElement.textContent = 'Added!';
            buttonElement.classList.add('zan-btn-success');
            if (typeof window.showToast === 'function') {
                window.showToast(data.message || 'Item added to your cart.', 'success');
            }

            if (typeof toggleCartDrawer === 'function') toggleCartDrawer(true);

            setTimeout(() => {
                buttonElement.textContent = originalText;
                buttonElement.classList.remove('zan-btn-success');
                buttonElement.disabled = false;
            }, 1200);
        })
        .catch(error => {
            console.error('Cart Submission Error:', error);
            if (typeof window.showToast === 'function') {
                window.showToast(error.message || 'Unable to add this item to your cart.', 'error');
            }
            buttonElement.textContent = 'Error!';
            setTimeout(() => {
                buttonElement.textContent = originalText;
                buttonElement.disabled = false;
            }, 1500);
        });
    }

    // Event Delegation: Global Click Handler for Forms and Standalone Buttons
    document.addEventListener('click', (e) => {
        const cartBtn = e.target.closest('.btn-cart, .zan-card-action');
        if (!cartBtn) return;

        // Check if button is inside a form container
        const parentForm = cartBtn.closest('.add-to-cart-form');

        if (parentForm) {
            e.preventDefault();

            // Extract ID safely from dataset, action attribute, or form dataset
            let productId = cartBtn.dataset.productId || parentForm.dataset.productId;
            if (!productId && parentForm.getAttribute('action')) {
                const actionUrl = parentForm.getAttribute('action');
                const parts = actionUrl.split('/').filter(Boolean);
                productId = parts.pop();
            }

            const qtyInput = parentForm.querySelector('input[name="quantity"]');
            const quantity = qtyInput ? qtyInput.value : 1;

            handleAddToCart(productId, cartBtn, quantity);
        } else if (cartBtn.dataset.productId) {
            e.preventDefault();
            handleAddToCart(cartBtn.dataset.productId, cartBtn, 1);
        }
    });

    // Form Submit Fallback: Intercept standard submit events
    document.querySelectorAll('.add-to-cart-form').forEach(form => {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const submitBtn = form.querySelector('button[type="submit"]') || form.querySelector('.btn-cart');
            let productId = form.dataset.productId;

            if (!productId && form.getAttribute('action')) {
                const actionUrl = form.getAttribute('action');
                const parts = actionUrl.split('/').filter(Boolean);
                productId = parts.pop();
            }

            const qtyInput = form.querySelector('input[name="quantity"]');
            const quantity = qtyInput ? qtyInput.value : 1;

            if (submitBtn) {
                handleAddToCart(productId, submitBtn, quantity);
            }
        });
    });
});