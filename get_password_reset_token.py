#!/usr/bin/env python3
"""
Get password reset token for a user when email is deferred
Usage: python3 get_password_reset_token.py email@example.com
"""
import sqlite3
import sys
import os
from datetime import datetime

# Use production DB path if on Render, else local
DB_PATH = os.environ.get('DATABASE_PATH', 'slidegen.db')

def get_reset_token(email):
    """Get password reset token for a user"""
    email = email.strip().lower()

    print(f'\n{"="*80}')
    print(f'PASSWORD RESET TOKEN FOR: {email}')
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
    print(f'   Subscription Status: {user["subscription_status"]}')
    print()

    # Check for existing reset token
    reset_token = cursor.execute(
        'SELECT * FROM password_resets WHERE user_id = ? ORDER BY created_at DESC LIMIT 1',
        (user['id'],)
    ).fetchone()

    if reset_token:
        # Check if token is still valid (within 1 hour)
        created_at = datetime.fromisoformat(reset_token['created_at'])
        expires_at = datetime.fromisoformat(reset_token['expires_at'])
        now = datetime.now()

        if now < expires_at:
            print(f'✅ ACTIVE RESET TOKEN FOUND:')
            print(f'   Token: {reset_token["token"]}')
            print(f'   Created: {reset_token["created_at"]}')
            print(f'   Expires: {reset_token["expires_at"]}')
            print(f'\n🔗 Reset Link:')
            print(f'   https://prespilot.com/reset-password.html?token={reset_token["token"]}')
            print(f'\n📧 Send this to the user:')
            print(f'   "Click this link to reset your password: https://prespilot.com/reset-password.html?token={reset_token["token"]}"')
            print(f'   "This link expires in 1 hour."')
        else:
            print(f'❌ Previous reset token has expired')
            print(f'   Token expired at: {reset_token["expires_at"]}')
            print(f'   User needs to request a new password reset')
    else:
        print(f'❌ No password reset token found')
        print(f'   User needs to request a password reset at https://prespilot.com')

    conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 get_password_reset_token.py email@example.com')
        sys.exit(1)

    email = sys.argv[1]
    get_reset_token(email)
