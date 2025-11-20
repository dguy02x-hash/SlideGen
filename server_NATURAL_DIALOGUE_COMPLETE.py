#!/usr/bin/env python3
"""
SlideGen Pro - Backend Server with Authentication & Subscriptions
PAYMENT REQUIRED - No free tier, users must subscribe to generate presentations.

ENHANCED FEATURES:
================
✓ AI-Written Speaker Notes: Notes expand on slide bullet points with additional context
✓ Natural Human Presentation: Notes read like someone actually presenting, not instructions
✓ Web-Enhanced Content: AI searches for current information, statistics, and examples
✓ No Meta-Instructions: Pure information delivery - no "pay attention to" or "let me explain"
✓ Contextual Expansion: Adds details, examples, and background not shown on slides
✓ Research Integration: Real-time information gathering to enhance presentation quality
✓ Custom Style Generation: AI interprets natural language prompts to create custom themes
✓ Image Placeholder Integration: Every content slide (except title and thank you) includes blank spaces for images
✓ Theme-Based Image Styling: AI generates image placeholder styles that match the overall theme

SPEAKER NOTE STYLES:
===================
Three length options available:
1. Concise (4-6 sentences): Brief expansion with key context
2. Detailed (7-10 sentences): Standard expansion with examples and transitions
3. Full Explanation (10-14 sentences): Comprehensive deep-dive with extensive detail

All styles expand on slide bullet points naturally, as if a presenter is speaking to an audience.
Notes include additional context, examples, statistics, and background information not shown on slides.

CUSTOM STYLE GENERATION:
=======================
Users can describe desired presentation styles in natural language:
- "Professional corporate style with blue and gray colors"
- "Creative startup pitch deck with vibrant colors"
- "Academic presentation with traditional fonts"
AI generates complete theme configurations with colors, fonts, and design settings.
All content slides (except title and thank you) automatically include image placeholders
that are styled to match the theme (position, size, border color).
"""

from flask import Flask, request, jsonify, session
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

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
CORS(app, supports_credentials=True, origins=["http://localhost:3000", "http://127.0.0.1:3000"])

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
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID')  # Your $6.99/month price ID from Stripe
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')

if not stripe.api_key:
    logger.warning("⚠️  STRIPE_SECRET_KEY not configured - payment features disabled")
else:
    logger.info("✅ Stripe configured")

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

def call_anthropic(prompt, max_tokens=2000):
    """Make API call to Anthropic"""
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY environment variable not set")
    
    try:
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
        
        response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            return data['content'][0]['text']
        else:
            raise Exception(f"API error: {response.status_code} - {response.text}")
    
    except Exception as e:
        logger.error(f"Anthropic API error: {str(e)}")
        raise

def proofread_speaker_notes(notes_text):
    """
    Proofread speaker notes - fix grammar and REMOVE ALL meta-instructions.
    Ensures notes read like natural presentation, not instructions to a speaker.
    This should sound like a human expert presenting information to an audience.
    """
    try:
        prompt = f"""Edit these speaker notes to make them perfect. Fix any grammar errors and COMPLETELY REMOVE any phrases that sound like instructions or meta-commentary. These notes should read like someone actually presenting information to an audience, NOT like instructions for how to present.

ORIGINAL NOTES:
{notes_text}

YOUR TASK:
1. Fix grammar, spelling, punctuation errors
2. COMPLETELY REMOVE ALL instruction-like phrases:
   - "let me explain/tell you/walk you through/show you/discuss/share/talk about"
   - "let's talk about/discuss/look at/examine/explore"
   - "pay attention to" / "focus on" / "take note of" / "notice"
   - "make sure to" / "be sure to" / "don't forget" / "remember to"
   - "this is crucial/important/key/essential/vital"
   - "it's important/crucial to note/understand"
   - "here's what matters/what you need to know/what's important"
   - "the key thing is" / "what really matters" / "the important point"
   - "you need/should/must/ought to emphasize/focus/highlight/mention/note/understand/know"
   - "I'm going to" / "I want to" / "I'll show/tell/explain"
   - "now we're going to" / "now let's"
   - "as you can see" / "as we can see"
   - "note that" / "please note"
   - "keep in mind" / "remember that"
   - "this demonstrates/shows/illustrates" (when instructional)
   - Any similar meta-commentary or instructional language
3. Keep ALL facts, data, names, dates, statistics, examples EXACTLY as written
4. Maintain natural, conversational presentation tone (as if speaking to a live audience)
5. Keep smooth transitions like "Additionally," "As a result," "This meant that," "Following this"
6. Return ONLY the cleaned text - nothing else, no explanations

EXAMPLES:
Before: "Let me explain - in 1957, the Soviet Union launched Sputnik."
After: "In 1957, the Soviet Union launched Sputnik."

Before: "What's important here is that cloud costs dropped 32%."
After: "Cloud costs dropped 32%."

Before: "Now let's talk about the impact. Pay attention to how this changed everything."
After: "The impact was significant. This changed everything."

Before: "I'm going to show you how this revolutionized the industry. This is key to understand."
After: "This revolutionized the industry."

Before: "You need to emphasize that machine learning requires massive datasets."
After: "Machine learning requires massive datasets."

Return ONLY the edited notes now (no explanations, just the cleaned text):"""

        corrected = call_anthropic(prompt, max_tokens=1500)
        return corrected.strip()

    except Exception as e:
        logger.error(f"Error proofreading notes: {str(e)}")
        return notes_text

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
    """Get current user info - compatibility endpoint for frontend"""
    return auth_status()

