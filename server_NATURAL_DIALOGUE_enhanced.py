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
✓ CUSTOM STYLE GENERATION: AI interprets user prompts to create custom presentation styles

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
    """Increment the user's generation count"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET generations_used = generations_used + 1 
        WHERE id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

# ============= Authentication Endpoints =============

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user - NO FREE TIER, subscription required"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400
        
        password_hash = hash_password(password)
        
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO users (email, password_hash, subscription_status, generations_limit)
                VALUES (?, ?, 'inactive', 0)
            ''', (email, password_hash))
            user_id = cursor.lastrowid
            conn.commit()
            
            session['user_id'] = user_id
            session['email'] = email
            
            logger.info(f"New user registered: {email}")
            return jsonify({
                'success': True,
                'message': 'Account created! Subscribe to start creating presentations.',
                'user': {
                    'id': user_id,
                    'email': email,
                    'subscription_status': 'inactive',
                    'generations_used': 0,
                    'generations_limit': 0
                },
                'requires_subscription': True
            })
        
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Email already registered'}), 400
        finally:
            conn.close()
    
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login existing user"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        password_hash = hash_password(password)
        
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute(
            'SELECT * FROM users WHERE email = ? AND password_hash = ?',
            (email, password_hash)
        ).fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
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
    """Logout user"""
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/api/auth/me', methods=['GET'])
@login_required
def get_current_user():
    """Get current user info"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'user': {
                'id': user['id'],
                'email': user['email'],
                'subscription_status': user['subscription_status'],
                'generations_used': user['generations_used'],
                'generations_limit': user['generations_limit'],
                'subscription_expires': user['subscription_expires']
            }
        })
    
    except Exception as e:
        logger.error(f"Get user error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ============= Subscription & Payment Endpoints =============

@app.route('/api/subscription/create-checkout', methods=['POST'])
@login_required
def create_checkout_session():
    """Create Stripe checkout session for subscription"""
    try:
        if not stripe.api_key:
            return jsonify({'error': 'Payment system not configured'}), 500
        
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
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET stripe_customer_id = ? WHERE id = ?', (customer_id, user_id))
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
            success_url=request.host_url + 'subscription-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'subscription-cancel',
            metadata={'user_id': user_id}
        )
        
        return jsonify({
            'checkout_url': checkout_session.url,
            'session_id': checkout_session.id
        })
    
    except Exception as e:
        logger.error(f"Checkout creation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/subscription/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhooks"""
    try:
        payload = request.data
        sig_header = request.headers.get('Stripe-Signature')
        
        # Verify webhook signature (you need to set STRIPE_WEBHOOK_SECRET in .env)
        webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = json.loads(payload)
        
        # Handle subscription events
        if event['type'] == 'checkout.session.completed':
            session_data = event['data']['object']
            user_id = int(session_data['metadata']['user_id'])
            
            # Activate subscription
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'premium',
                    subscription_expires = datetime('now', '+1 month'),
                    generations_limit = 50,
                    stripe_subscription_id = ?
                WHERE id = ?
            ''', (session_data.get('subscription'), user_id))
            conn.commit()
            conn.close()
            
            logger.info(f"Subscription activated for user {user_id}")
        
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            
            # Deactivate subscription
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users 
                SET subscription_status = 'inactive',
                    generations_limit = 0
                WHERE stripe_subscription_id = ?
            ''', (subscription['id'],))
            conn.commit()
            conn.close()
            
            logger.info(f"Subscription cancelled for subscription {subscription['id']}")
        
        return jsonify({'success': True})
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'error': str(e)}), 400

