# 💳 SlideGen Pro - Payment Integration Guide

## 🎯 Overview

Your SlideGen Pro now includes:
- ✅ **Grammar proofreading** for all speaker notes
- ✅ **Stripe payment integration** for subscriptions
- ✅ **$6.99/month** subscription with **10 presentations per month**
- ✅ **1 free presentation** for all new users

---

## 🚀 Quick Start

### 1. Install Required Packages

```bash
pip install stripe --break-system-packages
```

### 2. Set Up Stripe Account

1. Go to https://stripe.com and create an account
2. Navigate to **Developers → API Keys**
3. Copy your **Publishable Key** and **Secret Key**
4. Create a **Product** in Stripe Dashboard:
   - Product Name: "SlideGen Pro Monthly"
   - Price: $6.99/month
   - Copy the **Price ID** (looks like `price_xxxxx`)

### 3. Set Up Webhook

1. In Stripe Dashboard, go to **Developers → Webhooks**
2. Click **Add endpoint**
3. Endpoint URL: `https://your-domain.com/api/payment/webhook`
4. Select events to listen for:
   - `checkout.session.completed`
   - `invoice.payment_succeeded`
   - `customer.subscription.deleted`
5. Copy the **Webhook Secret** (looks like `whsec_xxxxx`)

### 4. Configure Environment Variables

Create a `.env` file with:

```bash
# Anthropic API
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Flask Secret
SECRET_KEY=your_random_secret_key_here

# Stripe Configuration
STRIPE_SECRET_KEY=sk_test_xxxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxx
STRIPE_PRICE_ID=price_xxxxxxxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
```

### 5. Run the Server

```bash
export ANTHROPIC_API_KEY='your-key'
python3 server.py &
python3 -m http.server 3000 &
```

---

## 🆕 What's New

### 1. Grammar Proofreading ✍️

All speaker notes are automatically proofread using Claude AI after generation:

**Process:**
1. Speaker notes are generated based on slide content
2. Notes are sent to `proofread_speaker_notes()` function
3. Claude fixes grammar, spelling, and awkward phrasing
4. Corrected notes are returned to the user

**Example:**

**Before:**
```
This slide focus on Cloud Computing Benefits. Here what you need know:
Reduces infrastructure cost by 40%. Enable global team collaboration.
```

**After:**
```
This slide focuses on Cloud Computing Benefits. Here's what you need to know:
Reduces infrastructure costs by 40%. Enables global team collaboration.
```

### 2. Stripe Payment Integration 💳

**Free Tier:**
- 1 free presentation upon signup
- No credit card required

**Premium Tier ($6.99/month):**
- 10 presentations per month
- Monthly limit resets automatically
- Cancel anytime

**Payment Flow:**
```
User clicks "Upgrade" 
  → Stripe Checkout opens
  → User enters payment details
  → Payment processed
  → Webhook updates database
  → User gets premium access
  → 10 presentations per month
```

### 3. Database Updates 💾

New fields in `users` table:
- `stripe_customer_id` - Stripe customer reference
- `stripe_subscription_id` - Active subscription reference
- Updated `generations_limit` to 10 for premium users

New table: `payment_history`
- Tracks all payments and subscriptions
- Records payment status and amounts

---

## 📋 API Endpoints

### Payment Endpoints

#### Get Payment Configuration
```bash
GET /api/payment/config
```

Returns:
```json
{
  "publishableKey": "pk_test_xxxxx",
  "priceId": "price_xxxxx"
}
```

#### Create Checkout Session
```bash
POST /api/payment/create-checkout-session
Headers: Cookie (authentication)
```

Returns:
```json
{
  "sessionId": "cs_test_xxxxx"
}
```

#### Cancel Subscription
```bash
POST /api/payment/cancel-subscription
Headers: Cookie (authentication)
```

Returns:
```json
{
  "success": true,
  "message": "Subscription cancelled"
}
```

#### Webhook Endpoint
```bash
POST /api/payment/webhook
Headers: Stripe-Signature
```

Handles:
- `checkout.session.completed` - Activates premium
- `invoice.payment_succeeded` - Records payment
- `customer.subscription.deleted` - Downgrades to free

---

## 🔧 Frontend Integration

### Add Stripe.js to HTML

```html
<script src="https://js.stripe.com/v3/"></script>
```

### Payment Button Example

```javascript
async function handleUpgrade() {
    // Get Stripe config
    const configRes = await fetch('/api/payment/config');
    const config = await configRes.json();
    
    // Initialize Stripe
    const stripe = Stripe(config.publishableKey);
    
    // Create checkout session
    const sessionRes = await fetch('/api/payment/create-checkout-session', {
        method: 'POST',
        credentials: 'include'
    });
    const session = await sessionRes.json();
    
    // Redirect to Stripe Checkout
    await stripe.redirectToCheckout({ sessionId: session.sessionId });
}
```

### Check Subscription Status

```javascript
async function checkStatus() {
    const res = await fetch('/api/auth/status', {
        credentials: 'include'
    });
    const data = await res.json();
    
    if (data.authenticated) {
        console.log('Status:', data.user.subscription_status);
        console.log('Used:', data.user.generations_used);
        console.log('Limit:', data.user.generations_limit);
    }
}
```

---

## 🧪 Testing

### Test Mode (Stripe)

Use Stripe test cards:
- **Success:** `4242 4242 4242 4242`
- **Requires authentication:** `4000 0025 0000 3155`
- **Declined:** `4000 0000 0000 9995`
- Expiry: Any future date (e.g., 12/34)
- CVC: Any 3 digits (e.g., 123)

### Test Workflow

1. **Create Account**
   ```bash
   POST /api/auth/signup
   {
     "email": "test@example.com",
     "password": "password123"
   }
   ```