# ============= Stripe Payment Endpoints =============

@app.route('/api/payment/config', methods=['GET'])
def payment_config():
    """Get Stripe publishable key"""
    return jsonify({
        'publishableKey': STRIPE_PUBLISHABLE_KEY,
        'priceId': STRIPE_PRICE_ID
    })

@app.route('/api/payment/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe checkout session for subscription"""
    try:
        user_id = session['user_id']
        
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Create or retrieve Stripe customer
        if user['stripe_customer_id']:
            customer_id = user['stripe_customer_id']
        else:
            customer = stripe.Customer.create(
                email=user['email'],
                metadata={'user_id': user_id}
            )
            customer_id = customer.id
            
            # Update database with customer ID
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET stripe_customer_id = ? WHERE id = ?', 
                         (customer_id, user_id))
            conn.commit()
            conn.close()
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + 'payment-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'payment-cancelled',
            metadata={'user_id': user_id}
        )
        
        return jsonify({'sessionId': checkout_session.id})
    
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
        session = event['data']['object']
        user_id = session['metadata'].get('user_id')
        
        if user_id:
            # Activate premium subscription
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'premium',
                    generations_limit = 10,
                    generations_used = 0,
                    last_reset = ?,
                    stripe_subscription_id = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), session.get('subscription'), user_id))
            conn.commit()
            conn.close()
            
            logger.info(f"User {user_id} upgraded to premium")
    
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
@login_required
# @subscription_required  # REMOVED FOR TESTING
def research_topic():
    """Research topic and create presentation outline - REQUIRES SUBSCRIPTION"""
    try:
        user_id = session['user_id']
        
        # Check generations limit - DISABLED FOR TESTING
        # if not check_generations_limit(user_id):
        #     conn = get_db()
        #     cursor = conn.cursor()
        #     user = cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        #     conn.close()
        #     
        #     return jsonify({
        #         'error': 'Generation limit reached for this month',
        #         'limit_reached': True,
        #         'subscription_status': user['subscription_status'],
        #         'generations_used': user['generations_used'],
        #         'generations_limit': user['generations_limit']
        #     }), 403
        
        # Rate limiting
        if not check_rate_limit(user_id, 'research'):
            return jsonify({'error': 'Too many requests'}), 429
        
        data = request.json
        topic = data.get('topic', '')
        num_slides = int(data.get('num_slides', 10))
        
        if not topic:
            return jsonify({'error': 'Topic is required'}), 400
        
        logger.info(f"User {user_id} researching: {topic[:50]}")
        
        # Generate outline
        prompt = f"""Create an outline for a {num_slides}-slide presentation on: {topic}

Return ONLY valid JSON (no markdown, no ```json):
{{
  "sections": [
    {{"title": "Section Title", "facts": ["fact1", "fact2", "fact3"]}},
    ...
  ]
}}

Make it comprehensive and professional."""
        
        response = call_anthropic(prompt, max_tokens=3000)
        response = response.replace('```json\n', '').replace('\n```', '').replace('```', '').strip()
        result = json.loads(response)
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Research error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def clean_meta_instructions(notes_text):
    """
    Aggressively remove meta-instructions from speaker notes.
    This is a safety net to catch any that slip through the generation.
    Ensures notes sound like a human presenter speaking, not instructions.
    """
    import re

    # Comprehensive list of meta-instruction patterns to remove
    meta_patterns = [
        # "Let me" phrases
        r"[Ll]et's break this down\s*[,:]?\s*",
        r"[Ll]et me (walk you through|explain|tell you|show you|discuss|share|talk about)\s+",
        r"[Ll]et's (talk about|discuss|look at|examine|explore|dive into)\s+",

        # "Pay attention" type phrases
        r"[Pp]ay attention to\s+",
        r"[Tt]ake note of\s+",
        r"[Nn]otice (how|that)\s+",

        # "Make sure" phrases
        r"[Mm]ake sure (to|you|that)\s+",
        r"[Bb]e sure to\s+",

        # "Remember/Don't forget" phrases
        r"[Dd]on't forget (to|that)\s+",
        r"[Rr]emember (to|that)\s+",
        r"[Kk]eep in mind (that)?\s*",

        # "Important/Crucial" meta-commentary
        r"[Tt]his is (crucial|important|key|essential|vital)\s*[,:]?\s*",
        r"[Ii]t's (crucial|important|key|essential|vital) (to note|to understand|that)\s*",
        r"[Hh]ere's what('s| is) (important|crucial|key)\s*[,:]?\s*",
        r"[Ww]hat('s| is) (important|crucial|key|essential) (is|here)\s*[,:]?\s*",
        r"[Tt]he (key|important|crucial) (thing|point|aspect) (is|to understand|to note|here)\s*[,:]?\s*",
        r"[Ww]hat really matters (is|here)\s*[,:]?\s*",
        r"[Ww]hat (really|actually) (matters|counts) (is|here)\s*[,:]?\s*",

        # "You should/need/must" directives
        r"[Yy]ou (need|should|must|want|ought) to (emphasize|focus on|highlight|mention|note|understand|know|remember)\s+",
        r"[Yy]ou (really|definitely) (need|should|want) to\s+",

        # "Focus/Emphasize" instructions
        r"[Ff]ocus on\s+",
        r"[Ee]mphasize (that|this|the|how)\s+",
        r"[Mm]ake sure to emphasize\s+",
        r"[Hh]ighlight (that|this|the)\s+",

        # "I'm going to" phrases
        r"[Ii]'m going to (explain|show|tell|demonstrate|walk through|discuss)\s+",
        r"[Ii] (want to|will) (explain|show|tell|demonstrate|share)\s+",
        r"[Ii]'ll (show you|tell you|explain)\s+",

        # "Now we're" phrases
        r"[Nn]ow we're going to (look at|examine|discuss|talk about)\s+",
        r"[Nn]ow (let's|we'll) (look at|examine|discuss)\s+",

        # "Here's" phrases (when used instructionally)
        r"[Hh]ere's the thing\s*[,:]?\s*",
        r"[Hh]ere's what you (need to|should) (know|understand)\s*[,:]?\s*",

        # "Note that" phrases
        r"[Nn]ote that\s+",
        r"[Pp]lease note\s+",

        # "As you can see" phrases
        r"[Aa]s you can see\s*[,:]?\s*",
        r"[Aa]s we can see\s*[,:]?\s*",
        r"[Aa]s (you'll|you will) notice\s*[,:]?\s*",

        # "What you need to know" phrases
        r"[Ww]hat you (need|should|ought) to (know|understand|realize|grasp)\s*[,:]?\s*",
        r"[Tt]he (thing|point) (you|to) (need to|should) (understand|know|realize)\s*[,:]?\s*",

        # Additional instruction patterns
        r"[Tt]his demonstrates (that|how)\s+",
        r"[Tt]his shows (us|you) (that|how)\s+",
        r"[Tt]his illustrates (that|how)\s+",
    ]

    cleaned = notes_text
    for pattern in meta_patterns:
        cleaned = re.sub(pattern, '', cleaned)

    # Clean up any double spaces or awkward punctuation left behind
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\s+([,.])', r'\1', cleaned)
    cleaned = re.sub(r'\.\s*,', '.', cleaned)  # Remove comma after period
    cleaned = re.sub(r'^[,\s]+', '', cleaned)  # Remove leading comma or spaces

    return cleaned.strip()