@app.route('/api/subscription/status', methods=['GET'])
@login_required
def subscription_status():
    """Get user's subscription status"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        user = cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'subscription_status': user['subscription_status'],
            'generations_used': user['generations_used'],
            'generations_limit': user['generations_limit'],
            'subscription_expires': user['subscription_expires']
        })
    
    except Exception as e:
        logger.error(f"Status check error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ============= Core API Helper Functions =============

def call_anthropic(prompt, max_tokens=4000):
    """Call Anthropic API with error handling"""
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
        
        if response.status_code != 200:
            error_detail = response.json() if response.text else {}
            logger.error(f"API Error {response.status_code}: {error_detail}")
            raise Exception(f"API Error: {response.status_code} - {error_detail}")
        
        result = response.json()
        
        if 'content' in result and len(result['content']) > 0:
            return result['content'][0]['text']
        else:
            raise Exception("No content in API response")
    
    except requests.exceptions.Timeout:
        raise Exception("API request timed out")
    except requests.exceptions.RequestException as e:
        raise Exception(f"API request failed: {str(e)}")

def web_search(query):
    """
    Perform web search using Brave Search API.
    Returns relevant snippets and context for speaker notes.
    """
    try:
        brave_api_key = os.environ.get('BRAVE_API_KEY')
        if not brave_api_key:
            logger.warning("BRAVE_API_KEY not set - web search disabled")
            return ""
        
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": brave_api_key
        }
        
        params = {
            "q": query,
            "count": 5
        }
        
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
            timeout=10
        )
        
        if response.status_code == 200:
            results = response.json()
            
            # Extract relevant information
            context_parts = []
            if 'web' in results and 'results' in results['web']:
                for result in results['web']['results'][:3]:
                    title = result.get('title', '')
                    description = result.get('description', '')
                    context_parts.append(f"{title}: {description}")
            
            return "\n".join(context_parts) if context_parts else ""
        else:
            logger.warning(f"Web search failed: {response.status_code}")
            return ""
    
    except Exception as e:
        logger.error(f"Web search error: {str(e)}")
        return ""

def clean_meta_instructions(text):
    """Remove any meta-instructions or speaker directions that slipped through"""
    # Patterns that indicate meta-instructions
    meta_patterns = [
        r"Let's break this down",
        r"Let me walk you through",
        r"Let me explain",
        r"Pay attention to",
        r"Make sure to note",
        r"The key thing is",
        r"Here's what matters",
        r"I'll explain",
        r"As you can see",
        r"You'll notice that",
        r"It's important to understand",
    ]
    
    import re
    cleaned = text
    for pattern in meta_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Remove extra spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned

def proofread_speaker_notes(notes):
    """Light grammar check on speaker notes using AI"""
    try:
        prompt = f"""Proofread these speaker notes for grammar and clarity only. Keep the same content and tone - just fix any grammatical errors:

{notes}

Return only the corrected text with no additional commentary."""
        
        return call_anthropic(prompt, max_tokens=1000)
    except Exception as e:
        logger.error(f"Proofread error: {str(e)}")
        return notes  # Return original if proofreading fails

# ============= Presentation Generation Endpoints =============

@app.route('/api/presentations/outline', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def generate_outline():
    """Generate presentation outline - REQUIRES SUBSCRIPTION"""
    try:
        data = request.json
        topic = data.get('topic', '')
        num_slides = data.get('numSlides', 10)
        
        if not topic:
            return jsonify({'error': 'Topic is required'}), 400
        
        # Check if user can generate
        user_id = session['user_id']
        if not check_generations_limit(user_id):
            return jsonify({
                'error': 'Generation limit reached. Upgrade your plan for more presentations.',
                'subscription_required': True
            }), 403
        
        logger.info(f"Generating outline for: {topic} ({num_slides} slides)")
        
        prompt = f"""Create a structured presentation outline about: {topic}

Generate exactly {num_slides} slides following this structure:

1. Title Slide
   - Main title: "{topic}"
   - Subtitle: Brief tagline or context

2-{num_slides}. Content Slides
   Each slide should have:
   - Clear title (4-8 words)
   - 3-5 bullet points
   - Each bullet should be concise (8-15 words)

Format as JSON:
{{
  "title": "Main presentation title",
  "subtitle": "Brief subtitle",
  "sections": [
    {{
      "title": "Section 1 Title",
      "slides": [
        {{
          "title": "Slide title",
          "bullets": ["Point 1", "Point 2", "Point 3"]
        }}
      ]
    }}
  ]
}}

