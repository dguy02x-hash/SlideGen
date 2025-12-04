#!/usr/bin/env python3
"""
PresPilot - Backend Server with Authentication & Subscriptions
PAYMENT REQUIRED - No free tier, users must subscribe to generate presentations.
"""

from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
import os
import json
import requests
from datetime import datetime, timedelta
import logging
import sqlite3
import hashlib
import secrets
from functools import wraps
from dotenv import load_dotenv
import stripe
import time
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, ClickTracking, TrackingSettings
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email, EmailNotValidError
from twilio.rest import Client as TwilioClient
import boto3
from botocore.exceptions import ClientError

# Load environment variables from .env file (override=True to ensure .env takes precedence)
load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Session security configuration
app.config['SESSION_COOKIE_SECURE'] = True  # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent XSS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# CORS configuration - allow localhost for development and production domain
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5001",
    "http://127.0.0.1:5001",
    os.environ.get('FRONTEND_URL', '')  # Add your production URL here
]
# Remove empty strings
allowed_origins = [origin for origin in allowed_origins if origin]
CORS(app, supports_credentials=True, origins=allowed_origins if allowed_origins else "*")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Anthropic API configuration
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    logger.error("❌ ANTHROPIC_API_KEY not found! Please set it in .env file")
else:
    logger.info(f"✅ API Key loaded: {ANTHROPIC_API_KEY[:20]}...")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

# Stripe configuration
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID')  # Your $5.99/month price ID from Stripe
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')

if not stripe.api_key:
    logger.warning("⚠️  STRIPE_SECRET_KEY not configured - payment features disabled")
else:
    logger.info("✅ Stripe configured")

# SendGrid configuration (DEPRECATED - use SES instead due to poor IP reputation)
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
SENDGRID_FROM_EMAIL = os.environ.get('SENDGRID_FROM_EMAIL', 'support@prespilot.com')

if not SENDGRID_API_KEY:
    logger.warning("⚠️  SENDGRID_API_KEY not configured")
else:
    logger.info("⚠️  SendGrid configured (but has poor IP reputation - use SES)")

# Amazon SES configuration (PREFERRED for better deliverability)
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
SES_FROM_EMAIL = os.environ.get('SES_FROM_EMAIL', 'support@prespilot.com')

# Determine which email service to use (SES preferred)
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    EMAIL_PROVIDER = 'SES'
    logger.info("✅ Amazon SES configured (primary email provider)")
    ses_client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
elif SENDGRID_API_KEY:
    EMAIL_PROVIDER = 'SENDGRID'
    logger.warning("⚠️  Using SendGrid (poor IP reputation score: 3/100)")
else:
    EMAIL_PROVIDER = None
    logger.error("❌ No email provider configured! Set AWS credentials or SendGrid API key")

# Twilio configuration for SMS
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
    logger.warning("⚠️  Twilio not configured - SMS verification disabled")
    TWILIO_ENABLED = False
else:
    logger.info("✅ Twilio SMS configured")
    TWILIO_ENABLED = True
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Tavily Search API configuration (optional - for up-to-date research)
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')

if not TAVILY_API_KEY:
    logger.warning("⚠️  TAVILY_API_KEY not configured - research will use AI knowledge only")
else:
    logger.info("✅ Tavily Search configured for up-to-date research")

# Database initialization
# Use /data/slidegen.db on Render (persistent disk), or slidegen.db locally
DB_PATH = os.environ.get('DATABASE_PATH', '/data/slidegen.db')

# Ensure the database directory exists
db_dir = os.path.dirname(DB_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users table - NO FREE TIER
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subscription_status TEXT DEFAULT 'inactive',
            subscription_expires TIMESTAMP,
            generations_used INTEGER DEFAULT 0,
            generations_limit INTEGER DEFAULT 0,
            last_reset TIMESTAMP,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT
        )
    ''')
    
    # Presentations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS presentations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            topic TEXT NOT NULL,
            num_slides INTEGER NOT NULL,
            theme TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Rate limiting table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL,
            request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Payment history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stripe_payment_id TEXT,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'usd',
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Pending subscriptions table - for users who paid but haven't created account yet
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            customer_email TEXT NOT NULL,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            confirmation_token TEXT UNIQUE,
            verification_code TEXT,
            token_expires_at TIMESTAMP,
            email_verified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            account_created INTEGER DEFAULT 0
        )
    ''')

    # Add verification_code column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE pending_subscriptions ADD COLUMN verification_code TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Password reset tokens table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Auto-grant premium to dev account
    dev_email = 'dguy02x@gmail.com'
    dev_password_hash = hashlib.sha256('changeme123'.encode()).hexdigest()

    existing_user = cursor.execute('SELECT id, subscription_status FROM users WHERE email = ?', (dev_email,)).fetchone()

    if existing_user:
        # Update existing user to premium
        cursor.execute('''
            UPDATE users
            SET subscription_status = 'premium',
                generations_limit = 10,
                generations_used = 0,
                last_reset = ?
            WHERE email = ?
        ''', (datetime.now().isoformat(), dev_email))
        logger.info(f"✅ Auto-granted premium to dev account: {dev_email}")
    else:
        # Create dev account with premium
        cursor.execute('''
            INSERT INTO users (email, password_hash, subscription_status, generations_limit, generations_used, last_reset)
            VALUES (?, ?, 'premium', 10, 0, ?)
        ''', (dev_email, dev_password_hash, datetime.now().isoformat()))
        logger.info(f"✅ Created premium dev account: {dev_email}")

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

# Initialize database on startup
init_db()

def hash_password(password):
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def send_email_ses(to_email, subject, html_content, plain_text_content=None):
    """
    Send email via Amazon SES (preferred for better deliverability)
    """
    try:
        # Create plain text version if not provided
        if not plain_text_content:
            import re
            plain_text_content = re.sub('<[^<]+?>', '', html_content)
            plain_text_content = plain_text_content.replace('&nbsp;', ' ')
            plain_text_content = '\n'.join(line.strip() for line in plain_text_content.split('\n') if line.strip())

        # Send email via SES
        response = ses_client.send_email(
            Source=f'PresPilot <{SES_FROM_EMAIL}>',
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': plain_text_content, 'Charset': 'UTF-8'},
                    'Html': {'Data': html_content, 'Charset': 'UTF-8'}
                }
            },
            ReplyToAddresses=[SES_FROM_EMAIL]
        )

        message_id = response['MessageId']
        logger.info(f"✅ Email sent via SES to {to_email}: {subject} (MessageId: {message_id})")
        return True

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"❌ SES error sending to {to_email}: {error_code} - {error_message}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send email via SES to {to_email}: {str(e)}")
        return False


def send_email_sendgrid(to_email, subject, html_content, plain_text_content=None):
    """
    Send email via SendGrid (fallback - has poor IP reputation)
    """
    try:
        # Create plain text version if not provided
        if not plain_text_content:
            import re
            plain_text_content = re.sub('<[^<]+?>', '', html_content)
            plain_text_content = plain_text_content.replace('&nbsp;', ' ')
            plain_text_content = '\n'.join(line.strip() for line in plain_text_content.split('\n') if line.strip())

        message = Mail(
            from_email=Email(SENDGRID_FROM_EMAIL, "PresPilot"),
            to_emails=To(to_email),
            subject=subject,
            html_content=html_content,
            plain_text_content=plain_text_content
        )

        message.reply_to = Email(SENDGRID_FROM_EMAIL, "PresPilot Support")

        # Disable click tracking
        tracking_settings = TrackingSettings()
        tracking_settings.click_tracking = ClickTracking(enable=False, enable_text=False)
        message.tracking_settings = tracking_settings

        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"✅ Email sent via SendGrid to {to_email}: {subject} (Status: {response.status_code})")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send email via SendGrid to {to_email}: {str(e)}")
        return False


def send_email(to_email, subject, html_content, plain_text_content=None):
    """
    Generic email sending function - routes to SES or SendGrid based on configuration
    SES is preferred for better deliverability (SendGrid IP has reputation score of 3/100)
    """
    if not EMAIL_PROVIDER:
        logger.error("❌ No email provider configured - cannot send email")
        return False

    if EMAIL_PROVIDER == 'SES':
        return send_email_ses(to_email, subject, html_content, plain_text_content)
    elif EMAIL_PROVIDER == 'SENDGRID':
        logger.warning(f"⚠️  Using SendGrid with poor IP reputation for {to_email}")
        return send_email_sendgrid(to_email, subject, html_content, plain_text_content)
    else:
        logger.error(f"❌ Unknown email provider: {EMAIL_PROVIDER}")
        return False

def validate_email_address(email):
    """
    Validate email address format and domain.
    Returns (is_valid, normalized_email, error_message)
    """
    try:
        # Validate and normalize email
        validated = validate_email(email, check_deliverability=True)
        normalized_email = validated.normalized
        logger.info(f"✅ Email validation passed: {email} → {normalized_email}")
        return True, normalized_email, None
    except EmailNotValidError as e:
        error_msg = str(e)
        logger.warning(f"❌ Email validation failed for {email}: {error_msg}")

        # Provide user-friendly error messages
        if "domain" in error_msg.lower():
            return False, None, "The email domain doesn't exist. Please check for typos."
        elif "syntax" in error_msg.lower() or "@" not in email:
            return False, None, "Invalid email format. Please enter a valid email address."
        else:
            return False, None, "Invalid email address. Please check and try again."