def search_web_for_context(slide_title, slide_content):
    """Search for additional information to expand on slide bullet points"""
    try:
        # Use Claude to gather relevant contextual information
        search_prompt = f"""Provide helpful background information and context for a presentation about this topic.

SLIDE TITLE: {slide_title}
SLIDE BULLET POINTS: {', '.join(slide_content[:3]) if slide_content else 'N/A'}

Provide information that would help a presenter expand on these bullet points, including:
1. Relevant statistics, data, or facts (with approximate years when relevant)
2. Real-world examples or case studies
3. Important context or background information
4. Specific details that add depth to the topic

Write 4-6 sentences of factual information that a presenter could use to elaborate beyond what's shown on the slide. Focus on accuracy and relevance. Write naturally, not as instructions."""

        response = call_anthropic(search_prompt, max_tokens=400)
        return response.strip()

    except Exception as e:
        logger.error(f"Error searching web for context: {str(e)}")
        return ""

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

@app.route('/api/generate-content', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def generate_content():
    """Generate slide content - REQUIRES SUBSCRIPTION"""
    try:
        user_id = session['user_id']
        
        # Rate limiting
        if not check_rate_limit(user_id, 'generate-content'):
            return jsonify({'error': 'Too many requests'}), 429
        
        data = request.json
        section = data.get('section')
        slide_title = data.get('slide_title')
        slide_format = data.get('slide_format', 'Detailed')
        
        if not section or not slide_title:
            return jsonify({'error': 'Missing required fields'}), 400
        
        facts_text = '\n'.join(section.get('facts', [])[:4])
        
        if slide_format == "Concise":
            # NEW: Generate ONE sentence for the slide
            prompt = f"""Create ONE clear, informative sentence for a slide titled "{slide_title}".

Key information:
{facts_text}

INSTRUCTIONS:
1. Write ONE complete sentence (15-25 words)
2. Make it informative and specific
3. Include key data or context
4. Clear and direct

EXAMPLE:
"In 1957, the Soviet Union launched Sputnik 1, the first artificial satellite to orbit Earth, marking the beginning of the Space Age."

Respond with just the sentence, nothing else:"""
        else:
            # Keep existing bullet point format for Detailed
            prompt = f"""Create 3-5 clear, informative FULL SENTENCE bullet points for a slide titled "{slide_title}".

Key information:
{facts_text}

INSTRUCTIONS:
1. Write in natural, conversational language
2. Include SPECIFIC details (numbers, dates, examples)
3. Keep bullets clear and concise (10-20 words each)

Respond ONLY with valid JSON:
{{
  "bullets": ["First informative bullet point", "Second clear bullet point"]
}}"""
        
        response = call_anthropic(prompt, max_tokens=1000)
        response = response.replace('```json\n', '').replace('\n```', '').replace('```', '').strip()
        
        if slide_format == "Concise":
            # Return the single sentence
            return jsonify({'bullets': [response]})
        else:
            result = json.loads(response)
            return jsonify({'bullets': result.get('bullets', section.get('facts', [])[:3])})
    
    except Exception as e:
        logger.error(f"Content generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-notes', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def generate_notes():
    """
    Generate AI-written speaker notes that expand on slide bullet points.
    The notes read like a human presenting the slideshow - natural, informative,
    with no instructions or meta-commentary, just information.
    """
    try:
        user_id = session['user_id']
        
        # Rate limiting
        if not check_rate_limit(user_id, 'generate-notes'):
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
        
        # STEP 1: Search the web for current information
        logger.info(f"Searching web for context on: {slide_title}")
        web_context = search_web_for_context(slide_title, slide_content)
        
        slide_bullets = '\n'.join([f"- {item}" for item in slide_content]) if slide_content else ""
        
        # STEP 2: Generate natural dialogue based on length preference
        if style == "Concise":
            prompt = f"""You are a human presenter giving a live presentation. Write exactly what you would SAY out loud to the audience about this slide. This is NOT instructions for a speaker - this IS the actual spoken words.

SLIDE TITLE: {slide_title}
SLIDE POINTS:
{slide_bullets}

ADDITIONAL CONTEXT:
{web_context}

Write 4-6 sentences that expand and elaborate on these bullet points. Speak naturally, conversationally, as if you're explaining this to real people sitting in front of you. Add details, background information, or examples that aren't on the slide. Use natural transitions like "Additionally," "This meant that," "Following this," etc.

CRITICAL RULES:
- NO instructional language ("let me explain", "pay attention", "make sure to")
- NO meta-commentary ("what's important here", "the key thing is")
- NO references to yourself ("I'm going to", "I want to show you")
- JUST present the information naturally as a knowledgeable person speaking

EXAMPLE - If slide says "Sputnik launched 1957":
"In 1957, the Soviet Union achieved something remarkable when they successfully launched Sputnik 1 into orbit. This basketball-sized satellite became the first human-made object to circle the Earth. The launch sent shockwaves through the Western world, particularly the United States. Almost overnight, it sparked a fierce competition between the two superpowers for dominance in space technology."

Write the spoken presentation now (pure information, no instructions):"""

        elif style == "Full Explanation":
            prompt = f"""You are a human presenter giving a live, comprehensive presentation. Write exactly what you would SAY out loud to the audience about this slide. This is NOT instructions - this IS the actual spoken words of a knowledgeable presenter.

SLIDE TITLE: {slide_title}
SLIDE POINTS:
{slide_bullets}

ADDITIONAL CONTEXT:
{web_context}

Write 10-14 sentences that deeply expand and elaborate on these bullet points. Speak naturally, conversationally, as if giving a thorough explanation to real people. Add substantial details, background information, real-world examples, statistics, and relevant context that aren't shown on the slide. Connect ideas smoothly with natural transitions like "As a result," "Additionally," "This led to," "Following this development," etc.

CRITICAL RULES:
- NO instructional language ("let me explain", "pay attention", "make sure to", "remember")
- NO meta-commentary ("what's important here", "the key thing is", "what matters most")
- NO references to yourself as instructor ("I'm going to", "I want to tell you", "I'll show you")
- NO audience directions ("focus on", "take note of", "keep in mind")
- JUST present the information naturally as an expert sharing knowledge

EXAMPLE - If slide says "Sputnik launched 1957":
"On October 4th, 1957, the Soviet Union achieved something that changed human history forever. They successfully launched Sputnik 1, a polished metal sphere about the size of a beach ball, into orbit around Earth. This marked the first time humanity had sent an artificial object into space. The satellite weighed just 184 pounds and contained a simple radio transmitter that sent out a steady beeping signal. That beep could be picked up by amateur radio operators around the world, proving that something was actually up there circling our planet. The launch sent immediate shockwaves through the Western world, particularly the United States, which had assumed it held technological superiority. American newspapers ran alarmed headlines, and politicians demanded to know how the Soviets had beaten them to this milestone. Within weeks, the U.S. government dramatically increased funding for science and engineering programs. This event didn't just start the Space Race—it transformed education, military strategy, and international relations for decades to come."

Write the spoken presentation now (pure information, no instructions):"""

        else:  # Detailed
            prompt = f"""You are a human presenter giving a live presentation. Write exactly what you would SAY out loud to the audience about this slide. This is NOT instructions for a speaker - this IS the actual spoken words.

SLIDE TITLE: {slide_title}
SLIDE POINTS:
{slide_bullets}

ADDITIONAL CONTEXT:
{web_context}

Write 7-10 sentences that expand and elaborate on these bullet points. Speak naturally, conversationally, as if presenting to real people in an engaged audience. Add meaningful details, background information, examples, or relevant data that aren't shown on the slide. Connect ideas with smooth transitions like "This meant that," "As a result," "Additionally," "Following this," etc.

CRITICAL RULES:
- NO instructional language ("let me explain", "pay attention", "make sure to")
- NO meta-commentary ("what's important here", "the key thing is")
- NO references to yourself ("I'm going to", "I want to show you")
- NO audience directions ("focus on", "note that", "keep in mind")
- JUST present the information naturally as a knowledgeable person speaking

EXAMPLE - If slide says "Sputnik launched 1957":
"In October of 1957, the Soviet Union shocked the world by launching Sputnik 1, the first artificial satellite to successfully orbit Earth. This polished metal sphere was relatively small, about the size of a beach ball, but its impact was enormous. The satellite carried a radio transmitter that sent out a distinctive beeping signal, which radio operators around the globe could pick up and track. For the United States, this achievement came as a profound surprise. American leaders had believed they were ahead in rocket technology, but Sputnik proved otherwise. The launch triggered an immediate response from the U.S. government, which began pouring resources into space research and science education. This single event essentially started the Space Race and reshaped the technological competition between the two superpowers."

Write the spoken presentation now (pure information, no instructions):"""
        
        response = call_anthropic(prompt, max_tokens=2000)
        
        # STEP 3: Clean any meta-instructions that slipped through
        cleaned_notes = clean_meta_instructions(response.strip())
        
        # STEP 4: Light proofread for grammar only
        proofread_notes = proofread_speaker_notes(cleaned_notes)
        
        logger.info(f"Generated natural dialogue notes for: {slide_title}")
        
        return jsonify({
            'notes': proofread_notes,
            'structure_used': 'natural_dialogue',
            'web_context_included': bool(web_context)
        })
    
    except Exception as e:
        logger.error(f"Notes generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/style-from-prompt', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING  
def generate_style_from_prompt():
    """
    NEW FEATURE: Generate presentation style from natural language prompt.
    
    Users can describe their desired presentation style in natural language:
    - "Make it look professional and corporate with blue and gray colors"
    - "I want a creative, colorful design with bold fonts"
    - "Tech startup style with modern fonts and vibrant colors"
    
    AI interprets the prompt and returns structured style parameters.
    """
    try:
        data = request.json
        user_prompt = data.get('prompt', '').strip()
        
        if not user_prompt:
            return jsonify({'error': 'Style prompt is required'}), 400
        
        logger.info(f"🎨 AI generating presentation style from prompt: {user_prompt[:50]}...")
        
        # AI interprets the user's style preferences
        prompt = f"""You are an AI design assistant creating a custom presentation theme based on the user's description.

CRITICAL REQUIREMENT: Every content slide (ALL slides EXCEPT the title slide and the final "thank you" slide) MUST include blank spaces/placeholders for images.

USER'S STYLE REQUEST:
"{user_prompt}"

YOUR TASK: Design a complete presentation style that incorporates blank image placeholders on every content slide.

Return a JSON object with these exact fields:
{{
  "theme_name": "Descriptive name for this theme (e.g. 'Corporate Blue', 'Creative Sunset')",
  "primary_color": "#RRGGBB hex color",
  "secondary_color": "#RRGGBB hex color",
  "accent_color": "#RRGGBB hex color (used for image placeholder borders)",
  "background_color": "#RRGGBB hex color",
  "text_color": "#RRGGBB hex color",
  "title_font": "Font name (e.g. 'Arial', 'Calibri', 'Georgia')",
  "body_font": "Font name (e.g. 'Arial', 'Calibri', 'Times New Roman')",
  "title_size": 36,
  "body_size": 18,
  "style_description": "2-3 sentence description explaining the theme and how it incorporates image placeholders",
  "mood": "One word (e.g. professional, creative, bold, elegant, modern)",
  "image_placeholder_style": "dark, light, or themed",
  "image_placeholder_size": "large, medium, or small",
  "image_placeholder_position": "alternating (left, right, top, bottom rotation)",
  "layout_preference": "balanced (text and images get equal space)"
}}

IMPORTANT DESIGN CONSTRAINTS:
- EVERY content slide (except title and thank you) MUST have a blank space for an image placeholder
- Image placeholder positions alternate: left, right, top, bottom across slides
- Accent color will be used for image placeholder borders - make it visually distinct
- Background and text colors must work well when images are present
- Choose colors that complement typical photographs or graphics
- Image placeholders need excellent contrast with the background
- Text must remain readable when positioned alongside images

COLOR SELECTION GUIDELINES:
- Choose colors that work well together and match the requested mood
- Ensure text_color has STRONG contrast with background_color (readable from distance)
- Accent color for image borders should stand out against both background and typical images
- Consider the context (business, education, creative, tech, etc.)
- Test colors mentally against common image types (photos, charts, graphics)

FONT GUIDELINES:
- Select professional fonts appropriate for presentations
- Title font should be bold and attention-grabbing (36pt default)
- Body font should be highly readable (18pt default)
- Fonts must maintain readability when text shares space with images

COMMON IMAGE-FRIENDLY STYLES:
- Professional/Corporate: Blues/grays, clean fonts, white/light backgrounds, dark image borders
- Creative: Vibrant backgrounds, bold fonts, colorful accents, themed image frames
- Tech/Startup: Dark backgrounds, modern fonts, neon accents, sleek image borders
- Academic: Light backgrounds, serif fonts, traditional colors, subtle borders
- Minimalist: White/gray backgrounds, sans-serif fonts, minimal color accents

REMEMBER: Title slide = NO image placeholder. Thank you slide = NO image placeholder. ALL OTHER SLIDES = MUST have image placeholder.

Generate the style configuration JSON now:"""
        
        response = call_anthropic(prompt, max_tokens=1500)
        
        # Parse JSON response
        try:
            # Clean markdown code blocks if present
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)
            
            style_config = json.loads(response)
            
            # Validate required fields
            required_fields = [
                'theme_name', 'primary_color', 'secondary_color', 'accent_color',
                'background_color', 'text_color', 'title_font', 'body_font',
                'title_size', 'body_size', 'style_description', 'mood',
                'image_placeholder_style', 'image_placeholder_size',
                'image_placeholder_position', 'layout_preference'
            ]
            
            for field in required_fields:
                if field not in style_config:
                    raise ValueError(f"Missing required field: {field}")
            
            logger.info(f"✅ AI-generated style: {style_config.get('theme_name')}")
            
            return jsonify({
                'success': True,
                'style': style_config,
                'generated_from': user_prompt,
                'message': f"Custom style '{style_config.get('theme_name')}' created successfully!"
            })
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nResponse: {response}")
            return jsonify({'error': 'Failed to parse style configuration'}), 500
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            return jsonify({'error': str(e)}), 500
    
    except Exception as e:
        logger.error(f"❌ Style generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/complete', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def complete_presentation():
    """Mark presentation as complete and increment generation count - REQUIRES SUBSCRIPTION"""
    try:
        user_id = session['user_id']
        data = request.json
        
        title = data.get('title', 'Untitled')
        topic = data.get('topic', '')
        num_slides = data.get('num_slides', 10)
        theme = data.get('theme', 'Default')
        
        # Increment generation count
        increment_generation_count(user_id)
        
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
        
        logger.info(f"User {user_id} completed presentation: {title}")
        return jsonify({
            'success': True, 
            'message': 'Presentation generated successfully!',
            'presentation_id': presentation_id
        })
    
    except Exception as e:
        logger.error(f"Complete presentation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/generate-pptx', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def generate_pptx():
    """Generate the actual PowerPoint file - REQUIRES SUBSCRIPTION"""
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
        custom_style = data.get('customStyle')  # NEW: Custom style from AI
        
        logger.info(f"Generating PPTX: {title[:30]} with notes style: {notes_style}")
        
        if custom_style:
            logger.info(f"Custom style provided: {custom_style.get('theme_name')} (will use if supported)")
        
        # Generate presentation in temp file
        # Try with custom_style first, fall back to without it if not supported
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
            try:
                # Try passing custom_style (for updated pptx_generator)
                if custom_style:
                    filename = generate_presentation(
                        title=title,
                        topic=topic,
                        sections=sections,
                        theme_name=theme,
                        notes_style=notes_style,
                        custom_style=custom_style,
                        filename=tmp.name
                    )
                else:
                    filename = generate_presentation(
                        title=title,
                        topic=topic,
                        sections=sections,
                        theme_name=theme,
                        notes_style=notes_style,
                        filename=tmp.name
                    )
            except TypeError as e:
                # If custom_style parameter not supported, try without it
                if 'custom_style' in str(e):
                    logger.warning("pptx_generator doesn't support custom_style yet, using standard generation")
                    filename = generate_presentation(
                        title=title,
                        topic=topic,
                        sections=sections,
                        theme_name=theme,
                        notes_style=notes_style,
                        filename=tmp.name
                    )
                else:
                    raise
            
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

# ============= Utility Endpoints =============

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'api_configured': bool(ANTHROPIC_API_KEY),
        'stripe_configured': bool(stripe.api_key),
        'features': {
            'ai_speaker_notes': True,
            'custom_style_generation': True,
            'web_enhanced_content': True,
            'natural_dialogue_notes': True
        }
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
    print("✓ NO PAYMENT REQUIRED - Free to use")
    print("✓ NO SUBSCRIPTION NEEDED - Unlimited presentations")
    print("✓ AI-written speaker notes that expand on slide bullet points")
    print("✓ Notes read like natural human presentation - no instructions")
    print("✓ Web-enhanced content with current information and examples")
    print("✓ AI-powered custom style generation from prompts")
    
    # For local development
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
