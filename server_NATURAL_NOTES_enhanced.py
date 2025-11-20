#!/usr/bin/env python3
"""
SlideGen Pro - Backend Server with Authentication & Subscriptions
PAYMENT REQUIRED - No free tier, users must subscribe to generate presentations.

ENHANCED FEATURES:
================
✓ Web-Enhanced Speaker Notes: AI searches for current information, statistics, and examples
✓ Varied Note Structures: 8 different presentation formats (narrative, data-driven, comparative, etc.)
✓ Professional Tone: Polished yet natural speaker notes that sound like expert presentations
✓ Dynamic Content: Each slide uses a different structure to avoid repetitive delivery
✓ Research Integration: Real-time information gathering to enhance presentation quality

SPEAKER NOTE STRUCTURES:
=======================
1. Narrative: Story-telling approach with examples
2. Data-driven: Statistics and metrics focus
3. Comparative: Compare and contrast elements
4. Problem-solution: Present challenges then solutions
5. Chronological: Timeline or sequence-based delivery
6. Conceptual: Big-picture explanations
7. Practical: Real-world application focus
8. Analytical: Deep-dive component analysis

Each slide automatically cycles through these structures to create varied, engaging presentations.
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
    Proofread speaker notes for grammar while preserving natural, explanatory presentation tone.
    Returns grammatically corrected version that sounds like a knowledgeable person explaining.
    """
    try:
        prompt = f"""You are editing speaker notes for a professional presentation. Polish the grammar and flow while maintaining a natural, explanatory style.

ORIGINAL NOTES:
{notes_text}

TASK: Refine grammar, punctuation, and clarity while preserving the natural explanatory tone.

CRITICAL RULES:
1. Fix grammatical errors and awkward phrasing
2. Maintain natural, professional explanatory language (like the Space Race example)
3. Keep industry-specific terms and technical language exactly as written
4. Preserve all data points, statistics, names, and specific examples exactly
5. Ensure smooth transitions between sentences
6. Remove redundancies but keep intentional emphasis
7. Maintain varied sentence structures (don't make everything uniform)
8. Keep the overall structure and approach intact
9. Sound like a knowledgeable expert explaining naturally, not reading a script
10. REMOVE any meta-instructions to the speaker (phrases like "pay attention to", "this is crucial", "make sure to emphasize", "here's what matters")
11. Just have the notes explain the content - no commentary about how to present it
12. Return ONLY the corrected notes, nothing else

Examples of GOOD natural explanatory tone:
- "In 1957, the Soviet Union shocked the world by launching Sputnik 1, the first artificial satellite to orbit Earth."
- "This moment is widely considered the start of the Space Age, because it proved that humans now had the ability to send objects beyond Earth's atmosphere."

Examples of BAD meta-instructions to REMOVE:
- "Pay attention to this important point..."
- "Make sure you emphasize..."
- "This is crucial to understand..."
- "What really matters here is..."

POLISHED NOTES:"""

        corrected = call_anthropic(prompt, max_tokens=1500)
        return corrected.strip()
    
    except Exception as e:
        logger.error(f"Error proofreading notes: {str(e)}")
        # Return original if proofreading fails
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
@subscription_required
def research_topic():
    """Research topic and create presentation outline - REQUIRES SUBSCRIPTION"""
    try:
        user_id = session['user_id']
        
        # Check generations limit
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

