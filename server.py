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
from sendgrid.helpers.mail import Mail, Email, To, Content

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

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

# SendGrid configuration
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
SENDGRID_FROM_EMAIL = os.environ.get('SENDGRID_FROM_EMAIL', 'noreply@prespilot.com')

if not SENDGRID_API_KEY:
    logger.warning("⚠️  SENDGRID_API_KEY not configured - email features disabled")
else:
    logger.info("✅ SendGrid configured")

# Database initialization
DB_PATH = 'slidegen.db'

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
            token_expires_at TIMESTAMP,
            email_verified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            account_created INTEGER DEFAULT 0
        )
    ''')

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

def send_confirmation_email(to_email, confirmation_token):
    """Send email confirmation with token link"""
    if not SENDGRID_API_KEY:
        logger.error("SendGrid not configured - cannot send email")
        return False

    try:
        confirmation_url = f"{request.host_url}confirm-email.html?token={confirmation_token}"

        message = Mail(
            from_email=Email(SENDGRID_FROM_EMAIL),
            to_emails=To(to_email),
            subject='Confirm Your PresPilot Account',
            html_content=f'''
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #f59e0b;">Welcome to PresPilot!</h2>
                <p>Thank you for subscribing. Please confirm your email and create your password to get started.</p>
                <p><a href="{confirmation_url}" style="background: #f59e0b; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Confirm Email & Create Password</a></p>
                <p style="color: #666; font-size: 14px;">This link will expire in 24 hours.</p>
                <p style="color: #666; font-size: 14px;">If you didn't request this, please ignore this email.</p>
            </div>
            '''
        )

        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Confirmation email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
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
        
        if not user or user['subscription_status'] != 'premium':
            return jsonify({
                'error': 'Active subscription required',
                'subscription_required': True,
                'subscription_status': user['subscription_status'] if user else 'inactive'
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function

def check_generations_limit(user_id):
    """Check if user has generations available"""
    conn = get_db()
    cursor = conn.cursor()
    
    user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    if not user:
        return False
    
    # Only premium users can generate
    if user['subscription_status'] != 'premium':
        return False
    
    # Check if we need to reset monthly limit
    last_reset = datetime.fromisoformat(user['last_reset']) if user['last_reset'] else None
    now = datetime.now()
    
    # Reset monthly if it's a new month
    if not last_reset or (now.year > last_reset.year or now.month > last_reset.month):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET generations_used = 0, last_reset = ? 
            WHERE id = ?
        ''', (now.isoformat(), user_id))
        conn.commit()
        conn.close()
        return True
    
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
        prompt = f"""You are a professional editor proofreading slide text for a presentation.

ORIGINAL SLIDE TEXT:
{slide_text}

TASK: Thoroughly proofread and correct this slide text to ensure it is grammatically perfect, clear, and concise.

FIX ALL OF THE FOLLOWING:
1. **Grammar errors** - Subject-verb agreement, tense consistency, pronoun usage, etc.
2. **Spelling mistakes** - Any typos or misspelled words
3. **Punctuation errors** - Commas, periods, semicolons, apostrophes, quotation marks
4. **Sentence structure** - Run-on sentences, fragments, awkward constructions
5. **Word choice** - Replace awkward or unclear wording with better, more concise alternatives
6. **Clarity issues** - Make sure the text is clear and easy to understand at a glance

MAINTAIN:
- The same general length and brevity (slide text should be concise)
- The core meaning and information
- Professional tone appropriate for presentations
- Bullet point or phrase structure (don't turn it into full sentences if it wasn't)

OUTPUT: Return ONLY the corrected text with no explanations, comments, or labels. Keep it concise and slide-appropriate.

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
        password_hash = hash_password(password)
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
        
        if not user or user['password_hash'] != hash_password(password):
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
        if pending.get('email_verified'):
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
        if not pending.get('email_verified'):
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
                # Get preview images, prioritizing title.png first
                previews = []
                title_preview = None

                for file in sorted(os.listdir(theme_path)):
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        file_path = f'/{theme_dir}/{theme_name}/{file}'
                        if file.lower() in ['title.png', 'title.jpg', 'title.jpeg']:
                            title_preview = file_path
                        else:
                            previews.append(file_path)

                # Put title.png first if it exists
                if title_preview:
                    previews.insert(0, title_preview)

                if previews:  # Only include themes with preview images
                    themes.append({
                        'name': theme_name,
                        'previews': previews
                    })

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
            success_url=request.host_url + 'payment-success.html?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'landing.html',
            customer_email=None,  # Let Stripe collect email
            allow_promotion_codes=True,
        )

        return jsonify({'url': checkout_session.url, 'sessionId': checkout_session.id})

    except Exception as e:
        logger.error(f"Checkout session error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/payment/webhook', methods=['POST'])
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
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {str(e)}")
        return jsonify({'error': 'Invalid signature'}), 400
    
    # Handle subscription events
    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        session_id = session_obj['id']
        customer_email = session_obj.get('customer_details', {}).get('email')
        stripe_customer_id = session_obj.get('customer')
        stripe_subscription_id = session_obj.get('subscription')

        # Generate confirmation token and expiration (24 hours)
        confirmation_token = secrets.token_urlsafe(32)
        token_expires_at = datetime.utcnow() + timedelta(hours=24)

        # Store pending subscription - account will be created after email confirmation
        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO pending_subscriptions
                (session_id, customer_email, stripe_customer_id, stripe_subscription_id,
                 confirmation_token, token_expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (session_id, customer_email, stripe_customer_id, stripe_subscription_id,
                  confirmation_token, token_expires_at))
            conn.commit()
            logger.info(f"Stored pending subscription for {customer_email} with confirmation token")

            # Send confirmation email
            email_sent = send_confirmation_email(customer_email, confirmation_token)
            if email_sent:
                logger.info(f"✅ Confirmation email sent to {customer_email}")
            else:
                logger.error(f"❌ Failed to send confirmation email to {customer_email}")
        except Exception as e:
            logger.error(f"Error storing pending subscription: {str(e)}")
        finally:
            conn.close()
    
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        
        # Record payment
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute(
            'SELECT id FROM users WHERE stripe_subscription_id = ?', 
            (subscription_id,)
        ).fetchone()
        
        if user:
            cursor.execute('''
                INSERT INTO payment_history (user_id, stripe_payment_id, amount, status)
                VALUES (?, ?, ?, ?)
            ''', (user['id'], invoice['id'], invoice['amount_paid'] / 100, 'succeeded'))
            conn.commit()
        
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
    """Cancel user's subscription"""
    try:
        user_id = session['user_id']
        
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        
        if not user or not user['stripe_subscription_id']:
            return jsonify({'error': 'No active subscription'}), 400
        
        # Cancel in Stripe
        stripe.Subscription.delete(user['stripe_subscription_id'])
        
        # Update database to inactive (no free tier)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET subscription_status = 'inactive',
                generations_limit = 0,
                stripe_subscription_id = NULL
            WHERE id = ?
        ''', (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Subscription cancelled. Resubscribe anytime to continue creating presentations.'})
    
    except Exception as e:
        logger.error(f"Cancel subscription error: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
        
        # Generate outline
        prompt = f"""Create a detailed outline for a {num_slides}-slide presentation on: {topic}

CRITICAL REQUIREMENTS:
1. Create EXACTLY {num_slides} sections (one per slide)
2. Each section title must be VERY SHORT - MAXIMUM 2 WORDS (like "Overview", "Key Benefits", "Statistics", "Implementation", "Results")
3. Each section must have 3-4 key points
4. Each key point MUST be a COMPLETE SENTENCE (12-20 words)
5. Key points must be SPECIFIC - include numbers, examples, names, dates when relevant
6. NO repetition between sections - each section covers a DIFFERENT aspect
7. Each key point should be informative but concise enough to fit on a slide

Return ONLY valid JSON (no markdown, no ```json):
{{
  "sections": [
    {{"title": "Introduction", "facts": ["This is a complete sentence with specific information about the topic.", "This is another complete sentence covering a different aspect.", "This is a third sentence with relevant data or examples."]}},
    {{"title": "Key Benefits", "facts": ["First complete sentence about benefits with specific details.", "Second complete sentence highlighting different advantages.", "Third sentence with concrete examples or statistics."]}}
  ]
}}

Make it comprehensive, professional, and ensure each section is DISTINCT with VERY SHORT titles."""
        
        response = call_anthropic(prompt, max_tokens=3000)
        response = response.replace('```json\n', '').replace('\n```', '').replace('```', '').strip()

        # Clean up common JSON issues from AI responses
        import re
        # Remove trailing commas before closing brackets/braces
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

        # Limit extracted text to reasonable length (100k characters)
        if len(extracted_text) > 100000:
            extracted_text = extracted_text[:100000] + "\n\n[Document truncated due to length]"

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
            # Extract relevant excerpts from source document for this slide
            doc_excerpt = source_document[:3000]  # Use first 3000 chars as context
            document_context = f"""
SOURCE DOCUMENT CONTEXT (use this for additional details):
{doc_excerpt}

Pull supplementary information, examples, data, or context from the source document above that relates to "{slide_title}".
"""

        if style == "Concise":
            # Get the full facts from the section for the speaker notes
            prompt = f"""Write concise speaker notes for a presentation slide titled "{slide_title}".

TOPIC: {slide_title}

KEY POINTS TO COVER:
{chr(10).join([f"- {fact}" for fact in section.get('facts', [])[:5]])}

Write natural, conversational speaker notes (3-4 sentences) that provide context and explanation for these key points. Similar to detailed notes but more concise.

IMPORTANT RULES:
- Naturally incorporate 1-2 of these transition words (choose different ones each time): {', '.join(selected_transitions)}
- Provide context, examples, or explanations that supplement the slide content
- Be conversational and engaging
- Use complete, flowing sentences
- NEVER use generic phrases like "these elements work together" or "comprehensive understanding"
- Make it sound like natural speech, not a list

{document_context}

Speaker notes:"""
        else:  # Detailed style
            prompt = f"""Write detailed speaker notes for a presentation slide titled "{slide_title}".

Write a natural, conversational paragraph (5-7 sentences) that provides context, insights, and examples for this slide.

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

Speaker notes:"""

                    try:
                        summary = call_anthropic(prompt, max_tokens=500).strip()
                        section['custom_notes'] = summary
                    except Exception as e:
                        logger.warning(f"Failed to generate speaker notes: {e}")
                        # Fallback: Just join the facts
                        section['custom_notes'] = ' '.join(section['facts'])

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
            user_id = session.get('user_id', 'anonymous')
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
        logger.error(f"PPTX generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ============= Static File Serving =============

@app.route('/')
def serve_landing():
    """Serve the landing page"""
    return send_from_directory('.', 'landing.html')

@app.route('/app.html')
def serve_app():
    """Serve the main app"""
    return send_from_directory('.', 'app.html')

@app.route('/payment-success')
def payment_success():
    """Serve payment success page"""
    return send_from_directory('.', 'payment-success.html')

@app.route('/payment-cancelled')
def payment_cancelled():
    """Serve payment cancelled page"""
    return send_from_directory('.', 'payment-cancelled.html')

@app.route('/theme-previews/<path:filename>')
def serve_theme_preview(filename):
    """Serve theme preview images"""
    return send_from_directory('theme-previews', filename)

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
    print("✓ Grammar proofreading enabled for speaker notes")

    # Get configuration from environment
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'

    print(f"✓ Starting server on port {port} (debug={'on' if debug else 'off'})")
    app.run(host='0.0.0.0', port=port, debug=debug)