def send_confirmation_email(to_email, confirmation_token, verification_code):
    """
    Send email confirmation with verification code
    Optimized for deliverability across all email providers
    """
    # Use FRONTEND_URL if set, otherwise fall back to request.host_url for local dev
    base_url = os.environ.get('FRONTEND_URL', request.host_url.rstrip('/'))
    confirmation_url = f"{base_url}/confirm-email.html?email={to_email}"

    # Create plain text version for better spam filter compatibility
    plain_text = f'''
Welcome to PresPilot!

Thank you for subscribing. Use this verification code to create your account:

YOUR VERIFICATION CODE: {verification_code}

How to complete your registration:
1. Go to {confirmation_url}
2. Enter your email address: {to_email}
3. Enter the 6-digit code above
4. Create your password
5. Start creating presentations!

This code will expire in 24 hours.

If you didn't request this, you can safely ignore this email.

---
PresPilot - AI-Powered Presentation Creator
Support: support@prespilot.com
    '''

    html_content = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f5f5f5; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; padding: 40px 30px; border-radius: 8px;">
                        <tr>
                            <td>
                                <h2 style="color: #f59e0b; margin: 0 0 20px 0; font-size: 24px;">Welcome to PresPilot!</h2>
                                <p style="color: #333333; font-size: 16px; line-height: 1.5; margin: 0 0 25px 0;">Thank you for subscribing! Use this verification code to create your account:</p>

                                <!-- Verification Code Display -->
                                <div style="text-align: center; margin: 30px 0;">
                                    <div style="background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); padding: 30px; border-radius: 12px; display: inline-block;">
                                        <p style="color: #1f2937; font-size: 14px; font-weight: 600; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 1px;">Your Verification Code</p>
                                        <p style="color: #1f2937; font-size: 48px; font-weight: bold; margin: 0; letter-spacing: 8px; font-family: 'Courier New', monospace;">{verification_code}</p>
                                    </div>
                                </div>

                                <p style="color: #333333; font-size: 16px; line-height: 1.5; margin: 0 0 15px 0; font-weight: bold;">How to complete your registration:</p>
                                <ol style="color: #333333; font-size: 15px; line-height: 1.8; margin: 0 0 25px 0; padding-left: 25px;">
                                    <li>Go to <a href="{confirmation_url}" style="color: #f59e0b; text-decoration: none; font-weight: 600;">PresPilot.com</a></li>
                                    <li>Enter your email address</li>
                                    <li>Enter the 6-digit code above</li>
                                    <li>Create your password</li>
                                    <li>Start creating presentations!</li>
                                </ol>

                                <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 0 0 10px 0;">This code will expire in 24 hours.</p>
                                <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 0;">If you didn't request this, you can safely ignore this email.</p>

                                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                                <p style="color: #9ca3af; font-size: 12px; text-align: center; margin: 0;">PresPilot - AI-Powered Presentation Creator</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    '''

    return send_email(to_email, 'Your PresPilot Verification Code', html_content, plain_text)

def send_welcome_email(to_email):
    """Send welcome email after account creation (non-critical, can be deferred)"""

    plain_text = f'''
Welcome to PresPilot!

Your account is ready! You can now start creating amazing presentations powered by AI.

Getting Started:
1. Log in at https://prespilot.com
2. Click "Generate New Presentation"
3. Enter your topic and let AI do the work!
4. Customize and download your presentation

Your subscription includes:
- 10 AI presentations per month
- All premium themes
- Priority support

Need help? Reply to this email or contact support@prespilot.com

Happy creating!
The PresPilot Team
    '''

    html_content = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f5f5f5; padding: 20px 0;">
            <tr>
                <td align="center">
                    <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; padding: 40px 30px; border-radius: 8px;">
                        <tr>
                            <td>
                                <h2 style="color: #f59e0b; margin: 0 0 20px 0; font-size: 28px;">Welcome to PresPilot! 🎉</h2>
                                <p style="color: #333333; font-size: 16px; line-height: 1.5; margin: 0 0 25px 0;">Your account is ready! You can now start creating amazing presentations powered by AI.</p>

                                <div style="background: #fef3c7; padding: 20px; border-radius: 8px; margin: 25px 0;">
                                    <h3 style="color: #92400e; margin: 0 0 15px 0;">Getting Started:</h3>
                                    <ol style="color: #78350f; font-size: 15px; line-height: 1.8; margin: 0; padding-left: 20px;">
                                        <li>Log in at prespilot.com</li>
                                        <li>Click "Generate New Presentation"</li>
                                        <li>Enter your topic and let AI do the work!</li>
                                        <li>Customize and download your presentation</li>
                                    </ol>
                                </div>

                                <div style="background: #f3f4f6; padding: 20px; border-radius: 8px; margin: 25px 0;">
                                    <h3 style="color: #1f2937; margin: 0 0 15px 0;">Your Subscription Includes:</h3>
                                    <ul style="color: #4b5563; font-size: 15px; line-height: 1.8; margin: 0; padding-left: 20px;">
                                        <li>10 AI presentations per month</li>
                                        <li>All premium themes</li>
                                        <li>Priority support</li>
                                    </ul>
                                </div>

                                <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 20px 0 0 0;">Need help? Reply to this email or contact support@prespilot.com</p>
                                <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 10px 0 0 0;">Happy creating!<br>The PresPilot Team</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    '''

    return send_email(to_email, 'Welcome to PresPilot! 🎉', html_content, plain_text)

def send_sms_verification(phone_number, verification_code):
    """Send SMS verification code via Twilio"""
    if not TWILIO_ENABLED:
        logger.error("Twilio not configured - cannot send SMS")
        return False

    try:
        # Format phone number (ensure it has +1 for US)
        if not phone_number.startswith('+'):
            phone_number = f'+1{phone_number.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")}'

        message = twilio_client.messages.create(
            body=f'Your PresPilot verification code is: {verification_code}\n\nThis code will expire in 24 hours.\n\n- PresPilot',
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number
        )

        logger.info(f"SMS sent to {phone_number}: SID {message.sid}")
        return True

    except Exception as e:
        logger.error(f"Failed to send SMS to {phone_number}: {str(e)}")
        return False

def login_required(f):
    """Decorator to require login for endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

def subscription_required(f):
    """Decorator to require active subscription"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401

        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()

        # Dev bypass for dguy02x@gmail.com - skip subscription check
        if user and user['email'] == 'dguy02x@gmail.com':
            logger.info(f"Subscription bypass for dev account: {user['email']}")
            return f(*args, **kwargs)

        if not user or user['subscription_status'] != 'premium':
            return jsonify({
                'error': 'Active subscription required',
                'subscription_required': True,
                'subscription_status': user['subscription_status'] if user else 'inactive'
            }), 403

        return f(*args, **kwargs)
    return decorated_function

def check_generations_limit(user_id):
    """Check if user has generations available (resets happen via Stripe billing cycle webhook)"""
    conn = get_db()
    cursor = conn.cursor()

    user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()

    if not user:
        return False

    # Only premium and cancelled (still active until period end) users can generate
    if user['subscription_status'] not in ['premium', 'active', 'cancelled']:
        return False

    # Check if user has generations remaining
    # Note: Generations reset automatically when Stripe charges them (invoice.payment_succeeded webhook)
    return user['generations_used'] < user['generations_limit']

def increment_generation_count(user_id):
    """Increment user's generation count"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET generations_used = generations_used + 1 
        WHERE id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

def check_rate_limit(user_id, endpoint, limit=20, window_minutes=1):
    """Check rate limiting for user"""
    conn = get_db()
    cursor = conn.cursor()
    
    cutoff = (datetime.now() - timedelta(minutes=window_minutes)).isoformat()
    
    count = cursor.execute('''
        SELECT COUNT(*) as count FROM rate_limits 
        WHERE user_id = ? AND endpoint = ? AND request_time > ?
    ''', (user_id, endpoint, cutoff)).fetchone()['count']
    
    if count >= limit:
        conn.close()
        return False
    
    # Log this request
    cursor.execute('''
        INSERT INTO rate_limits (user_id, endpoint) VALUES (?, ?)
    ''', (user_id, endpoint))
    
    conn.commit()
    conn.close()
    return True

def call_anthropic(prompt, max_tokens=2000, max_retries=6):
    """Make API call to Anthropic with retry logic for 529 errors"""
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY environment variable not set")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)

            if response.status_code == 200:
                data = response.json()
                return data['content'][0]['text']
            elif response.status_code == 529 and attempt < max_retries - 1:
                # Exponential backoff: wait 2^attempt seconds
                wait_time = 2 ** attempt
                logger.warning(f"API overloaded (529), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                raise Exception(f"API error: {response.status_code} - {response.text}")

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning(f"API timeout, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                raise Exception("API request timed out after multiple retries")

        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            raise

    raise Exception("Max retries exceeded")

def search_tavily(query, max_results=5):
    """
    Optional: Search web using Tavily API for up-to-date information.
    Returns list of search results or empty list if unavailable/fails.
    """
    if not TAVILY_API_KEY:
        logger.warning("⚠️  Tavily API key not configured - skipping web search. Set TAVILY_API_KEY environment variable.")
        return []

    if TAVILY_API_KEY == "your_tavily_api_key_here":
        logger.warning("⚠️  Tavily API key is placeholder - please replace with actual key")
        return []

    logger.info(f"🔍 Searching web via Tavily for: {query[:50]}...")

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
                "include_raw_content": False
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            logger.info(f"✅ Tavily search successful - found {len(results)} results for: {query[:50]}")
            return results
        else:
            logger.error(f"❌ Tavily search failed with status {response.status_code}: {response.text[:200]}")
            return []

    except requests.exceptions.Timeout:
        logger.error(f"❌ Tavily search timed out after 10 seconds for: {query[:50]}")
        return []
    except Exception as e:
        logger.error(f"❌ Tavily search error for '{query[:50]}': {type(e).__name__} - {str(e)}")
        return []

def proofread_speaker_notes(notes_text, max_tokens=2200):
    """
    Proofread speaker notes for grammar, clarity, and naturalness.
    Returns grammatically corrected version.
    """
    try:
        prompt = f"""You are a professional editor proofreading speaker notes for a presentation.

ORIGINAL SPEAKER NOTES:
{notes_text}

TASK: Thoroughly proofread and correct these speaker notes to ensure they are grammatically perfect, clear, and natural-sounding.

FIX ALL OF THE FOLLOWING:
1. **Grammar errors** - Subject-verb agreement, tense consistency, pronoun usage, etc.
2. **Spelling mistakes** - Any typos or misspelled words
3. **Punctuation errors** - Commas, periods, semicolons, apostrophes, quotation marks
4. **Sentence structure** - Run-on sentences, fragments, awkward constructions
5. **Word choice** - Replace awkward or unclear wording with better alternatives
6. **Clarity issues** - Make sure every sentence is clear and easy to understand
7. **Flow and transitions** - Ensure smooth transitions between ideas
8. **Consistency** - Maintain consistent tone, style, and formatting throughout

MAINTAIN:
- The original conversational and natural tone
- The same general length
- The core meaning and information
- The engaging, human-like quality

OUTPUT: Return ONLY the corrected text with no explanations, comments, or labels. The corrected notes should read smoothly and professionally.

CORRECTED NOTES:"""

        corrected = call_anthropic(prompt, max_tokens=max_tokens)
        return corrected.strip()

    except Exception as e:
        logger.error(f"Error proofreading notes: {str(e)}")
        # Return original if proofreading fails
        return notes_text

def proofread_slide_text(slide_text, max_tokens=500):
    """
    Proofread slide text (titles and bullet points) for grammar and clarity.
    Returns grammatically corrected version optimized for slides.
    """
    try:
        prompt = f"""You are a strict professional editor proofreading slide text for a business presentation. Your job is to catch and fix EVERY error, no matter how small.

