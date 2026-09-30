// static/js/cart.js
function toggleCartDrawer(open) {
  const drawer = document.getElementById('cart-drawer');
  const overlay = document.getElementById('cart-drawer-overlay');

  if (open) {
    drawer.classList.remove('translate-x-full');
    overlay.classList.remove('opacity-0', 'pointer-events-none');
  } else {
    drawer.classList.add('translate-x-full');
    overlay.classList.add('opacity-0', 'pointer-events-none');
  }
}

document.getElementById('close-cart-btn')?.addEventListener('click', () => toggleCartDrawer(false));
document.getElementById('cart-drawer-overlay')?.addEventListener('click', () => toggleCartDrawer(false));

function addToCart(productId, quantity = 1) {
  const formData = new FormData();
  formData.append('quantity', quantity);
  formData.append('csrfmiddlewaretoken', getCookie('csrftoken'));

  fetch(`/cart/add/${productId}/`, {
    method: 'POST',
    body: formData,
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      document.getElementById('cart-drawer-count').innerText = data.cart_count;
      document.getElementById('cart-drawer-subtotal').innerText = data.total_price;
      toggleCartDrawer(true);
      // Optional: re-fetch or dynamically update cart drawer items via AJAX
      window.location.reload(); // Simplest way to reflect updated rendered template state
    }
  });
}

function removeFromCart(productId) {
  const formData = new FormData();
  formData.append('csrfmiddlewaretoken', getCookie('csrftoken'));

  fetch(`/cart/remove/${productId}/`, {
    method: 'POST',
    body: formData,
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      document.getElementById(`cart-item-${productId}`)?.remove();
      document.getElementById('cart-drawer-count').innerText = data.cart_count;
      document.getElementById('cart-drawer-subtotal').innerText = data.total_price;
    }
  });
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}