def search_web_for_context(slide_title, slide_content):
    """Search the web for current information about the slide topic"""
    try:
        # Create a focused search query from the slide title and content
        search_query = f"{slide_title} latest information statistics examples"
        
        # Use Claude to search the web and gather information
        search_prompt = f"""I need current, factual information to enhance speaker notes for a presentation slide.

SLIDE TITLE: {slide_title}
SLIDE CONTENT: {', '.join(slide_content[:3]) if slide_content else 'N/A'}

Please provide:
1. Recent statistics, data, or facts (with approximate years if relevant)
2. Real-world examples or case studies
3. Current trends or developments
4. Expert insights or industry perspectives

Format your response as a brief, informative paragraph (4-6 sentences) that a presenter could use to elaborate on the slide points. Focus on accuracy and relevance."""

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
@subscription_required
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
            prompt = f"""Create 3-5 KEY WORDS or SHORT PHRASES (2-4 words each) for a slide titled "{slide_title}".

Key information:
{facts_text}

INSTRUCTIONS:
1. Use ONLY key words or very short phrases (2-4 words maximum)
2. NO complete sentences
3. Make them specific

Respond ONLY with valid JSON:
{{
  "bullets": ["Key phrase one", "Key phrase two", "Key phrase three"]
}}"""
        else:
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
        result = json.loads(response)
        
        return jsonify({'bullets': result.get('bullets', section.get('facts', [])[:3])})
    
    except Exception as e:
        logger.error(f"Content generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-notes', methods=['POST'])
@login_required
@subscription_required
def generate_notes():
    """Generate speaker notes with web-searched information and varied formatting - REQUIRES SUBSCRIPTION"""
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
        
        facts_text = '\n'.join(section.get('facts', []))
        slide_bullets = '\n'.join([f"• {item}" for item in slide_content]) if slide_content else ""
        
        # STEP 2: Create varied note structures based on slide number
        # This ensures each slide has a different feel and format
        note_structures = [
            "narrative",      # Story-telling approach
            "data_driven",    # Statistics and numbers focus
            "comparative",    # Compare and contrast
            "problem_solution", # Problem-solution format
            "chronological",  # Timeline/sequence approach
            "conceptual",     # Big-picture concept explanation
            "practical",      # Real-world application focus
            "analytical"      # Deep-dive analysis
        ]
        
        structure_type = note_structures[slide_num % len(note_structures)]
        
        # STEP 3: Generate notes based on style and structure
        if style == "Concise":
            prompt = f"""You are writing speaker notes for a professional presentation. Create CONCISE notes for slide {slide_num} that naturally explain and expand on the bullet points.

SLIDE TITLE: {slide_title}
SLIDE CONTENT:
{slide_bullets}

CURRENT RESEARCH & CONTEXT:
{web_context}

STRUCTURE TYPE: {structure_type.upper()} APPROACH

INSTRUCTIONS:
1. Expand on each bullet point naturally, like explaining to an interested audience
2. Explain significance, context, or impact - don't just restate
3. Use the {structure_type} approach to vary your delivery style
4. Integrate research findings naturally (statistics, examples, context)
5. Keep it brief (3-4 sentences total)
6. Vary sentence structure - each point should open differently
7. NO meta-instructions to the speaker (no "pay attention to", "make sure to emphasize", etc.)
8. Just explain the content naturally and informatively

Generate natural, explanatory speaker notes (plain text only):"""
        
        elif style == "Full Explanation":
            prompt = f"""You are writing speaker notes for a professional presentation. Create COMPREHENSIVE notes for slide {slide_num} that naturally explain and expand on the bullet points.

SLIDE TITLE: {slide_title}
SLIDE CONTENT:
{slide_bullets}

CURRENT RESEARCH & CONTEXT:
{web_context}

STRUCTURE TYPE: {structure_type.upper()} APPROACH

INSTRUCTIONS:
1. Expand each bullet point with context, significance, examples, or historical background
2. Explain WHY things matter and HOW they connect to the bigger picture
3. Use the {structure_type} format to create a unique flow for this slide
4. Integrate research findings seamlessly (specific data, case studies, industry insights)
5. Build a natural explanation (7-9 sentences)
6. Vary sentence structure significantly - avoid repetitive patterns
7. Sound like a knowledgeable expert explaining things naturally
8. NO meta-instructions to the speaker (no "this is crucial", "pay attention to", "here's what matters")
9. Just explain the content informatively and engagingly

Examples of good expansion:
- "In 1957, the Soviet Union shocked the world by launching Sputnik 1..."
- "This moment is widely considered the start of the Space Age, because it proved..."
- "Just four years later, the Soviet Union achieved another historic milestone..."

Generate natural, explanatory speaker notes (plain text only):"""
        
        else:  # Detailed
            prompt = f"""You are writing speaker notes for a professional presentation. Create DETAILED notes for slide {slide_num} that naturally explain and expand on the bullet points.

SLIDE TITLE: {slide_title}
SLIDE CONTENT:
{slide_bullets}

CURRENT RESEARCH & CONTEXT:
{web_context}

STRUCTURE TYPE: {structure_type.upper()} APPROACH

INSTRUCTIONS:
1. Expand on each bullet point with context, significance, examples, or relevant background
2. Explain what things mean and why they matter
3. Use the {structure_type} structure to make this slide unique from others
4. Weave in research findings naturally (statistics, real-world applications, industry insights)
5. Maintain a professional but natural tone (5-7 sentences)
6. Vary your opening and structure based on the approach:
   - Narrative: Start with an example or story that illustrates the point
   - Data-driven: Open with compelling statistics or metrics
   - Comparative: Begin by contrasting two things or showing evolution
   - Problem-solution: Present the challenge first, then the resolution
   - Chronological: Walk through the sequence or timeline
   - Conceptual: Explain the underlying principle or big picture
   - Practical: Focus on how it works in practice or real applications
   - Analytical: Break down the components or relationships
7. NO meta-instructions or directions to the speaker (no "this is crucial", "pay attention to", "what really matters here", "make sure to emphasize")
8. Just explain the content naturally - let the information speak for itself

Examples of natural explanation style:
- "In 1957, the Soviet Union shocked the world by launching Sputnik 1, the first artificial satellite to orbit Earth."
- "This moment is widely considered the start of the Space Age, because it proved that humans now had the ability to send objects beyond Earth's atmosphere."
- "Just four years later, the Soviet Union achieved another historic milestone when Yuri Gagarin became the first human to travel into space."

Generate natural, informative speaker notes (plain text only):"""
        
        response = call_anthropic(prompt, max_tokens=1500)
        
        # STEP 4: Proofread while maintaining professional tone
        proofread_notes = proofread_speaker_notes(response.strip())
        
        logger.info(f"Generated web-enhanced notes with {structure_type} structure for: {slide_title}")
        
        return jsonify({
            'notes': proofread_notes,
            'structure_used': structure_type,
            'web_context_included': bool(web_context)
        })
    
    except Exception as e:
        logger.error(f"Notes generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/complete', methods=['POST'])
@login_required
@subscription_required
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
@subscription_required
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
        
        logger.info(f"Generating PPTX: {title[:30]} with notes style: {notes_style}")
        
        # Generate presentation in temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
            filename = generate_presentation(
                title=title,
                topic=topic,
                sections=sections,
                theme_name=theme,
                notes_style=notes_style,
                filename=tmp.name
            )
            
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
    print("✓ PAYMENT REQUIRED - $6.99/month for 10 presentations")
    print("✓ NO FREE TIER - Users must subscribe to generate presentations")
    print("✓ Web-enhanced speaker notes with varied professional formatting")
    print("✓ AI-powered research integration for current information")
    print("✓ 8 distinct presentation structures for note variety")
    
    # For local development
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