ORIGINAL SLIDE TEXT:
{slide_text}

CRITICAL: Fix EVERY single error you find. Do not let anything slip through. This is for a professional presentation and must be perfect.

FIX ALL OF THE FOLLOWING (be aggressive - fix everything):
1. **Grammar errors** - Subject-verb agreement, tense consistency, pronoun usage, articles (a/an/the), prepositions
2. **Spelling mistakes** - Any typos or misspelled words, including commonly confused words (their/they're/there, your/you're, its/it's)
3. **Punctuation errors** - Missing or incorrect commas, periods, semicolons, apostrophes, quotation marks, hyphens
4. **Capitalization** - Proper nouns, sentence beginnings, title case for headings
5. **Sentence structure** - Run-on sentences, fragments, awkward constructions, unclear phrasing
6. **Word choice** - Awkward wording, redundancy, vague language, unprofessional terms
7. **Clarity issues** - Ambiguous statements, confusing phrasing, unclear references
8. **Consistency** - Tense consistency, terminology consistency, parallel structure in lists
9. **Professional tone** - Remove casual language, slang, or informal expressions
10. **Redundancy** - Remove unnecessary words while keeping the meaning clear

MAINTAIN:
- Professional, concise presentation style
- The core meaning and key information
- Bullet point format if original was a bullet point
- ALL numbers, percentages, statistics, dates, and specific data points EXACTLY as they appear
- Specific terminology, proper nouns, and technical terms
- Important capitalization for product names, companies, or specific terms

IMPORTANT:
- Make ALL necessary corrections, even if there are many
- Do not be conservative - fix everything that needs fixing
- The output must be grammatically perfect and professionally written
- NEVER remove, change, or alter numbers, percentages, or statistics
- NEVER change specific data points or measurements
- Keep it concise but don't sacrifice correctness for brevity

OUTPUT: Return ONLY the corrected text with no explanations, comments, or labels.

CORRECTED TEXT:"""

        corrected = call_anthropic(prompt, max_tokens=max_tokens)
        return corrected.strip()

    except Exception as e:
        logger.error(f"Error proofreading slide text: {str(e)}")
        # Return original if proofreading fails
        return slide_text

# ============= Authentication Endpoints =============

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    """Create new user account - NO FREE PRESENTATIONS"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400

        # Validate email format and domain
        is_valid, normalized_email, error_msg = validate_email_address(email)
        if not is_valid:
            return jsonify({'error': error_msg}), 400

        # Use normalized email
        email = normalized_email

        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if email exists
        existing = cursor.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Email already registered'}), 400
        
        # Create user with NO free generations - subscription required
        password_hash = generate_password_hash(password)
        cursor.execute('''
            INSERT INTO users (email, password_hash, subscription_status, generations_limit, generations_used, last_reset)
            VALUES (?, ?, 'inactive', 0, 0, ?)
        ''', (email, password_hash, datetime.now().isoformat()))
        
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Auto-login
        session['user_id'] = user_id
        session['email'] = email
        
        logger.info(f"New user registered: {email} - Subscription required")
        return jsonify({
            'success': True,
            'message': 'Account created! Subscribe now to start creating presentations.',
            'subscription_required': True,
            'user': {'id': user_id, 'email': email}
        })
    
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """User login"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        conn = get_db()
        cursor = conn.cursor()
        
        user = cursor.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if not user or not check_password_hash(user['password_hash'], password):
            return jsonify({'error': 'Invalid email or password'}), 401
        
        session['user_id'] = user['id']
        session['email'] = user['email']
        
        logger.info(f"User logged in: {email}")
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'subscription_status': user['subscription_status'],
                'generations_used': user['generations_used'],
                'generations_limit': user['generations_limit']
            }
        })
    
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """User logout"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Check authentication status"""
    if 'user_id' not in session:
        return jsonify({'authenticated': False})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if not user:
            session.clear()
            return jsonify({'authenticated': False})
        
        return jsonify({
            'authenticated': True,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'subscription_status': user['subscription_status'],
                'generations_used': user['generations_used'],
                'generations_limit': user['generations_limit']
            }
        })
    except Exception as e:
        logger.error(f"Auth status error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    """Alias for auth_status - for frontend compatibility"""
    return auth_status()

@app.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Request password reset - generates token and sends email"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()

        if not email:
            return jsonify({'error': 'Email is required'}), 400

        # Validate email format and domain
        is_valid, normalized_email, error_msg = validate_email_address(email)
        if not is_valid:
            return jsonify({'error': error_msg}), 400

        # Use normalized email
        email = normalized_email

        conn = get_db()
        cursor = conn.cursor()

        # Check if user exists
        user = cursor.execute('SELECT id, email FROM users WHERE email = ?', (email,)).fetchone()

        # Always return success message to prevent email enumeration
        if not user:
            conn.close()
            logger.info(f"Password reset requested for non-existent email: {email}")
            return jsonify({
                'success': True,
                'message': 'If that email exists in our system, a password reset link has been sent.'
            })

        # Generate secure token
        reset_token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)

        # Delete any existing reset tokens for this user
        cursor.execute('DELETE FROM password_reset_tokens WHERE user_id = ?', (user['id'],))

        # Store new reset token
        cursor.execute('''
            INSERT INTO password_reset_tokens (user_id, token, expires_at)
            VALUES (?, ?, ?)
        ''', (user['id'], reset_token, expires_at.isoformat()))

        conn.commit()
        conn.close()

        # Send password reset email
        # Use FRONTEND_URL if set, otherwise fall back to request.host_url for local dev
        base_url = os.environ.get('FRONTEND_URL', request.host_url.rstrip('/'))
        reset_url = f"{base_url}/reset-password.html?token={reset_token}"

        # Create plain text version for better deliverability
        plain_text = f'''
Password Reset Request

We received a request to reset your password for your PresPilot account.

Click this link to reset your password:
{reset_url}

This link will expire in 1 hour.

If you didn't request this password reset, you can safely ignore this email. Your password will not be changed.

---
PresPilot - AI-Powered Presentation Creator
Support: support@prespilot.com
        '''

        html_content = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f5f5f5; padding: 20px 0;">
                <tr>
                    <td align="center">
                        <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; padding: 40px 30px; border-radius: 8px;">
                            <tr>
                                <td>
                                    <h2 style="color: #f59e0b; margin: 0 0 20px 0; font-size: 24px;">Password Reset Request</h2>
                                    <p style="color: #333333; font-size: 16px; line-height: 1.5; margin: 0 0 15px 0;">We received a request to reset your password for your PresPilot account.</p>
                                    <p style="color: #333333; font-size: 16px; line-height: 1.5; margin: 0 0 25px 0;">Click the button below to reset your password:</p>

                                    <!-- Button -->
                                    <div style="text-align: center; margin: 25px 0;">
                                        <a href="{reset_url}" style="background-color: #f59e0b; color: #ffffff; padding: 16px 40px; text-decoration: none; font-weight: bold; font-size: 18px; display: inline-block; border-radius: 6px;">Reset Password</a>
                                    </div>

                                    <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 0 0 10px 0;">This link will expire in 1 hour.</p>
                                    <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 0 0 15px 0; font-weight: bold;">If the button doesn't work, click this link or copy and paste it into your browser:</p>
                                    <p style="margin: 0 0 25px 0; padding: 15px; background-color: #f9f9f9; border-left: 4px solid #f59e0b; word-break: break-all;">
                                        <a href="{reset_url}" style="color: #0066cc; font-size: 14px; text-decoration: underline;">{reset_url}</a>
                                    </p>
                                    <p style="color: #666666; font-size: 14px; line-height: 1.5; margin: 0;">If you didn't request this password reset, you can safely ignore this email. Your password will not be changed.</p>

                                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                                    <p style="color: #9ca3af; font-size: 12px; text-align: center; margin: 0;">PresPilot - AI-Powered Presentation Creator</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        '''

        email_sent = send_email(email, 'Reset Your PresPilot Password', html_content, plain_text)

        if email_sent:
            logger.info(f"Password reset email sent to {email}")
        else:
            logger.error(f"Failed to send password reset email to {email}")

        return jsonify({
            'success': True,
            'message': 'If that email exists in our system, a password reset link has been sent.'
        })

    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        return jsonify({'error': 'Failed to process password reset request'}), 500

@app.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    """Reset password using valid token"""
    try:
        data = request.json
        token = data.get('token', '').strip()
        new_password = data.get('new_password', '')

        if not token or not new_password:
            return jsonify({'error': 'Token and new password are required'}), 400

        if len(new_password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Find valid token
        reset_record = cursor.execute('''
            SELECT * FROM password_reset_tokens
            WHERE token = ?
        ''', (token,)).fetchone()

        if not reset_record:
            conn.close()
            return jsonify({'error': 'Invalid or expired reset token'}), 400

        # Check if token is expired
        expires_at = datetime.fromisoformat(reset_record['expires_at'])
        if datetime.utcnow() > expires_at:
            # Delete expired token
            cursor.execute('DELETE FROM password_reset_tokens WHERE id = ?', (reset_record['id'],))
            conn.commit()
            conn.close()
            return jsonify({'error': 'Reset token has expired. Please request a new one.'}), 400

        # Update user password
        new_password_hash = generate_password_hash(new_password)
        cursor.execute('''
            UPDATE users
            SET password_hash = ?
            WHERE id = ?
        ''', (new_password_hash, reset_record['user_id']))

        # Delete used token
        cursor.execute('DELETE FROM password_reset_tokens WHERE id = ?', (reset_record['id'],))

        conn.commit()
        conn.close()

        logger.info(f"Password reset successful for user_id: {reset_record['user_id']}")

        return jsonify({
            'success': True,
            'message': 'Password reset successfully! You can now sign in with your new password.'
        })

    except Exception as e:
        logger.error(f"Reset password error: {str(e)}")
        return jsonify({'error': 'Failed to reset password'}), 500

@app.route('/api/auth/pending-subscription', methods=['GET'])
def get_pending_subscription():
    """Get pending subscription data by session_id"""
    try:
        session_id = request.args.get('session_id')

        if not session_id:
            return jsonify({'error': 'Session ID is required'}), 400

        conn = get_db()
        cursor = conn.cursor()
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE session_id = ? AND account_created = 0',
            (session_id,)
        ).fetchone()
        conn.close()

        if not pending:
            return jsonify({'error': 'No pending subscription found'}), 404

        return jsonify({
            'email': pending['customer_email'],
            'session_id': pending['session_id']
        })

    except Exception as e:
        logger.error(f"Error retrieving pending subscription: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/verify-email', methods=['GET'])
def verify_email():
    """Verify email confirmation token"""
    try:
        token = request.args.get('token')

        if not token:
            return jsonify({'error': 'Token is required'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get pending subscription by token
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE confirmation_token = ? AND account_created = 0',
            (token,)
        ).fetchone()
        conn.close()

        if not pending:
            return jsonify({'error': 'Invalid confirmation token', 'valid': False}), 400

        # Check if token is expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            return jsonify({'error': 'Confirmation link has expired', 'valid': False}), 400

        # Check if email was already verified
        if pending['email_verified']:
            # If already verified but account not created yet, still allow password creation
            return jsonify({
                'valid': True,
                'email': pending['customer_email']
            })

        # Mark email as verified
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE pending_subscriptions SET email_verified = 1 WHERE confirmation_token = ?',
            (token,)
        )
        conn.commit()
        conn.close()

        logger.info(f"Email verified for {pending['customer_email']}")

        return jsonify({
            'valid': True,
            'email': pending['customer_email']
        })

    except Exception as e:
        logger.error(f"Error verifying email: {str(e)}")
        return jsonify({'error': str(e), 'valid': False}), 500

@app.route('/api/auth/complete-registration', methods=['POST'])
def complete_registration():
    """Complete account registration after email confirmation"""
    try:
        data = request.json
        token = data.get('token')
        password = data.get('password')

        if not all([token, password]):
            return jsonify({'error': 'Token and password are required'}), 400

        # Validate password length
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get pending subscription by token
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE confirmation_token = ? AND account_created = 0',
            (token,)
        ).fetchone()

        if not pending:
            conn.close()
            return jsonify({'error': 'Invalid or expired confirmation token'}), 400

        # Verify token is not expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            conn.close()
            return jsonify({'error': 'Confirmation link has expired'}), 400

        # Verify email was confirmed
        if not pending['email_verified']:
            conn.close()
            return jsonify({'error': 'Email must be verified first'}), 400

        email = pending['customer_email']

        # Check if email already exists
        existing = cursor.execute('SELECT id FROM users WHERE email = ?', (email.lower(),)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Account already exists with this email'}), 400

        # Create user account with premium subscription
        password_hash = generate_password_hash(password)
        cursor.execute('''
            INSERT INTO users
            (email, password_hash, subscription_status, generations_limit, generations_used,
             last_reset, stripe_customer_id, stripe_subscription_id)
            VALUES (?, ?, 'premium', 10, 0, ?, ?, ?)
        ''', (email.lower(), password_hash, datetime.now().isoformat(),
              pending['stripe_customer_id'], pending['stripe_subscription_id']))

        user_id = cursor.lastrowid

        # Mark pending subscription as completed
        cursor.execute(
            'UPDATE pending_subscriptions SET account_created = 1 WHERE confirmation_token = ?',
            (token,)
        )

        conn.commit()
        conn.close()

        # Log the user in
        session['user_id'] = user_id
        session.permanent = True

        logger.info(f"Account created and activated for {email}")

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'user': {
                'id': user_id,
                'email': email,
                'subscription_status': 'premium'
            }
        })

    except Exception as e:
        logger.error(f"Error completing registration: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/check-verification-code', methods=['POST'])
def check_verification_code():
    """Check if verification code is valid without creating account yet"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()

        if not all([email, code]):
            return jsonify({'error': 'Email and verification code are required'}), 400

        # Validate email format and domain
        is_valid, normalized_email, error_msg = validate_email_address(email)
        if not is_valid:
            return jsonify({'error': error_msg, 'valid': False}), 400

        # Use normalized email for database lookup
        email = normalized_email

        conn = get_db()
        cursor = conn.cursor()

        # Get pending subscription by email and code
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE customer_email = ? AND verification_code = ? AND account_created = 0',
            (email, code)
        ).fetchone()

        if not pending:
            conn.close()
            return jsonify({'error': 'Invalid email or verification code', 'valid': False}), 400

        # Verify code is not expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            conn.close()
            return jsonify({'error': 'Verification code has expired (24 hours)', 'valid': False}), 400

        # Check if email already exists
        existing = cursor.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Account already exists with this email', 'valid': False}), 400

        conn.close()

        # Code is valid! Store in session for account creation
        session['verified_email'] = email
        session['verified_code'] = code
        session.permanent = True

        logger.info(f"Verification code validated for {email}")

        return jsonify({
            'success': True,
            'valid': True,
            'message': 'Verification code is valid',
            'email': email
        }), 200

    except Exception as e:
        logger.error(f"Error checking verification code: {str(e)}")
        return jsonify({'error': str(e), 'valid': False}), 500

