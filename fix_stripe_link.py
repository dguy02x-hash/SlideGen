#!/usr/bin/env python3
"""
Fix missing Stripe subscription link for a user
Usage: python3 fix_stripe_link.py email@example.com
"""
import sqlite3
import sys
import os
import stripe
from dotenv import load_dotenv

load_dotenv()

# Load environment variables
DB_PATH = os.environ.get('DATABASE_PATH', 'slidegen.db')
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

def fix_stripe_link(email):
    """Link Stripe subscription to user account"""
    email = email.strip().lower()

    print(f'\n{"="*80}')
    print(f'FIXING STRIPE LINK FOR: {email}')
    print(f'{"="*80}\n')

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get user
    user = cursor.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

    if not user:
        print(f'❌ User {email} not found in database')
        conn.close()
        return

    print(f'✅ Found user in database:')
    print(f'   User ID: {user["id"]}')
    print(f'   Email: {user["email"]}')
    print(f'   Current Stripe Customer ID: {user["stripe_customer_id"] or "MISSING"}')
    print(f'   Current Stripe Subscription ID: {user["stripe_subscription_id"] or "MISSING"}')
    print(f'   Subscription Status: {user["subscription_status"]}')
    print()

    # Search for active subscriptions in Stripe for this email
    print(f'🔍 Searching Stripe for subscriptions with email: {email}')

    try:
        # Search for customers with this email
        customers = stripe.Customer.list(email=email, limit=10)

        if not customers.data:
            print(f'❌ No Stripe customers found with email {email}')
            conn.close()
            return

        print(f'✅ Found {len(customers.data)} Stripe customer(s)')

        # Find active subscription
        active_subscription = None
        customer_id = None

        for customer in customers.data:
            print(f'\n📋 Customer: {customer.id}')
            subscriptions = stripe.Subscription.list(customer=customer.id, limit=10)

            for sub in subscriptions.data:
                print(f'   Subscription: {sub.id}')
                print(f'   Status: {sub.status}')

                if sub.status == 'active':
                    active_subscription = sub
                    customer_id = customer.id
                    print(f'   ✅ ACTIVE SUBSCRIPTION FOUND')
                    break

            if active_subscription:
                break

        if not active_subscription:
            print(f'\n❌ No active subscriptions found for {email}')
            conn.close()
            return

        print(f'\n{"="*80}')
        print(f'UPDATING DATABASE')
        print(f'{"="*80}')
        print(f'Customer ID: {customer_id}')
        print(f'Subscription ID: {active_subscription.id}')
        print()

        # Update user record
        cursor.execute('''
            UPDATE users
            SET stripe_customer_id = ?,
                stripe_subscription_id = ?,
                subscription_status = 'premium',
                generations_limit = 10
            WHERE id = ?
        ''', (customer_id, active_subscription.id, user['id']))

        conn.commit()

        # Verify update
        updated_user = cursor.execute('SELECT * FROM users WHERE id = ?', (user['id'],)).fetchone()

        print(f'✅ DATABASE UPDATED SUCCESSFULLY')
        print(f'   Stripe Customer ID: {updated_user["stripe_customer_id"]}')
        print(f'   Stripe Subscription ID: {updated_user["stripe_subscription_id"]}')
        print(f'   Subscription Status: {updated_user["subscription_status"]}')
        print(f'   Generations Limit: {updated_user["generations_limit"]}')
        print()
        print(f'✅ User {email} can now cancel their subscription!')

    except Exception as e:
        print(f'❌ Error: {str(e)}')
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 fix_stripe_link.py email@example.com')
        sys.exit(1)

    email = sys.argv[1]
    fix_stripe_link(email)
