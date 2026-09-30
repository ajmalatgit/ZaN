# Razorpay test-mode setup

The checkout uses the Razorpay Checkout.js modal with INR amounts. Available
payment methods (including UPI, cards, and netbanking) depend on the methods
enabled for the Razorpay account.

1. Keep credentials out of source control. Configure these environment variables
   (or add them to the ignored local `.env` file):

   ```text
   RAZORPAY_KEY_ID=your_test_key_id
   RAZORPAY_KEY_SECRET=your_test_key_secret
   RAZORPAY_WEBHOOK_SECRET=your_webhook_signing_secret
   ```

   The webhook signing secret is generated when configuring the webhook in the
   Razorpay Dashboard. It is separate from the API key secret.

2. Apply database migrations:

   ```powershell
   python manage.py migrate
   ```

3. In the Razorpay Dashboard test-mode settings, configure a webhook pointing to
   `https://your-public-host/payment/webhook/`, use the same value as
   `RAZORPAY_WEBHOOK_SECRET`, and enable `payment.captured`, `payment.failed`,
   and `order.paid` events. Local development servers need a secure public
   tunnel for Razorpay to reach the webhook.

4. Start the server and place a test order. Checkout creates the Razorpay order
   on the backend, then opens the payment modal. The browser callback is
   signature-verified and the payment is fetched from Razorpay; the signed
   webhook independently confirms captured payments. Orders are marked paid
   only after Razorpay reports a captured/paid transaction.

Use Razorpay test-mode credentials and test payment details until the integration
has been verified. Rotate any API credentials that were previously stored in
source files.
