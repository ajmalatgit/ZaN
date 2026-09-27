document.addEventListener('DOMContentLoaded', () => {
    let cartCount = 0;
    const cartBadge = document.querySelector('.cart-badge');
    const addButtons = document.querySelectorAll('.btn-cart');

    addButtons.forEach(button => {
        button.addEventListener('click', () => {
            cartCount++;
            if (cartBadge) {
                cartBadge.textContent = cartCount;
            }
            
            // Subtle button animation feedback
            button.textContent = 'Added!';
            button.style.backgroundColor = 'var(--accent-gold)';
            button.style.color = 'var(--bg-dark)';
            
            setTimeout(() => {
                button.textContent = 'Add to Cart';
                button.style.backgroundColor = 'transparent';
                button.style.color = 'var(--accent-gold)';
            }, 1000);
        });
    });
});