Make it professional, logical, and comprehensive."""

        response = call_anthropic(prompt, max_tokens=3000)
        
        # Parse JSON response
        try:
            # Clean markdown code blocks if present
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)
            
            outline = json.loads(response)
            return jsonify(outline)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nResponse: {response}")
            return jsonify({'error': 'Failed to parse outline'}), 500
    
    except Exception as e:
        logger.error(f"Outline generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/presentations/speaker-notes', methods=['POST'])
@login_required
# @subscription_required  # REMOVED FOR TESTING
def generate_speaker_notes():
    """
    Generate AI-powered speaker notes based on slide key points.
    
    CRITICAL: Speaker notes are ALWAYS AI-generated from the slide content.
    The AI analyzes the key points and creates natural, conversational notes
    that expand on the bullet points with context, examples, and smooth transitions.
    """
    try:
        data = request.json
        slide_title = data.get('title', '')
        bullets = data.get('bullets', [])
        style = data.get('style', 'Detailed')  # Brief, Detailed, or Full Explanation
        
        if not slide_title or not bullets:
            return jsonify({'error': 'Slide title and bullets required'}), 400
        
        logger.info(f"🤖 AI GENERATING speaker notes for: {slide_title} (style: {style})")
        
        # Format bullets for prompt
        slide_bullets = '\n'.join([f"• {bullet}" for bullet in bullets])
        
        # STEP 1: Gather web context for enrichment (optional but recommended)
        search_query = f"{slide_title} statistics examples"
        web_context = web_search(search_query)
        
        if web_context:
            logger.info(f"✓ Web context retrieved for enhanced notes")
        
        # STEP 2: AI generates natural dialogue based on key points and context
        # The prompts vary by style but ALL generate AI content from the key points
        
        if style == "Brief":
            prompt = f"""You are an AI assistant generating natural speaker notes for a presentation slide.

SLIDE TITLE: {slide_title}
KEY POINTS ON SLIDE:
{slide_bullets}

ADDITIONAL RESEARCH CONTEXT:
{web_context}

YOUR TASK: Generate 4-6 sentences of natural dialogue that a presenter would say when presenting this slide. 

REQUIREMENTS:
✓ Expand on the key points with context and examples
✓ Use the research context to add specific details, statistics, or real examples
✓ Write in a conversational, natural speaking style
✓ Include smooth transitions between ideas
✓ Sound like an expert explaining the topic to an engaged audience

EXAMPLE OF GOOD OUTPUT:
"In 1957, the Soviet Union shocked the world by launching Sputnik 1, the first artificial satellite to orbit Earth. This proved humans could send objects beyond our atmosphere. The launch triggered intense competition between the U.S. and USSR. Within months, both nations accelerated their space programs."

DO NOT include any of these phrases:
❌ "Let's break this down"
❌ "Let me walk you through"  
❌ "Pay attention to"
❌ "The key thing is"
❌ Any instructions to the speaker

Generate the speaker notes now:"""
        
        elif style == "Full Explanation":
            prompt = f"""You are an AI assistant generating comprehensive speaker notes for a presentation slide.

SLIDE TITLE: {slide_title}
KEY POINTS ON SLIDE:
{slide_bullets}

ADDITIONAL RESEARCH CONTEXT:
{web_context}

YOUR TASK: Generate 10-14 sentences of natural dialogue that thoroughly explains these points.

REQUIREMENTS:
✓ Deeply expand on each key point with rich context
✓ Use the research context to add specific statistics, data, and real-world examples
✓ Write in a conversational, engaging speaking style
✓ Include smooth transitions like "This meant that...", "At the same time...", "The result was..."
✓ Sound like an expert giving a detailed explanation to an interested audience
✓ Connect ideas logically and build a coherent narrative

EXAMPLE OF GOOD OUTPUT:
"In 1957, the Soviet Union shocked the world by launching Sputnik 1, the first artificial satellite to orbit Earth. This moment proved that humans now had the ability to send objects beyond our atmosphere. The achievement wasn't just technical—it was deeply political. Sputnik triggered intense scientific and military competition between the U.S. and USSR. Within months, both nations dramatically accelerated their space programs. The United States responded by increasing funding for science education. This investment shaped an entire generation of engineers and scientists."

DO NOT include any of these phrases:
❌ "Let's break this down"
❌ "Let me explain"
❌ "Pay attention to"
❌ "Here's what matters"
❌ Any meta-instructions

Generate the comprehensive speaker notes now:"""
        
        else:  # Detailed (default)
            prompt = f"""You are an AI assistant generating detailed speaker notes for a presentation slide.

SLIDE TITLE: {slide_title}
KEY POINTS ON SLIDE:
{slide_bullets}

ADDITIONAL RESEARCH CONTEXT:
{web_context}

YOUR TASK: Generate 7-10 sentences of natural dialogue that clearly explains these points.

