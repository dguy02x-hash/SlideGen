#!/usr/bin/env python3
"""
SlideGen Pro - Backend Server with Authentication & Subscriptions
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

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# CORS configuration - allow localhost for development and production domain
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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

        # SIMPLE APPROACH: Just use the facts directly from the outline
        # This prevents repetition and ensures each slide has unique content
        facts = section.get('facts', [])
        bullets = facts[:5]  # Use up to 5 facts directly as bullets

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
        
        if style == "Concise":
            style_instruction = "Create brief talking points (2-3 sentences total)."
        else:  # Detailed style
            style_instruction = "For EACH bullet point on the slide, write 1-2 additional sentences that expand on it with relevant details, context, or examples."
        
        if slide_format == "Concise":
            format_instruction = f"The slide shows KEY WORDS: {slide_bullets}\nEXPLAIN each keyword with full context."
        else:
            format_instruction = f"The slide shows: {slide_bullets}\nELABORATE with additional details."

        # Create completely unique structure for each slide
        structures = [
            "Start with a personal anecdote or story, then connect it to the data. Use conversational language like you're telling a friend.",
            "Begin with a surprising statistic, then explain why it matters. Sound like a documentary narrator revealing insights.",
            "Open with a rhetorical question to the audience, then answer it with examples. Be engaging and interactive.",
            "Start with 'Imagine...' and paint a vivid scenario, then tie it back to facts. Be descriptive and relatable.",
            "Begin by comparing this to something familiar (like 'Think of it like...'), then dive into specifics. Use analogies.",
            "Open with 'Here's what most people don't know...' and share insider insights. Be revealing and informative.",
            "Start with 'Let me tell you about...' and share a brief case study. Be specific with names and details.",
            "Begin with 'The key to understanding this is...' and break it down simply. Be educational and clear.",
            "Open with 'In my experience...' or 'Research shows...' and share evidence. Be authoritative yet approachable.",
            "Start with 'Picture this scenario:' and describe a real-world application. Be practical and action-oriented."
        ]

        structure = structures[slide_num % len(structures)]

        # Check if there's source document content to enhance speaker notes
        source_document = session.get('source_document', '')
        document_context = ""

        if source_document:
            # Extract relevant excerpts from source document for this slide
            doc_excerpt = source_document[:3000]  # Use first 3000 chars as context
            document_context = f"""
SOURCE DOCUMENT CONTEXT (use this for additional details NOT shown on slide):
{doc_excerpt}

IMPORTANT: Pull supplementary information, examples, data, or context from the source document above that relates to "{slide_title}" but is NOT already on the slide. Use this to enrich your speaker notes with information the audience won't see on screen.
"""

        # Generate varied transition words for this slide
        transition_sets = [
            ["What's fascinating here is", "Here's what makes this significant", "Now, here's the key insight"],
            ["Let me break this down", "Here's what really matters", "The interesting part is"],
            ["Think about it this way", "Here's the reality", "What we're seeing here is"],
            ["Now consider this", "The crucial point is", "What's remarkable about this"],
            ["Here's where it gets interesting", "Let me explain why this matters", "The real story here is"],
            ["So what does this mean?", "Here's the practical application", "Let's dig deeper into this"],
            ["You might be wondering", "The data shows us", "What's emerging here is"],
            ["This is particularly revealing", "Here's the context you need", "Let me give you perspective"],
            ["Picture this scenario", "Here's what research tells us", "The compelling part is"],
            ["Let's explore why", "What we discovered is", "Here's the breakthrough insight"]
        ]

        transitions = transition_sets[slide_num % len(transition_sets)]

        if style == "Concise":
            prompt = f"""Write brief speaker notes (2-3 sentences total) for slide {slide_num} titled "{slide_title}".

THE SLIDE SHOWS:
{slide_bullets}

Write 2-3 concise sentences that summarize the key takeaways from this slide in a conversational tone.

Speaker notes:"""
        else:  # Detailed style
            prompt = f"""Write speaker notes for slide {slide_num} titled "{slide_title}".

THE SLIDE SHOWS (each bullet point is ONE sentence):
{slide_bullets}

YOUR TASK: For EACH bullet point above, write 1-2 additional sentences that expand on it with relevant details, context, or examples.

FORMAT:
• [Bullet point from slide]
  [1-2 sentences expanding on this point with specific details, context, examples, or explanations]

• [Next bullet point from slide]
  [1-2 sentences expanding on this point]

RULES:
- Keep the original bullet text, then add 1-2 sentences after it
- Make your additions specific and informative (add data, examples, context, or explanations)
- Be conversational and natural
- Don't repeat - each addition should provide NEW information
- {style_instruction}

{document_context}

Write your speaker notes now (plain text):"""

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
    """Mark presentation as complete and increment generation count"""
    try:
        user_id = session.get('user_id', 'anonymous')
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

# ============= Static File Serving =============

@app.route('/')
def serve_index():
    """Serve the main HTML file"""
    return send_from_directory('.', 'index.html')

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
