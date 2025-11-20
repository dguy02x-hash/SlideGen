# 🚀 SlideGen Pro - Complete Setup Guide

## 📋 Table of Contents
1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running Locally](#running-locally)
5. [Testing](#testing)
6. [Deployment](#deployment)
7. [Troubleshooting](#troubleshooting)

---

## ✅ Prerequisites

### Required Accounts
- [ ] Anthropic API account (https://console.anthropic.com)
- [ ] Stripe account (https://stripe.com)

### Required Software
- [ ] Python 3.8 or higher
- [ ] pip (Python package manager)
- [ ] Git (optional, for version control)

---

## 📦 Installation

### 1. Install Python Dependencies

```bash
pip install flask flask-cors requests python-dotenv stripe --break-system-packages
```

Or using a virtual environment (recommended for production):

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install flask flask-cors requests python-dotenv stripe
```

### 2. Verify Installation

```bash
python3 -c "import flask, stripe; print('✅ All packages installed')"
```

---

## ⚙️ Configuration

### 1. Get Anthropic API Key

1. Go to https://console.anthropic.com
2. Sign up or log in
3. Navigate to **API Keys**
4. Click **Create Key**
5. Copy the key (starts with `sk-ant-api03-`)

### 2. Set Up Stripe (Test Mode)

#### Get API Keys
1. Go to https://dashboard.stripe.com
2. Sign up or log in
3. Make sure you're in **Test Mode** (toggle in top right)
4. Go to **Developers → API Keys**
5. Copy:
   - **Publishable key** (starts with `pk_test_`)
   - **Secret key** (starts with `sk_test_`)

#### Create Product and Price
1. Go to **Products** in Stripe Dashboard
2. Click **Add Product**
3. Fill in:
   - Name: `SlideGen Pro Monthly`
   - Description: `Monthly subscription for SlideGen Pro`
4. Click **Add pricing**:
   - Price: `$6.99`
   - Billing period: `Monthly`
   - Currency: `USD`
5. Save and copy the **Price ID** (starts with `price_`)

#### Set Up Webhook (for local testing)
1. Install Stripe CLI:
   ```bash
   # macOS
   brew install stripe/stripe-cli/stripe
   
   # Linux
   wget https://github.com/stripe/stripe-cli/releases/download/v1.19.0/stripe_1.19.0_linux_x86_64.tar.gz
   tar -xvf stripe_1.19.0_linux_x86_64.tar.gz
   
   # Windows
   # Download from https://github.com/stripe/stripe-cli/releases
   ```

2. Login to Stripe CLI:
   ```bash
   stripe login
   ```

3. Forward webhooks to local server:
   ```bash
   stripe listen --forward-to localhost:5000/api/payment/webhook
   ```

4. Copy the **webhook signing secret** (starts with `whsec_`)

### 3. Create Environment File

```bash
# Copy the example file
cp .env.example .env

# Edit with your values
nano .env  # or use any text editor
```

Fill in:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
SECRET_KEY=your-64-char-secret-key
STRIPE_SECRET_KEY=sk_test_your-key-here
STRIPE_PUBLISHABLE_KEY=pk_test_your-key-here
STRIPE_PRICE_ID=price_your-id-here
STRIPE_WEBHOOK_SECRET=whsec_your-secret-here
```

Generate SECRET_KEY:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Verify Configuration

```bash
python3 -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('✅ ANTHROPIC_API_KEY:', 'SET' if os.getenv('ANTHROPIC_API_KEY') else '❌ MISSING')
print('✅ STRIPE_SECRET_KEY:', 'SET' if os.getenv('STRIPE_SECRET_KEY') else '❌ MISSING')
print('✅ STRIPE_PUBLISHABLE_KEY:', 'SET' if os.getenv('STRIPE_PUBLISHABLE_KEY') else '❌ MISSING')
print('✅ STRIPE_PRICE_ID:', 'SET' if os.getenv('STRIPE_PRICE_ID') else '❌ MISSING')
print('✅ SECRET_KEY:', 'SET' if os.getenv('SECRET_KEY') else '❌ MISSING')
"
```

---

## 🏃 Running Locally

### 1. Start the Backend Server

```bash
python3 server.py
```

You should see:
```
✓ API key configured
✓ Stripe configured
✓ Database initialized
✓ Authentication system ready
✓ Subscription system ready ($6.99/month for 10 generations)
✓ Grammar proofreading enabled for speaker notes
 * Running on http://0.0.0.0:5000
```

### 2. Start the Frontend Server (in a new terminal)

```bash
python3 -m http.server 3000
```

### 3. Start Stripe Webhook Listener (in a third terminal)

```bash
stripe listen --forward-to localhost:5000/api/payment/webhook
```

### 4. Open the Application

Open your browser to:
```
http://localhost:3000/index.html
```

---

## 🧪 Testing

### Test Authentication

1. **Sign Up**
   - Click "Sign Up"
   - Enter email: `test@example.com`
   - Enter password: `password123`
   - Should see: "Account created! You have 1 free presentation."

2. **Log In**
   - Use the same credentials
   - Should see subscription status banner

### Test Free Generation

1. Click "Create New Presentation"
2. Enter topic: "Artificial Intelligence"
3. Choose settings and generate
4. Should successfully create 1 presentation
5. Try to create another - should see limit reached modal

### Test Payment Flow (Stripe Test Mode)

1. Click "Upgrade to Premium"
2. Use test card:
   - Card number: `4242 4242 4242 4242`
   - Expiry: Any future date (e.g., `12/34`)
   - CVC: Any 3 digits (e.g., `123`)
   - ZIP: Any 5 digits (e.g., `12345`)
3. Complete payment
4. Should redirect to success page
5. Should now have 10 presentations per month

### Test Premium Features

1. Generate multiple presentations (up to 10)
2. Check subscription status updates
3. Test cancellation flow

### Test Grammar Proofreading

1. Generate a presentation
2. Open the downloaded PPTX
3. Go to **View → Notes Page**
4. Check speaker notes are grammatically correct

---

## 🌐 Deployment

### Option 1: Deploy to Heroku

1. Create `Procfile`:
   ```
   web: python server.py
   ```

2. Create `requirements.txt`:
   ```bash
   flask
   flask-cors
   requests
   python-dotenv
   stripe
   python-pptx
   ```

3. Deploy:
   ```bash
   heroku create your-app-name
   heroku config:set ANTHROPIC_API_KEY=your-key
   heroku config:set STRIPE_SECRET_KEY=your-key
   heroku config:set STRIPE_PUBLISHABLE_KEY=your-key
   heroku config:set STRIPE_PRICE_ID=your-id
   heroku config:set STRIPE_WEBHOOK_SECRET=your-secret
   heroku config:set SECRET_KEY=your-secret
   git push heroku main
   ```

4. Set up production webhook:
   - In Stripe Dashboard: Developers → Webhooks
   - Add endpoint: `https://your-app.herokuapp.com/api/payment/webhook`
   - Select events and copy new webhook secret
   - Update heroku config with new webhook secret

### Option 2: Deploy to DigitalOcean App Platform

1. Create `requirements.txt` (same as above)

2. Create app in DigitalOcean:
   - Connect your GitHub repo
   - Set environment variables in dashboard
   - Deploy

3. Set up webhook endpoint in Stripe Dashboard

### Option 3: Deploy to Railway

1. Create account at https://railway.app
2. New Project → Deploy from GitHub
3. Add environment variables
4. Deploy
5. Set up Stripe webhook

### Production Checklist

- [ ] Switch to Stripe **Live Mode**
- [ ] Get live API keys from Stripe
- [ ] Update environment variables with live keys
- [ ] Set up production webhook endpoint
- [ ] Test with real payment method
- [ ] Set up error monitoring (Sentry, etc.)
- [ ] Add SSL certificate (HTTPS)
- [ ] Set up custom domain
- [ ] Configure CORS for production domain
- [ ] Set up backup system for database
- [ ] Add logging and monitoring
- [ ] Test subscription cancellation flow
- [ ] Verify monthly limit reset works

---

## 🐛 Troubleshooting

### Issue: "ANTHROPIC_API_KEY not set"

**Solution:**
```bash
export ANTHROPIC_API_KEY='your-key-here'
python3 server.py
```

Or add to `.env` file.

### Issue: "Stripe not configured"

**Solution:**
Make sure all Stripe variables are set in `.env`:
```bash
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_PRICE_ID=price_...
```

### Issue: Database locked error

**Solution:**
```bash
# Kill any running processes
pkill -f server.py

# Remove database and restart
rm slidegen.db
python3 server.py
```

### Issue: Webhook not receiving events

**Solution:**
1. Make sure Stripe CLI is running:
   ```bash
   stripe listen --forward-to localhost:5000/api/payment/webhook
   ```

2. Check webhook secret matches in `.env`

3. For production, verify webhook URL in Stripe Dashboard

### Issue: Payment not activating premium

**Solution:**
1. Check server logs for webhook events
2. Verify webhook secret is correct
3. Test webhook manually:
   ```bash
   stripe trigger checkout.session.completed
   ```

### Issue: Grammar proofreading not working

**Solution:**
1. Verify ANTHROPIC_API_KEY has sufficient credits
2. Check API usage at console.anthropic.com
3. Notes will fallback to original if proofreading fails

### Issue: CORS errors in browser

**Solution:**
Update CORS origins in `server.py`:
```python
CORS(app, supports_credentials=True, 
     origins=["http://localhost:3000", "https://your-domain.com"])
```

### Issue: Session not persisting

**Solution:**
Make sure cookies are enabled and `credentials: 'include'` is in all fetch requests:
```javascript
fetch('/api/endpoint', {
    credentials: 'include'
})
```

---

## 📊 Database Management

### View Database

```bash
sqlite3 slidegen.db
```

```sql
-- View all users
SELECT * FROM users;

-- View subscription stats
SELECT subscription_status, COUNT(*) 
FROM users 
GROUP BY subscription_status;

-- View recent presentations
SELECT u.email, p.title, p.created_at 
FROM presentations p 
JOIN users u ON p.user_id = u.id 
ORDER BY p.created_at DESC 
LIMIT 10;
```

### Backup Database

```bash
# Create backup
cp slidegen.db slidegen_backup_$(date +%Y%m%d).db

# Restore from backup
cp slidegen_backup_20240101.db slidegen.db
```

### Reset User Limits (for testing)

```sql
-- Reset all users to free with 1 presentation
UPDATE users 
SET generations_used = 0, 
    generations_limit = 1,
    subscription_status = 'free';

-- Give specific user premium manually (for testing)
UPDATE users 
SET subscription_status = 'premium',
    generations_limit = 10,
    generations_used = 0
WHERE email = 'test@example.com';
```

---

## 🔐 Security Best Practices

1. **Never commit .env file**
   ```bash
   echo ".env" >> .gitignore
   ```

2. **Use strong secret keys**
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

3. **Use HTTPS in production**
   - Get SSL certificate (Let's Encrypt)
   - Force HTTPS redirects

4. **Rate limit API endpoints**
   - Already implemented in code
   - Adjust limits as needed

5. **Monitor for suspicious activity**
   - Check logs regularly
   - Set up alerts for failed payments

6. **Rotate API keys regularly**
   - Especially if compromised
   - Update all environments

---

## 📞 Support Resources

- **Stripe Docs:** https://stripe.com/docs
- **Anthropic Docs:** https://docs.anthropic.com
- **Flask Docs:** https://flask.palletsprojects.com
- **python-pptx Docs:** https://python-pptx.readthedocs.io

---

## ✅ Quick Reference

### Start All Services (Development)

```bash
# Terminal 1: Backend
python3 server.py

# Terminal 2: Frontend
python3 -m http.server 3000

# Terminal 3: Stripe Webhooks
stripe listen --forward-to localhost:5000/api/payment/webhook
```

### Test Cards

- Success: `4242 4242 4242 4242`
- Requires authentication: `4000 0025 0000 3155`
- Declined: `4000 0000 0000 9995`

### Environment Variables Quick Check

```bash
python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Keys configured!' if all([os.getenv('ANTHROPIC_API_KEY'), os.getenv('STRIPE_SECRET_KEY')]) else 'Missing keys!')"
```

---

**You're all set! 🚀**

For issues or questions, check the troubleshooting section above.