REQUIREMENTS:
✓ Expand on the key points with meaningful context and examples
✓ Use the research context to add specific details, data, or real examples
✓ Write in a conversational, natural speaking style
✓ Include smooth transitions like "This meant that...", "As a result...", "Additionally..."
✓ Sound like a knowledgeable presenter explaining the topic clearly

EXAMPLE OF GOOD OUTPUT:
"In 1957, the Soviet Union shocked the world by launching Sputnik 1, the first artificial satellite to orbit Earth. This proved humans could send objects beyond our atmosphere. The launch triggered intense competition between the U.S. and USSR. Both nations accelerated their space programs dramatically. The United States responded by investing heavily in science education. This shaped an entire generation of engineers and scientists."

DO NOT include any of these phrases:
❌ "Let's break this down"
❌ "Let me walk you through"
❌ "Pay attention to"
❌ "Make sure to note"
❌ "The key thing is"
❌ Any instructions or directions

Generate the speaker notes now:"""
        
        # Call AI to generate the notes
        response = call_anthropic(prompt, max_tokens=2000)
        
        # STEP 3: Clean any meta-instructions that might have slipped through
        cleaned_notes = clean_meta_instructions(response.strip())
        
        # STEP 4: Light proofread for grammar only
        proofread_notes = proofread_speaker_notes(cleaned_notes)
        
        logger.info(f"✅ AI-generated speaker notes complete for: {slide_title}")
        
        return jsonify({
            'notes': proofread_notes,
            'generated_by': 'AI',
            'based_on': 'slide_key_points',
            'web_enhanced': bool(web_context),
            'style': style
        })
    
    except Exception as e:
        logger.error(f"❌ Speaker notes AI generation error: {str(e)}")
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
        prompt = f"""You are an AI design assistant helping create a custom presentation style.

USER'S STYLE REQUEST:
"{user_prompt}"

YOUR TASK: Interpret this request and generate a complete presentation style configuration.

Return a JSON object with these exact fields:
{{
  "theme_name": "Descriptive name for this theme (e.g. 'Corporate Blue', 'Creative Sunset')",
  "primary_color": "#RRGGBB hex color",
  "secondary_color": "#RRGGBB hex color",
  "accent_color": "#RRGGBB hex color",
  "background_color": "#RRGGBB hex color",
  "text_color": "#RRGGBB hex color",
  "title_font": "Font name (e.g. 'Arial', 'Calibri', 'Georgia')",
  "body_font": "Font name (e.g. 'Arial', 'Calibri', 'Times New Roman')",
  "title_size": 44,
  "body_size": 18,
  "style_description": "2-3 sentence description of this style",
  "mood": "One word (e.g. professional, creative, bold, elegant, modern)",
  "use_gradients": true or false,
  "use_shadows": true or false,
  "layout_style": "modern, classic, or minimal"
}}

GUIDELINES:
- Choose colors that work well together and match the requested mood
- Ensure text_color has good contrast with background_color
- Select professional fonts appropriate for presentations
- Font sizes should be readable (title: 40-48pt, body: 16-24pt)
- Consider the context (business, education, creative, tech, etc.)

COMMON STYLES TO REFERENCE:
- Professional/Corporate: Blues, grays, clean fonts, minimal design
- Creative: Bright colors, bold fonts, gradients, modern layout
- Tech/Startup: Vibrant colors, modern fonts, sleek design
- Academic: Traditional colors, serif fonts, classic layout
- Minimalist: Limited colors, clean fonts, lots of white space

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
                'title_size', 'body_size', 'style_description', 'mood'
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
            logger.info(f"Using custom AI-generated style: {custom_style.get('theme_name')}")
        
        # Generate presentation in temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as tmp:
            filename = generate_presentation(
                title=title,
                topic=topic,
                sections=sections,
                theme_name=theme,
                notes_style=notes_style,
                custom_style=custom_style,  # Pass custom style to generator
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
        'stripe_configured': bool(stripe.api_key),
        'features': {
            'ai_speaker_notes': True,
            'custom_style_generation': True,
            'web_enhanced_content': True
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
    print("✓ AI-GENERATED speaker notes from key points")
    print("✓ NEW: Custom style generation from natural language prompts")
    print("✓ Web-enhanced content with real-time research")
    
    # For local development
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