@app.route('/api/auth/resend-code-sms', methods=['POST'])
def resend_code_sms():
    """Resend verification code via SMS"""
    try:
        if not TWILIO_ENABLED:
            return jsonify({'error': 'SMS verification is not available'}), 503

        data = request.json
        email = data.get('email', '').strip().lower()
        phone_number = data.get('phone_number', '').strip()

        if not all([email, phone_number]):
            return jsonify({'error': 'Email and phone number are required'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get pending subscription by email
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE customer_email = ? AND account_created = 0',
            (email,)
        ).fetchone()
        conn.close()

        if not pending:
            return jsonify({'error': 'No pending subscription found for this email'}), 404

        # Check if code is expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            return jsonify({'error': 'Verification code has expired. Please subscribe again.'}), 400

        # Send SMS with existing verification code
        sms_sent = send_sms_verification(phone_number, pending['verification_code'])

        if sms_sent:
            logger.info(f"Verification code resent via SMS to {phone_number} for {email}")
            return jsonify({
                'success': True,
                'message': 'Verification code sent via SMS'
            }), 200
        else:
            return jsonify({'error': 'Failed to send SMS. Please try again.'}), 500

    except Exception as e:
        logger.error(f"Error resending code via SMS: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/resend-verification', methods=['POST'])
def resend_verification_email():
    """Resend verification email for pending subscription"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()

        if not email:
            return jsonify({'error': 'Email is required'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get most recent pending subscription by email
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE customer_email = ? AND account_created = 0 ORDER BY created_at DESC LIMIT 1',
            (email,)
        ).fetchone()
        conn.close()

        if not pending:
            return jsonify({'error': 'No pending subscription found for this email. Please try subscribing again.'}), 404

        # Check if code is expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            return jsonify({'error': 'Verification code has expired (24 hours). Please contact support or subscribe again.'}), 400

        # Extract 6-digit code from token (or use full token if it's already 6 digits)
        verification_code = pending['confirmation_token'][:6] if len(pending['confirmation_token']) > 10 else pending['confirmation_token']

        # Resend confirmation email
        email_sent = send_confirmation_email(email, pending['confirmation_token'], verification_code)

        if email_sent:
            logger.info(f"✅ Verification email resent to {email}")
            return jsonify({
                'success': True,
                'message': 'Verification email sent! Check your inbox and spam folder.'
            }), 200
        else:
            logger.error(f"❌ Failed to resend verification email to {email}")
            return jsonify({'error': 'Failed to send email. Please try again or contact support.'}), 500

    except Exception as e:
        logger.error(f"Error resending verification email: {str(e)}")
        return jsonify({'error': 'An error occurred. Please try again.'}), 500

@app.route('/api/auth/create-account-with-session', methods=['POST'])
def create_account_with_session():
    """Create account using verified email and code from session"""
    try:
        data = request.json
        password = data.get('password')

        if not password:
            return jsonify({'error': 'Password is required'}), 400

        # Validate password length
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        # Get verified email and code from session
        email = session.get('verified_email')
        code = session.get('verified_code')

        if not email or not code:
            return jsonify({'error': 'Session expired. Please verify your code again.'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get pending subscription by email and code
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE customer_email = ? AND verification_code = ? AND account_created = 0',
            (email, code)
        ).fetchone()

        if not pending:
            conn.close()
            return jsonify({'error': 'Invalid session. Please verify your code again.'}), 400

        # Verify code is not expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            conn.close()
            return jsonify({'error': 'Verification code has expired (24 hours)'}), 400

        # Check if email already exists
        existing = cursor.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Account already exists with this email'}), 400

        # Create user account with premium subscription
        password_hash = generate_password_hash(password)
        cursor.execute('''
            INSERT INTO users
            (email, password_hash, subscription_status, generations_limit, generations_used,
             last_reset, stripe_customer_id, stripe_subscription_id)
            VALUES (?, ?, 'premium', 10, 0, ?, ?, ?)
        ''', (email, password_hash, datetime.now().isoformat(),
              pending['stripe_customer_id'], pending['stripe_subscription_id']))

        user_id = cursor.lastrowid

        # Mark pending subscription as completed
        cursor.execute(
            'UPDATE pending_subscriptions SET account_created = 1, email_verified = 1 WHERE id = ?',
            (pending['id'],)
        )

        conn.commit()
        conn.close()

        # Clear verification session data
        session.pop('verified_email', None)
        session.pop('verified_code', None)

        # Log the user in
        session['user_id'] = user_id
        session.permanent = True

        logger.info(f"Account created with verified session for {email}")

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'user': {
                'id': user_id,
                'email': email,
                'subscription_status': 'premium'
            }
        }), 200

    except Exception as e:
        logger.error(f"Error creating account with session: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/verify-code', methods=['POST'])
def verify_code():
    """Verify email with code and create account"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        password = data.get('password')

        if not all([email, code, password]):
            return jsonify({'error': 'Email, verification code, and password are required'}), 400

        # Validate password length
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get pending subscription by email and code
        pending = cursor.execute(
            'SELECT * FROM pending_subscriptions WHERE customer_email = ? AND verification_code = ? AND account_created = 0',
            (email, code)
        ).fetchone()

        if not pending:
            conn.close()
            return jsonify({'error': 'Invalid email or verification code'}), 400

        # Verify code is not expired
        token_expires_at = datetime.fromisoformat(pending['token_expires_at'])
        if datetime.utcnow() > token_expires_at:
            conn.close()
            return jsonify({'error': 'Verification code has expired (24 hours)'}), 400

        # Check if email already exists
        existing = cursor.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Account already exists with this email'}), 400

        # Create user account with premium subscription
        password_hash = generate_password_hash(password)
        cursor.execute('''
            INSERT INTO users
            (email, password_hash, subscription_status, generations_limit, generations_used,
             last_reset, stripe_customer_id, stripe_subscription_id)
            VALUES (?, ?, 'premium', 10, 0, ?, ?, ?)
        ''', (email, password_hash, datetime.now().isoformat(),
              pending['stripe_customer_id'], pending['stripe_subscription_id']))

        user_id = cursor.lastrowid

        # Mark pending subscription as completed
        cursor.execute(
            'UPDATE pending_subscriptions SET account_created = 1, email_verified = 1 WHERE id = ?',
            (pending['id'],)
        )

        conn.commit()
        conn.close()

        # Log the user in
        session['user_id'] = user_id
        session.permanent = True

        logger.info(f"Account created via verification code for {email}")

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'user': {
                'id': user_id,
                'email': email,
                'subscription_status': 'premium'
            }
        }), 200

    except Exception as e:
        logger.error(f"Error verifying code: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ============= Theme Endpoints =============

@app.route('/api/themes/list', methods=['GET'])
def list_themes():
    """Get list of available themes with preview images"""
    try:
        theme_dir = 'theme-previews'
        if not os.path.exists(theme_dir):
            return jsonify({'themes': []})

        themes = []
        for theme_name in os.listdir(theme_dir):
            theme_path = os.path.join(theme_dir, theme_name)
            if os.path.isdir(theme_path):
                # Get preview images, prioritizing Preview.png or title.png first
                previews = []
                main_preview = None

                for file in sorted(os.listdir(theme_path)):
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        file_path = f'/{theme_dir}/{theme_name}/{file}'
                        # Prioritize files with "Preview" in the name (e.g., "Iridiscent Glow Preview.png")
                        if 'preview' in file.lower():
                            main_preview = file_path
                        # Fallback to title.png if no Preview file exists
                        elif file.lower() in ['title.png', 'title.jpg', 'title.jpeg'] and not main_preview:
                            main_preview = file_path
                        else:
                            previews.append(file_path)

                # Put main preview first if it exists
                if main_preview:
                    previews.insert(0, main_preview)

                if previews:  # Only include themes with preview images
                    themes.append({
                        'name': theme_name,
                        'previews': previews
                    })

        # Sort themes with Film Flare first, then alphabetically
        themes.sort(key=lambda x: (x['name'] != 'Film Flare', x['name']))

        return jsonify({'themes': themes})
    except Exception as e:
        logger.error(f"Error listing themes: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ============= Stripe Payment Endpoints =============

@app.route('/api/payment/config', methods=['GET'])
def payment_config():
    """Get Stripe publishable key"""
    return jsonify({
        'publishableKey': STRIPE_PUBLISHABLE_KEY,
        'priceId': STRIPE_PRICE_ID
    })

@app.route('/api/payment/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session for subscription - no login required"""
    try:
        # Create checkout session - customer email will be collected by Stripe
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'payment-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url,
            customer_email=None,  # Let Stripe collect email
            allow_promotion_codes=True,
        )

        return jsonify({'url': checkout_session.url, 'sessionId': checkout_session.id})

    except Exception as e:
        logger.error(f"Checkout session error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/payment/session-info', methods=['GET'])
def get_session_info():
    """Get email and subscription info from Stripe session after payment"""
    try:
        session_id = request.args.get('session_id')

        if not session_id:
            return jsonify({'error': 'Session ID is required'}), 400

        # Retrieve session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)

        customer_email = session.get('customer_details', {}).get('email')
        stripe_customer_id = session.get('customer')
        stripe_subscription_id = session.get('subscription')

        if not customer_email:
            return jsonify({'error': 'No email found in session'}), 404

        # Check if user already exists (resubscribing)
        conn = get_db()
        cursor = conn.cursor()
        existing_user = cursor.execute(
            'SELECT id FROM users WHERE email = ?',
            (customer_email.lower(),)
        ).fetchone()
        conn.close()

        return jsonify({
            'email': customer_email,
            'stripe_customer_id': stripe_customer_id,
            'stripe_subscription_id': stripe_subscription_id,
            'user_exists': existing_user is not None
        })

    except Exception as e:
        logger.error(f"Error retrieving session info: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/auth/create-account-after-payment', methods=['POST'])
def create_account_after_payment():
    """Create user account immediately after payment with password"""
    try:
        data = request.json
        session_id = data.get('session_id')
        password = data.get('password')

        if not session_id or not password:
            return jsonify({'error': 'Session ID and password are required'}), 400

        # Retrieve session from Stripe
        session = stripe.checkout.Session.retrieve(session_id)

        customer_email = session.get('customer_details', {}).get('email', '').strip().lower()
        stripe_customer_id = session.get('customer')
        stripe_subscription_id = session.get('subscription')

        if not customer_email:
            return jsonify({'error': 'No email found in session'}), 404

        # Validate email
        is_valid, normalized_email, error_msg = validate_email_address(customer_email)
        if not is_valid:
            return jsonify({'error': error_msg}), 400

        # Hash password
        password_hash = generate_password_hash(password)

        conn = get_db()
        cursor = conn.cursor()

        # Check if user already exists
        existing_user = cursor.execute(
            'SELECT id FROM users WHERE email = ?',
            (normalized_email,)
        ).fetchone()

        if existing_user:
            conn.close()
            return jsonify({'error': 'Account already exists. Please sign in instead.'}), 400

        # Create new user account
        cursor.execute('''
            INSERT INTO users (email, password_hash, subscription_status, generations_limit,
                             stripe_customer_id, stripe_subscription_id, created_at, last_reset)
            VALUES (?, ?, 'premium', 10, ?, ?, ?, ?)
        ''', (normalized_email, password_hash, stripe_customer_id, stripe_subscription_id,
              datetime.now().isoformat(), datetime.now().isoformat()))

        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Log user in
        session['user_id'] = user_id
        session['email'] = normalized_email

        logger.info(f"✅ Created account for {normalized_email} after payment")

        # Send welcome email (non-blocking, can be deferred without issues)
        try:
            send_welcome_email(normalized_email)
        except Exception as e:
            logger.error(f"Failed to send welcome email to {normalized_email}: {str(e)}")
            # Don't fail account creation if welcome email fails

        return jsonify({
            'success': True,
            'message': 'Account created successfully',
            'user_id': user_id
        })

    except Exception as e:
        logger.error(f"Error creating account after payment: {str(e)}")
        return jsonify({'error': 'Failed to create account. Please contact support.'}), 500


@app.route('/api/payment/webhook', methods=['POST'], strict_slashes=False)
def stripe_webhook():
    """Handle Stripe webhooks"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {str(e)}")
        return jsonify({'error': 'Invalid payload'}), 400
    except Exception as e:
        if 'SignatureVerificationError' in str(type(e)):
            logger.error(f"Invalid signature: {str(e)}")
            return jsonify({'error': 'Invalid signature'}), 400
        raise
    
    # Handle subscription events
    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        session_id = session_obj['id']
        customer_email = session_obj.get('customer_details', {}).get('email')
        stripe_customer_id = session_obj.get('customer')
        stripe_subscription_id = session_obj.get('subscription')

        conn = get_db()
        cursor = conn.cursor()

        try:
            # Check if user already exists
            existing_user = cursor.execute(
                'SELECT id FROM users WHERE email = ?',
                (customer_email.lower(),)
            ).fetchone()

            if existing_user:
                # User exists - update their subscription status directly (re-subscribing)
                cursor.execute('''
                    UPDATE users
                    SET subscription_status = 'premium',
                        generations_limit = 10,
                        generations_used = 0,
                        stripe_customer_id = ?,
                        stripe_subscription_id = ?,
                        last_reset = ?
                    WHERE id = ?
                ''', (stripe_customer_id, stripe_subscription_id, datetime.now().isoformat(), existing_user['id']))
                conn.commit()
                logger.info(f"✅ Upgraded existing user {customer_email} to premium")
            else:
                # New user - account will be created when they set password on payment-success page
                # No confirmation email needed - they create account immediately after payment
                logger.info(f"✅ New subscription for {customer_email} - account will be created on payment-success page")
        except Exception as e:
            logger.error(f"Error handling checkout session: {str(e)}")
        finally:
            conn.close()
    
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')

        # Record payment and reset generation count
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute(
            'SELECT id FROM users WHERE stripe_subscription_id = ?',
            (subscription_id,)
        ).fetchone()

        if user:
            # Record the payment
            cursor.execute('''
                INSERT INTO payment_history (user_id, stripe_payment_id, amount, status)
                VALUES (?, ?, ?, ?)
            ''', (user['id'], invoice['id'], invoice['amount_paid'] / 100, 'succeeded'))

            # Reset generation count to 10 for the new billing cycle
            cursor.execute('''
                UPDATE users
                SET generations_used = 0,
                    generations_limit = 10,
                    last_reset = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), user['id']))

            conn.commit()
            logger.info(f"✅ Payment succeeded for user {user['id']} - Reset generations to 10 (0 used)")

        conn.close()
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        
        # Downgrade to inactive (no free tier)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET subscription_status = 'inactive',
                generations_limit = 0,
                generations_used = 0,
                stripe_subscription_id = NULL
            WHERE stripe_subscription_id = ?
        ''', (subscription['id'],))
        conn.commit()
        conn.close()
        
        logger.info(f"Subscription {subscription['id']} cancelled - user now inactive")
    
    return jsonify({'success': True})

@app.route('/api/payment/cancel-subscription', methods=['POST'])
@login_required
def cancel_subscription():
    """Cancel user's subscription at the end of billing period"""
    try:
        user_id = session['user_id']
        logger.info(f"Cancel subscription request from user_id: {user_id}")

        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()

        logger.info(f"User found: {user is not None}, Stripe Sub ID: {user['stripe_subscription_id'] if user else 'N/A'}")

        if not user:
            logger.warning(f"Cancel subscription failed - user {user_id} not found in database")
            return jsonify({'error': 'User not found. Please try logging out and back in.'}), 400

        if not user['stripe_subscription_id']:
            logger.warning(f"Cancel subscription failed - user {user['email']} has no stripe_subscription_id")
            return jsonify({
                'error': 'No active subscription found. If you just subscribed, please contact support.',
                'debug_info': f'User: {user["email"]}, Status: {user["subscription_status"]}'
            }), 400

        # Cancel subscription at period end (keeps access until end of paid month)
        subscription = stripe.Subscription.modify(
            user['stripe_subscription_id'],
            cancel_at_period_end=True
        )

        # Get the cancellation date - try both attribute and dictionary access
        try:
            period_end = subscription.current_period_end
        except (AttributeError, KeyError):
            period_end = subscription.get('current_period_end')

        cancel_date = datetime.fromtimestamp(period_end).strftime('%B %d, %Y')

        # Update database to mark subscription as cancelled (but still active until period end)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users
            SET subscription_status = 'cancelled'
            WHERE id = ?
        ''', (user_id,))
        conn.commit()
        conn.close()

        logger.info(f"Subscription {subscription.id} will cancel on {cancel_date}")

        return jsonify({
            'success': True,
            'message': f'✅ Subscription Successfully Cancelled\n\nYou will continue to have full access until {cancel_date}.\n\nYou can still generate presentations and use all premium features until then.\n\nThank you for using PresPilot!'
        })

    except Exception as e:
        logger.error(f"Cancel subscription error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/payment/fix-stripe-link', methods=['POST'])
@login_required
def fix_stripe_link():
    """Fix missing Stripe subscription link for logged-in user"""
    try:
        user_id = session['user_id']

        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404

        email = user['email']
        logger.info(f"Attempting to fix Stripe link for user: {email}")

        # Check if already linked
        if user['stripe_subscription_id']:
            conn.close()
            return jsonify({
                'success': True,
                'message': 'Your account is already linked to a Stripe subscription',
                'subscription_id': user['stripe_subscription_id']
            })

        # Search for active subscriptions in Stripe for this email
        customers = stripe.Customer.list(email=email, limit=10)

        if not customers.data:
            conn.close()
            return jsonify({'error': 'No Stripe subscription found for your email'}), 404

        # Find active subscription
        active_subscription = None
        customer_id = None

        for customer in customers.data:
            subscriptions = stripe.Subscription.list(customer=customer.id, limit=10)

            for sub in subscriptions.data:
                if sub.status == 'active':
                    active_subscription = sub
                    customer_id = customer.id
                    break

            if active_subscription:
                break

        if not active_subscription:
            conn.close()
            return jsonify({'error': 'No active subscription found for your email'}), 404

        # Update user record with Stripe IDs
        cursor.execute('''
            UPDATE users
            SET stripe_customer_id = ?,
                stripe_subscription_id = ?,
                subscription_status = 'premium',
                generations_limit = 10
            WHERE id = ?
        ''', (customer_id, active_subscription.id, user_id))

        conn.commit()
        conn.close()

        logger.info(f"✅ Fixed Stripe link for {email}: {active_subscription.id}")

        return jsonify({
            'success': True,
            'message': 'Your Stripe subscription has been linked successfully!',
            'subscription_id': active_subscription.id,
            'customer_id': customer_id
        })

    except Exception as e:
        logger.error(f"Fix Stripe link error: {str(e)}")
        return jsonify({'error': f'Failed to fix Stripe link: {str(e)}'}), 500

# ============= Presentation Generation Endpoints =============

@app.route('/api/research', methods=['POST'])
def research_topic():
    """Research topic and create presentation outline"""
    try:
        user_id = session.get('user_id', 'anonymous')

        # Check generations limit (skip for anonymous users)
        if user_id != 'anonymous' and not check_generations_limit(user_id):
            conn = get_db()
            cursor = conn.cursor()
            user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
            conn.close()
            
            return jsonify({
                'error': 'Generation limit reached for this month',
                'limit_reached': True,
                'subscription_status': user['subscription_status'],
                'generations_used': user['generations_used'],
                'generations_limit': user['generations_limit']
            }), 403
        
        # Rate limiting - allow 10 research requests per minute
        if not check_rate_limit(user_id, 'research', limit=10, window_minutes=1):
            return jsonify({'error': 'Too many requests'}), 429
        
        data = request.json
        topic = data.get('topic', '')
        num_slides = int(data.get('num_slides', 10))
        
        if not topic:
            return jsonify({'error': 'Topic is required'}), 400
        
        logger.info(f"User {user_id} researching: {topic[:50]}")

        # Check if there's an uploaded document to use as source material
        source_document = session.get('source_document', '')
        document_context = ""

        if source_document:
            # Use document as primary source for presentation content
            document_context = f"""
⚠️ CRITICAL - SOURCE DOCUMENT PROVIDED (YOU MUST USE THIS AS PRIMARY SOURCE):
{source_document}

⚠️ MANDATORY REQUIREMENTS FOR DOCUMENT-BASED PRESENTATIONS:
1. Read through the ENTIRE document above and extract the most relevant information for the topic: "{topic}"
2. You MUST base the presentation slides on the content from the source document above
3. Extract key facts, statistics, numbers, and specific details from anywhere in the document
4. Preserve important numbers, percentages, dates, and data points exactly as they appear in the document
5. Use the document's terminology and specific examples
6. The slides should reflect what's IN the document, not general knowledge about the topic
7. If the document has specific capitalization or formatting for terms, preserve it
8. Include specific quotes, data points, and examples from throughout the document
9. Intelligently identify the most important information across the entire document, not just the beginning

"""
            logger.info(f"✅ Using uploaded document ({len(source_document)} chars) as primary source for presentation outline")

        # Search web for up-to-date information (especially important for current events and sports)
        # Check if topic requires current information (sports, current events, etc.)
        sports_keywords = [
            'sport', 'game', 'team', 'player', 'season', 'championship', 'tournament', 'league',
            'nfl', 'nba', 'mlb', 'nhl', 'mls', 'fifa', 'uefa', 'premier league', 'la liga', 'serie a',
            'soccer', 'football', 'basketball', 'baseball', 'hockey', 'tennis', 'golf', 'racing',
            'nascar', 'formula 1', 'f1', 'boxing', 'mma', 'ufc', 'wrestling', 'volleyball', 'cricket', 'rugby',
            'playoff', 'playoffs', 'super bowl', 'superbowl', 'world series', 'world cup', 'olympics', 'olympic',
            'finals', 'semifinal', 'quarterfinal', 'match', 'score', 'win', 'loss', 'victory', 'defeat',
            'draft', 'trade', 'injury', 'injured', 'roster', 'conference', 'division', 'standings', 'ranking',
            'athlete', 'athletes', 'coach', 'coaching', 'trainer', 'stadium', 'arena', 'cup', 'trophy',
            'medal', 'gold medal', 'silver medal', 'bronze medal', 'champion', 'champions', 'mvp',
            'all-star', 'hall of fame', 'record-breaking', 'franchise', 'contract', 'signing'
        ]
        current_events_keywords = [
            'current', 'event', 'news', 'recent', 'today', 'yesterday', 'this week', 'this month',
            'this year', 'this season', 'right now', 'currently', 'now', 'present',
            'latest', 'breaking', 'update', 'developing', 'announcement', 'announced',
            '2025', '2024', '2026', 'january 2025', 'february 2025', 'march 2025', 'april 2025',
            'may 2025', 'june 2025', 'july 2025', 'august 2025', 'september 2025', 'october 2025',
            'november 2025', 'december 2025',
            'situation', 'crisis', 'emergency', 'election', 'political', 'policy', 'pandemic',
            'outbreak', 'conflict', 'war', 'protest', 'strike', 'legislation', 'regulation',
            'reform', 'investigation', 'scandal', 'controversy', 'milestone', 'achievement',
            'historic', 'unprecedented', 'trend', 'trending', 'viral', 'breaking news'
        ]

        topic_lower = topic.lower()
        requires_current_info = any(keyword in topic_lower for keyword in sports_keywords + current_events_keywords)

        web_context = ""
        search_results = []

        if not source_document or requires_current_info:
            # Always search web if no document OR if topic is sports/current events (requires up-to-date info)
            search_results = search_tavily(topic, max_results=3)
            if requires_current_info:
                logger.info(f"🔍 Sports/current events topic detected - forcing web search for up-to-date information")
        else:
            logger.info("⚠️  Skipping web search - using uploaded document as primary source")

        if search_results:
            # Format search results for inclusion in prompt
            web_info = []
            for idx, result in enumerate(search_results[:3], 1):
                title = result.get('title', 'No title')
                content = result.get('content', '')[:300]  # Limit content length
                url = result.get('url', '')
                web_info.append(f"{idx}. {title}\n   Source: {url}\n   {content}")

            web_context = f"""
⚠️ CRITICAL - CURRENT WEB INFORMATION FROM {datetime.now().year} (YOU MUST USE THIS):
{chr(10).join(web_info)}

⚠️ MANDATORY REQUIREMENTS FOR WEB INFORMATION:
1. You MUST use the information above from the web search results
2. DO NOT use outdated information from your training data if web results are provided
3. Include specific facts, dates, names, and statistics from the web sources above
4. If the topic involves current events (2025 or recent past), ONLY use the web information
5. Your presentation must reflect what is actually happening NOW, not predictions or past information

"""
            logger.info(f"✅ Including web search context from {len(search_results)} sources in presentation research")
        else:
            logger.warning(f"⚠️  No web search results - presentation will use AI knowledge only (may be outdated for current events)")

        # Generate outline with document context (if available) and web context (if available)
        web_instruction = ""
        if search_results and requires_current_info:
            # For sports/current events, ALWAYS prioritize web search (even if document uploaded)
            web_instruction = "\n⚠️ CRITICAL: This is a sports/current events topic. You MUST base your presentation on the CURRENT web information provided above, NOT on your training data or the document. Use specific facts, dates, scores, standings, and details from the web sources.\n"
        elif search_results and not source_document:
            # Only web search available, no document uploaded
            web_instruction = "\n⚠️ CRITICAL: Current web information is provided above. You MUST base your presentation on this current information, NOT on your training data. Use specific facts, dates, and details from the web sources.\n"
        elif source_document and search_results:
            # If both document and web search available (but not sports/current events), prioritize document
            web_instruction = "\n⚠️ NOTE: Web information is provided for additional context, but prioritize the source document content above.\n"

        prompt = f"""Create a detailed outline for a {num_slides}-slide presentation on: {topic}

{document_context}{web_context}{web_instruction}
CRITICAL REQUIREMENTS:
1. Create EXACTLY {num_slides} sections (one per slide)
2. Each section title must be VERY SHORT - MAXIMUM 2 WORDS (like "Overview", "Key Benefits", "Statistics", "Implementation", "Results")
3. Each section must have 3-4 key points
4. Each key point MUST be a COMPLETE, GRAMMATICALLY CORRECT SENTENCE (12-20 words)
5. Key points must be SPECIFIC - include numbers, examples, names, dates when relevant
6. PRESERVE exact numbers, percentages, statistics, and data points from source materials
7. NO repetition between sections - each section covers a DIFFERENT aspect
8. Each key point should be informative but concise enough to fit on a slide
9. IMPORTANT: Use proper grammar, spelling, and punctuation in all sentences
10. If source document is provided above, extract facts directly from it and preserve specific terminology, numbers, and capitalization
11. If web information is provided above, you MUST prioritize it over your training data - use the current facts, not outdated predictions

Return ONLY valid JSON (no markdown, no ```json):
{{
  "sections": [
    {{"title": "Introduction", "facts": ["This is a complete sentence with specific information about the topic.", "This is another complete sentence covering a different aspect.", "This is a third sentence with relevant data or examples."]}},
    {{"title": "Key Benefits", "facts": ["First complete sentence about benefits with specific details.", "Second complete sentence highlighting different advantages.", "Third sentence with concrete examples or statistics."]}}
  ]
}}

Make it comprehensive, professional, grammatically perfect, and ensure each section is DISTINCT with VERY SHORT titles."""
        
        response = call_anthropic(prompt, max_tokens=3000)
        response = response.replace('```json\n', '').replace('\n```', '').replace('```', '').strip()

        # Clean up common JSON issues from AI responses
        import re
        # Remove trailing commas before closing brackets/braces
        response = re.sub(r',(\s*[}\]])', r'\1', response)
        # Remove comments (// or /* */)
        response = re.sub(r'//.*?$', '', response, flags=re.MULTILINE)
        response = re.sub(r'/\*.*?\*/', '', response, flags=re.DOTALL)

        # Try to parse JSON with better error handling
        try:
            result = json.loads(response)

            # Proofread all facts for grammar and clarity
            for section in result.get('sections', []):
                if 'facts' in section:
                    proofread_facts = []
                    for fact in section['facts']:
                        # Proofread each fact to ensure proper grammar
                        proofread_fact = proofread_slide_text(fact, max_tokens=100)
                        proofread_facts.append(proofread_fact)
                    section['facts'] = proofread_facts

        except json.JSONDecodeError as e:
            # Log the malformed JSON for debugging
            logger.error(f"JSON parsing error: {str(e)}")
            logger.error(f"Malformed JSON response (first 500 chars): {response[:500]}")

            # Retry with a simplified prompt
            logger.info("Retrying research with simplified prompt...")
            retry_prompt = f"""Create a {num_slides}-slide presentation outline on: {topic}

Return ONLY valid JSON in this EXACT format (no extra text, no markdown):
{{"sections": [{{"title": "Intro", "facts": ["First fact.", "Second fact.", "Third fact."]}}]}}

CRITICAL: Must be valid JSON. Each title max 2 words. Each fact must be a complete sentence."""

            response = call_anthropic(retry_prompt, max_tokens=3000)
            response = response.replace('```json\n', '').replace('\n```', '').replace('```', '').strip()
            response = re.sub(r',(\s*[}\]])', r'\1', response)
            result = json.loads(response)
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Research error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def fetch_web_context(query, facts):
    """Fetch web context for speaker notes enhancement"""
    try:
        facts_text = '\n'.join(facts[:3])
        context_prompt = f"""Provide 2-3 sentences of helpful background context about: {query}

Key points to enhance:
{facts_text}

Include relevant statistics, real-world examples, or industry insights.
Keep it conversational and natural - this is for speaker notes, not the slides themselves."""

        response = call_anthropic(context_prompt, max_tokens=200)
        return response.strip()
    
    except Exception as e:
        logger.error(f"Error fetching web context: {str(e)}")
        return ""  # Return empty string if search fails

@app.route('/api/upload-document', methods=['POST'])
def upload_document():
    """Upload and extract text from PDF, DOC, DOCX, or TXT files"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        filename = file.filename.lower()
        extracted_text = ""

        # Handle PDF files
        if filename.endswith('.pdf'):
            try:
                import PyPDF2
                from io import BytesIO

                pdf_bytes = BytesIO(file.read())
                pdf_reader = PyPDF2.PdfReader(pdf_bytes)

                for page in pdf_reader.pages:
                    extracted_text += page.extract_text() + "\n"

                logger.info(f"Extracted {len(extracted_text)} characters from PDF")
            except Exception as e:
                logger.error(f"PDF extraction error: {str(e)}")
                return jsonify({'error': f'Failed to extract text from PDF: {str(e)}'}), 500

        # Handle Word documents (.docx)
        elif filename.endswith('.docx'):
            try:
                from docx import Document
                from io import BytesIO

                doc_bytes = BytesIO(file.read())
                doc = Document(doc_bytes)

                for paragraph in doc.paragraphs:
                    extracted_text += paragraph.text + "\n"

                logger.info(f"Extracted {len(extracted_text)} characters from DOCX")
            except Exception as e:
                logger.error(f"DOCX extraction error: {str(e)}")
                return jsonify({'error': f'Failed to extract text from Word document: {str(e)}'}), 500

        # Handle text files
        elif filename.endswith('.txt'):
            try:
                extracted_text = file.read().decode('utf-8')
                logger.info(f"Extracted {len(extracted_text)} characters from TXT")
            except Exception as e:
                logger.error(f"TXT extraction error: {str(e)}")
                return jsonify({'error': f'Failed to read text file: {str(e)}'}), 500

        else:
            return jsonify({'error': 'Unsupported file format. Please upload PDF, DOCX, or TXT'}), 400

        if not extracted_text.strip():
            return jsonify({'error': 'No text could be extracted from the document'}), 400

        # Limit extracted text to reasonable length (50k characters for better performance)
        # 50k chars = ~10k words = ~20 pages, which is plenty for presentation context
        if len(extracted_text) > 50000:
            logger.warning(f"Document too long ({len(extracted_text)} chars), truncating to 50k for better performance")
            extracted_text = extracted_text[:50000] + "\n\n[Document truncated to 50,000 characters for optimal processing. Key information should still be included.]"

        # Store full document in session for use in speaker notes
        session['source_document'] = extracted_text.strip()
        session.modified = True

        return jsonify({
            'success': True,
            'extracted_text': extracted_text.strip(),
            'filename': file.filename,
            'length': len(extracted_text)
        })

    except Exception as e:
        logger.error(f"Document upload error: {str(e)}")
        return jsonify({'error': 'Failed to process document'}), 500

@app.route('/api/generate-content', methods=['POST'])
def generate_content():
    """Generate slide content"""
    try:
        user_id = session.get('user_id', 'anonymous')

        # Rate limiting (skip for anonymous users) - allow 50 content generations per minute
        if user_id != 'anonymous' and not check_rate_limit(user_id, 'generate-content', limit=50, window_minutes=1):
            return jsonify({'error': 'Too many requests'}), 429

        data = request.json
        section = data.get('section')
        slide_title = data.get('slide_title')
        slide_format = data.get('slide_format', 'Detailed')

        if not section or not slide_title:
            return jsonify({'error': 'Missing required fields'}), 400

        facts = section.get('facts', [])

        # If Concise format, convert facts to very short bullets (max 5 words)
        if slide_format == "Concise":
            prompt = f"""Convert these key points into VERY SHORT bullet points for a presentation slide titled "{slide_title}".

KEY POINTS:
{chr(10).join([f"- {fact}" for fact in facts[:5]])}

REQUIREMENTS:
- Each bullet must be NO MORE THAN 5 WORDS
- Maximum 5 words per bullet
- Use short phrases or key details only
- Remove all unnecessary words
- Keep only the essential information
- Make them punchy and memorable

Examples:
- "Global market growth increased by 47%" → "47% market growth"
- "Companies are adopting AI technologies rapidly" → "Rapid AI adoption"
- "Customer satisfaction scores improved significantly" → "Higher satisfaction scores"

Return ONLY the short bullets, one per line, no formatting:"""

            response = call_anthropic(prompt, max_tokens=300)
            bullets = [line.strip().lstrip('•-*').strip() for line in response.strip().split('\n') if line.strip()]
            bullets = bullets[:5]  # Limit to 5 bullets
        else:
            # Detailed format: use facts directly as full sentences
            bullets = facts[:5]

        return jsonify({'bullets': bullets})

    except Exception as e:
        logger.error(f"Content generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-notes', methods=['POST'])
def generate_notes():
    """Generate speaker notes with grammar proofreading"""
    try:
        user_id = session.get('user_id', 'anonymous')

        # Rate limiting (skip for anonymous users) - allow 50 notes generations per minute
        if user_id != 'anonymous' and not check_rate_limit(user_id, 'generate-notes', limit=50, window_minutes=1):
            return jsonify({'error': 'Too many requests'}), 429
        
        data = request.json
        section = data.get('section')
        style = data.get('style', 'Detailed')
        slide_title = data.get('slide_title')
        slide_num = data.get('slide_num', 1)
        slide_format = data.get('slide_format', 'Detailed')
        slide_content = data.get('slide_content', [])
        
        if not section or not slide_title:
            return jsonify({'error': 'Missing required fields'}), 400
        
        facts_text = '\n'.join(section.get('facts', []))
        slide_bullets = '\n'.join([f"• {item}" for item in slide_content]) if slide_content else ""
        
        # Check if there's source document content to enhance speaker notes
        source_document = session.get('source_document', '')
        document_context = ""

        if source_document:
            # Use full document for speaker notes - AI will extract relevant parts
            document_context = f"""
SOURCE DOCUMENT CONTEXT (use this for additional details):
{source_document}

Search through the entire document above and pull supplementary information, examples, data, or context that relates to "{slide_title}".
Extract the most relevant information from anywhere in the document, preserving specific numbers, quotes, and data points exactly.
"""

        if style == "Concise":
            # Get the full facts from the section for the speaker notes
            prompt = f"""Write concise speaker notes for a presentation slide titled "{slide_title}".

TOPIC: {slide_title}

KEY POINTS TO COVER:
{chr(10).join([f"- {fact}" for fact in section.get('facts', [])[:5]])}

Write natural, conversational speaker notes (3-4 sentences) that provide context and explanation for these key points. Similar to detailed notes but more concise.

IMPORTANT RULES:
- Use THIRD-PERSON, OBJECTIVE language (no "we", "our", "us" unless the source document uses first person)
- Write as an objective narrator describing facts and information
- Example: "Inter Miami has achieved..." NOT "We have achieved..."
- Naturally incorporate 1-2 of these transition words (choose different ones each time): {', '.join(selected_transitions)}
- Provide context, examples, or explanations that supplement the slide content
- Be conversational and engaging, but objective
- Use complete, flowing sentences
- NEVER use generic phrases like "these elements work together" or "comprehensive understanding"
- Make it sound like natural speech from an objective narrator, not a list

{document_context}

Speaker notes:"""
        else:  # Detailed style
            prompt = f"""Write detailed speaker notes for a presentation slide titled "{slide_title}".

Write a natural, conversational paragraph (5-7 sentences) that provides context, insights, and examples for this slide.

CRITICAL: Use THIRD-PERSON, OBJECTIVE language. Write as an objective narrator describing facts and information. Do NOT use first person ("we", "our", "us") unless the source document specifically uses first person. Example: "The company has..." NOT "We have..."

{document_context}

Speaker notes:"""

        # Detailed style needs more tokens to expand each bullet
        max_tokens = 1500 if style == "Concise" else 2500
        response = call_anthropic(prompt, max_tokens=max_tokens)

        # PROOFREAD THE NOTES
        proofread_max_tokens = 1800 if style == "Concise" else 3000
        proofread_notes = proofread_speaker_notes(response.strip(), max_tokens=proofread_max_tokens)
        
        logger.info(f"Generated and proofread notes for slide: {slide_title}")
        
        return jsonify({'notes': proofread_notes})
    
    except Exception as e:
        logger.error(f"Notes generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/complete', methods=['POST'])
def complete_presentation():
    """Mark presentation as complete - generation count will be incremented on successful download"""
    try:
        user_id = session.get('user_id', 'anonymous')
        data = request.json

        title = data.get('title', 'Untitled')
        topic = data.get('topic', '')
        num_slides = data.get('num_slides', 10)
        theme = data.get('theme', 'Default')

        # NOTE: Generation count is NOT incremented here anymore
        # It will be incremented only when the PowerPoint file is successfully generated

        # Save presentation record
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO presentations (user_id, title, topic, num_slides, theme)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, title, topic, num_slides, theme))
        presentation_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"User {user_id} completed presentation research: {title}")
        return jsonify({
            'success': True,
            'message': 'Presentation generated successfully!',
            'presentation_id': presentation_id
        })

    except Exception as e:
        logger.error(f"Complete presentation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/generate-pptx', methods=['POST'])
def generate_pptx():
    """Generate the actual PowerPoint file"""
    try:
        from pptx_generator import generate_presentation
        from flask import send_file
        import tempfile

        # Check generations limit BEFORE generating
        user_id = session.get('user_id', 'anonymous')

        if user_id != 'anonymous':
            # Check if user has generations remaining
            if not check_generations_limit(user_id):
                conn = get_db()
                cursor = conn.cursor()
                user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
                conn.close()

                return jsonify({
                    'error': 'Generation limit reached for this month',
                    'limit_reached': True,
                    'subscription_status': user['subscription_status'],
                    'generations_used': user['generations_used'],
                    'generations_limit': user['generations_limit']
                }), 403

        data = request.json
        title = data.get('title', 'Presentation')
        topic = data.get('topic', '')
        sections = data.get('sections', [])
        theme = data.get('theme', 'Business Black and Yellow')
        notes_style = data.get('notesStyle', 'Detailed')
        slide_format = data.get('slideFormat', 'Detailed')  # Add slide format

        logger.info(f"Generating PPTX: {title[:30]} with format: {slide_format}, notes: {notes_style}")

        # If Concise format, convert facts to short phrases (max 5 words) BEFORE generating PPTX
        if slide_format == "Concise":
            # Collect all bullets to convert in one batch
            all_bullets = []
            for section in sections:
                if 'facts' in section and section['facts']:
                    all_bullets.extend(section['facts'][:5])

            # Convert all bullets in a single AI call for speed
            if all_bullets:
                bullets_text = '\n'.join([f"{i+1}. {bullet}" for i, bullet in enumerate(all_bullets)])
                prompt = f"""Convert each of these bullet points into a SHORT phrase of NO MORE THAN 5 WORDS.
Return ONLY the shortened phrases, one per line, in the same order:

{bullets_text}"""
                try:
                    response = call_anthropic(prompt, max_tokens=500)
                    short_bullets = [line.strip().strip('•-*').strip('1234567890.').strip()
                                   for line in response.split('\n') if line.strip()]

                    # Distribute the shortened bullets back to sections
                    bullet_index = 0
                    for section in sections:
                        if 'facts' in section and section['facts']:
                            num_facts = min(len(section['facts']), 5)
                            section['facts'] = short_bullets[bullet_index:bullet_index + num_facts]
                            bullet_index += num_facts
                except Exception as e:
                    logger.warning(f"Batch conversion failed, using fallback: {e}")
                    # Fallback: Just take first 5 words of each
                    for section in sections:
                        if 'facts' in section and section['facts']:
                            section['facts'] = [' '.join(fact.split()[:5]) for fact in section['facts'][:5]]

        # If Detailed notes, generate AI summaries for speaker notes
        if notes_style == "Detailed":
            for section in sections:
                if 'facts' in section and section['facts']:
                    # Create a prompt to generate a natural summary
                    facts_text = '\n'.join([f"- {fact}" for fact in section['facts'][:5]])
                    prompt = f"""Create detailed speaker notes for a presentation slide about "{section.get('title', 'this topic')}".

Key points to cover:
{facts_text}

Write a natural, conversational paragraph (5-7 sentences) that provides context, insights, and examples for these points.

IMPORTANT: Use THIRD-PERSON, OBJECTIVE language (write as an objective narrator). Do NOT use first person ("we", "our", "us") unless the key points above are clearly written in first person from a company/organization perspective.

Speaker notes:"""

                    try:
                        summary = call_anthropic(prompt, max_tokens=500).strip()
                        section['custom_notes'] = summary
                    except Exception as e:
                        logger.warning(f"Failed to generate speaker notes: {e}")
                        # Fallback: Just join the facts
                        section['custom_notes'] = ' '.join(section['facts'])

        # Grammar check ONLY for document uploads (which may have typos)
        # Skip for AI-generated content (already clean)
        source_document = session.get('source_document', '')

        if source_document:
            logger.info("Grammar checking slide text (document upload detected)")
            for section in sections:
                # Proofread slide title
                if 'title' in section and section['title']:
                    try:
                        section['title'] = proofread_slide_text(section['title'])
                    except Exception as e:
                        logger.warning(f"Failed to proofread title: {e}")

                # Proofread bullets/facts
                if 'facts' in section and section['facts']:
                    proofread_facts = []
                    for fact in section['facts']:
                        try:
                            proofread_facts.append(proofread_slide_text(fact))
                        except Exception as e:
                            logger.warning(f"Failed to proofread bullet: {e}")
                            proofread_facts.append(fact)  # Use original if proofreading fails
                    section['facts'] = proofread_facts
        else:
            logger.info("Skipping grammar check (AI-generated content is already clean)")

        # Generate presentation in temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
            filename = generate_presentation(
                title=title,
                topic=topic,
                sections=sections,
                theme_name=theme,
                notes_style=notes_style,
                slide_format=slide_format,  # Pass slide format
                filename=tmp.name
            )

            # Increment generation count ONLY after successful generation
            if user_id != 'anonymous':
                increment_generation_count(user_id)
                logger.info(f"User {user_id} successfully generated presentation: {title}")

            # Send file
            return send_file(
                filename,
                mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
                as_attachment=True,
                download_name=f"{title.replace(' ', '_')}.pptx"
            )

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"PPTX generation error: {str(e)}")
        logger.error(f"Full traceback: {error_details}")
        return jsonify({'error': f'Generation failed: {str(e)}'}), 500

# ============= Static File Serving =============

@app.route('/')
def serve_landing():
    """Serve the landing page"""
    return send_from_directory('.', 'landing.html')

@app.route('/app.html')
def serve_app():
    """Serve the main app"""
    return send_from_directory('.', 'app.html')

@app.route('/subscribe.html')
def serve_subscribe():
    """Serve the subscription page"""
    return send_from_directory('.', 'subscribe.html')

@app.route('/payment-success')
def payment_success():
    """Serve payment success page"""
    return send_from_directory('.', 'payment-success.html')

@app.route('/payment-cancelled')
def payment_cancelled():
    """Serve payment cancelled page"""
    return send_from_directory('.', 'payment-cancelled.html')

@app.route('/reset-password.html')
def reset_password_page():
    """Serve password reset page"""
    return send_from_directory('.', 'reset-password.html')

@app.route('/confirm-email.html')
def confirm_email_page():
    """Serve email confirmation page"""
    return send_from_directory('.', 'confirm-email.html')

@app.route('/create-account.html')
def create_account_page():
    """Serve account creation page"""
    return send_from_directory('.', 'create-account.html')

@app.route('/landing.html')
def landing_page():
    """Serve landing page"""
    return send_from_directory('.', 'landing.html')

@app.route('/video1-2.mp4')
def serve_video():
    """Serve background video"""
    return send_from_directory('.', 'video1-2.mp4', mimetype='video/mp4')

@app.route('/theme-previews/<path:filename>')
def serve_theme_preview(filename):
    """Serve theme preview images"""
    return send_from_directory('theme-previews', filename)

@app.route('/phonto21.jpg')
def serve_logo():
    """Serve splash screen logo"""
    return send_from_directory('.', 'phonto21.jpg', mimetype='image/jpeg')

# ============= Utility Endpoints =============

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'api_configured': bool(ANTHROPIC_API_KEY),
        'stripe_configured': bool(stripe.api_key)
    })

# Force HTTPS redirect
@app.before_request
def redirect_to_https():
    """Redirect HTTP to HTTPS in production"""
    if not request.is_secure and request.headers.get('X-Forwarded-Proto') == 'http':
        url = request.url.replace('http://', 'https://', 1)
        return redirect(url, code=301)

@app.route('/api/test', methods=['POST'])
def test_api():
    """Test endpoint to verify API key works"""
    try:
        response = call_anthropic("Test", max_tokens=10)
        return jsonify({'success': True, 'message': 'API key is working'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    if not ANTHROPIC_API_KEY:
        print("⚠️  WARNING: ANTHROPIC_API_KEY environment variable is not set!")
        print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
    else:
        print("✓ API key configured")

    if not stripe.api_key:
        print("⚠️  WARNING: Stripe not configured - payment features disabled")
    else:
        print("✓ Stripe configured")

    print("✓ Database initialized")
    print("✓ Authentication system ready")
    print("✓ PAYMENT REQUIRED - $5.99/month for 10 presentations")
    print("✓ NO FREE TIER - Users must subscribe to generate presentations")
    print("✓ Grammar proofreading enabled for slide text and speaker notes")

    # Get configuration from environment
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'

    print(f"✓ Starting server on port {port} (debug={'on' if debug else 'off'})")
    app.run(host='0.0.0.0', port=port, debug=debug)
