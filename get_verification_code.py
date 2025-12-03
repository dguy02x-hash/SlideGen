#!/usr/bin/env python3
"""
Quick script to get verification code for a user when email is deferred
Usage: python3 get_verification_code.py email@example.com
"""
import sqlite3
import sys
import os

# Use production DB path if on Render, else local
DB_PATH = os.environ.get('DATABASE_PATH', 'slidegen.db')

def get_verification_code(email):
    """Get verification code for a pending subscription"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get pending subscription
    pending = cursor.execute(
        'SELECT * FROM pending_subscriptions WHERE customer_email = ? AND account_created = 0 ORDER BY created_at DESC LIMIT 1',
        (email,)
    ).fetchone()

    if not pending:
        print(f'❌ No pending subscription found for {email}')
        print(f'   They may have already completed registration or never subscribed.')
        conn.close()
        return

    print(f'\n✅ VERIFICATION CODE FOR: {email}')
    print(f'   Code: {pending["confirmation_token"][:6] if len(pending["confirmation_token"]) > 10 else pending["confirmation_token"]}')
    print(f'   Expires: {pending["token_expires_at"]}')
    print(f'   Created: {pending["created_at"]}')
    print(f'\nSend this to the user:')
    print(f'   "Your PresPilot verification code is: {pending["confirmation_token"][:6] if len(pending["confirmation_token"]) > 10 else pending["confirmation_token"]}"')
    print(f'   "Go to https://prespilot.com/confirm-email.html and enter your email and this code."')

    conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 get_verification_code.py email@example.com')
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    get_verification_code(email)
