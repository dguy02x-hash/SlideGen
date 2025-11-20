# SlideGen Pro - Deployment Guide

## Quick Deploy to Render.com

### Prerequisites
1. GitHub account
2. Render.com account (free)
3. All API keys ready:
   - Anthropic API Key
   - Stripe Secret Key
   - Stripe Publishable Key
   - Stripe Price ID
   - Stripe Webhook Secret

### Step-by-Step Deployment

#### 1. Push Code to GitHub

```bash
# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit - SlideGen Pro"

# Create GitHub repo and push
git remote add origin https://github.com/YOUR_USERNAME/slidegen-pro.git
git branch -M main
git push -u origin main
```

#### 2. Deploy to Render

1. Go to [render.com](https://render.com) and sign in
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: `slidegen-pro` (or your choice)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`
   - **Instance Type**: Free

#### 3. Add Environment Variables

In Render dashboard, go to "Environment" tab and add:

```
ANTHROPIC_API_KEY=your_anthropic_key
STRIPE_SECRET_KEY=your_stripe_secret
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable
STRIPE_PRICE_ID=your_price_id
STRIPE_WEBHOOK_SECRET=your_webhook_secret
PORT=10000
DEBUG=False
SECRET_KEY=your_random_secret_key_here
```

**Generate a SECRET_KEY** with:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

#### 4. Deploy

Click "Create Web Service" and wait for deployment (5-10 minutes).

Your app will be available at: `https://slidegen-pro.onrender.com`

#### 5. Update Stripe Webhook

1. Go to Stripe Dashboard → Developers → Webhooks
2. Click "Add endpoint"
3. Enter: `https://your-app.onrender.com/api/payment/webhook`
4. Select events to listen to:
   - `checkout.session.completed`
   - `invoice.payment_succeeded`
   - `customer.subscription.deleted`
5. Copy the **Signing Secret** and update `STRIPE_WEBHOOK_SECRET` in Render

#### 6. Update CORS (if needed)

If you're using a custom domain, update the environment variable:
```
FRONTEND_URL=https://yourdomain.com
```

### Custom Domain Setup

1. In Render dashboard, go to "Settings" → "Custom Domain"
2. Add your domain
3. Update your DNS records:
   - Add CNAME record pointing to Render's URL
   - Wait for DNS propagation (can take up to 48 hours)
4. Render will automatically provision SSL certificate

### Monitoring

- View logs in Render dashboard
- Monitor API usage in Anthropic dashboard
- Check payments in Stripe dashboard

### Troubleshooting

#### App crashes on startup
- Check logs in Render dashboard
- Verify all environment variables are set
- Ensure `requirements.txt` includes all dependencies

#### Database errors
- Render uses ephemeral storage - database resets on restart
- For production, consider using a persistent database (PostgreSQL)
- To add PostgreSQL:
  1. In Render, create a new PostgreSQL database
  2. Update `server.py` to use PostgreSQL instead of SQLite
  3. Add `psycopg2-binary` to `requirements.txt`

#### Payment not working
- Verify Stripe webhook URL is correct
- Check Stripe webhook signing secret
- Ensure webhook is receiving events in Stripe dashboard

### Scaling

Free tier limitations:
- App spins down after 15 minutes of inactivity
- 750 hours/month free compute time
- First request after spin-down takes 30-60 seconds

To upgrade:
- Go to Render dashboard → Settings → Instance Type
- Select paid plan ($7/month for Starter)
- No spin-down on paid plans

### Database Backup

For SQLite (current setup):
```bash
# Download database from Render
render shell
cp slidegen.db /tmp/
# Download from /tmp/ in Render dashboard
```

For production, use PostgreSQL with automatic backups.

### Support

For issues:
- Check Render logs
- Review Stripe webhook logs
- Verify Anthropic API quota
- Check environment variables are correct

### Cost Estimate

Monthly costs:
- Render: Free (or $7/month for no spin-down)
- Anthropic API: Pay-per-use (~$0.015 per 1K tokens)
- Stripe: 2.9% + $0.30 per transaction
- Domain: ~$10-15/year (optional)

Total: $0-20/month depending on usage