2. **Use Free Presentation**
   - Generate 1 presentation
   - Limit reached: Cannot generate more

3. **Upgrade to Premium**
   - Click upgrade button
   - Use test card `4242 4242 4242 4242`
   - Complete checkout
   - Now have 10 presentations

4. **Generate Presentations**
   - Can generate up to 10 per month
   - Limit resets on the 1st of each month

5. **Cancel Subscription**
   ```bash
   POST /api/payment/cancel-subscription
   ```

---

## 🔒 Security

### Environment Variables

**Never commit these to Git:**
- STRIPE_SECRET_KEY
- STRIPE_WEBHOOK_SECRET
- ANTHROPIC_API_KEY
- SECRET_KEY

Add to `.gitignore`:
```
.env
*.db
__pycache__/
```

### Webhook Signature Verification

The webhook endpoint verifies Stripe signatures:
```python
event = stripe.Webhook.construct_event(
    payload, sig_header, webhook_secret
)
```

This prevents unauthorized webhook calls.

### Session Management

- Session cookies are httpOnly
- CORS is configured for specific origins
- Login required decorator on protected endpoints

---

## 📊 Database Schema

### Users Table
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    subscription_status TEXT DEFAULT 'free',
    generations_used INTEGER DEFAULT 0,
    generations_limit INTEGER DEFAULT 1,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    last_reset TIMESTAMP,
    created_at TIMESTAMP
);
```

### Payment History Table
```sql
CREATE TABLE payment_history (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    stripe_payment_id TEXT,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'usd',
    status TEXT NOT NULL,
    created_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);
```

---

## 🐛 Troubleshooting

### Issue: Webhook not working

**Solution:**
1. Check webhook URL is publicly accessible
2. Verify webhook secret is correct
3. Check webhook events are selected in Stripe Dashboard
4. Test webhook with Stripe CLI:
   ```bash
   stripe listen --forward-to localhost:5000/api/payment/webhook
   ```

### Issue: Payment not activating premium

**Solution:**
1. Check webhook endpoint logs
2. Verify `checkout.session.completed` event is received
3. Check database was updated:
   ```bash
   sqlite3 slidegen.db "SELECT * FROM users WHERE id=1;"
   ```

### Issue: Monthly limit not resetting

**Solution:**
The limit resets automatically when:
- User is premium
- Current month > last_reset month

Check `last_reset` field in database.

### Issue: Grammar proofreading failing

**Solution:**
1. Check ANTHROPIC_API_KEY is set
2. Verify API has sufficient credits
3. Check logs for error messages
4. Notes will fallback to unproofread if proofreading fails

---

## 📈 Monitoring

### Check User Stats

```sql
-- Total users
SELECT COUNT(*) FROM users;

-- Premium vs Free
SELECT subscription_status, COUNT(*) 
FROM users 
GROUP BY subscription_status;

-- Total presentations generated
SELECT COUNT(*) FROM presentations;

-- Revenue (total payments)
SELECT SUM(amount) FROM payment_history WHERE status='succeeded';
```

### Check Generation Usage

```sql
-- Users near limit
SELECT email, generations_used, generations_limit 
FROM users 
WHERE generations_used >= generations_limit - 1;

-- Top users
SELECT u.email, COUNT(p.id) as presentations
FROM users u
LEFT JOIN presentations p ON u.id = p.user_id
GROUP BY u.id
ORDER BY presentations DESC
LIMIT 10;
```

---

## 🔄 Migration from Old System

If you have existing users:

```sql
-- Set all existing users to free with 1 presentation
UPDATE users 
SET subscription_status = 'free',
    generations_limit = 1,
    generations_used = 0,
    last_reset = CURRENT_TIMESTAMP
WHERE subscription_status IS NULL;
```

---

## 💡 Tips

1. **Test thoroughly in Stripe test mode** before going live
2. **Monitor webhook logs** for debugging payment issues
3. **Use Stripe Dashboard** to view customer subscriptions
4. **Set up billing emails** in Stripe for failed payments
5. **Consider annual pricing** ($69.99/year) for better retention

---

## 🚀 Going Live

### Pre-Launch Checklist

- [ ] Switch to Stripe live keys
- [ ] Update webhook URL to production domain
- [ ] Test full payment flow with real card
- [ ] Set up error monitoring (Sentry, etc.)
- [ ] Configure email notifications (SendGrid, etc.)
- [ ] Add terms of service and privacy policy
- [ ] Set up customer support email
- [ ] Test subscription cancellation flow
- [ ] Verify monthly reset logic works
- [ ] Add analytics (Google Analytics, etc.)

### Stripe Live Mode

1. Switch to **Live** mode in Stripe Dashboard
2. Get new API keys (starts with `sk_live_` and `pk_live_`)
3. Update `.env` file with live keys
4. Test with real payment method
5. Monitor first few transactions closely

---

## 📞 Support

### Stripe Support
- Dashboard: https://dashboard.stripe.com
- Docs: https://stripe.com/docs
- Support: support@stripe.com

### Anthropic Support
- Docs: https://docs.anthropic.com
- Console: https://console.anthropic.com

---

## ✅ Summary

Your SlideGen Pro now features:

1. **✍️ Grammar Proofreading**
   - All speaker notes are automatically corrected
   - Uses Claude AI for natural, professional output
   - Fallback to original if proofreading fails

2. **💳 Stripe Payments**
   - $6.99/month subscription
   - 10 presentations per month
   - Automatic monthly reset
   - Secure webhook integration

3. **🎁 Free Tier**
   - 1 free presentation for all users
   - No credit card required
   - Easy upgrade path

4. **🔒 Security**
   - Webhook signature verification
   - Session-based authentication
   - Environment variable protection

**You're ready to launch!** 🚀
