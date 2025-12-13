#!/usr/bin/env python3
"""
Script to grant premium subscription to a user
"""
import sqlite3
from datetime import datetime
import hashlib

DB_PATH = 'slidegen.db'

def grant_premium(email):
    """Grant premium subscription to a user"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if user exists
    user = cursor.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()

    if user:
        # User exists - update to premium
        cursor.execute('''
            UPDATE users
            SET subscription_status = 'premium',
                generations_limit = 10,
                generations_used = 0,
                last_reset = ?
            WHERE email = ?
        ''', (datetime.now().isoformat(), email.lower()))

        conn.commit()
        conn.close()

        print(f"✅ Updated {email} to premium subscription")
        print(f"   - Status: premium")
        print(f"   - Monthly limit: 10 presentations")
        print(f"   - Generations used: 0 (reset)")
    else:
        # User doesn't exist - create with premium
        # Generate a default password hash (user can reset it later)
        default_password = "changeme123"
        password_hash = hashlib.sha256(default_password.encode()).hexdigest()

        cursor.execute('''
            INSERT INTO users (email, password_hash, subscription_status, generations_limit, generations_used, last_reset)
            VALUES (?, ?, 'premium', 10, 0, ?)
        ''', (email.lower(), password_hash, datetime.now().isoformat()))

        conn.commit()
        conn.close()

        print(f"✅ Created new premium user: {email}")
        print(f"   - Status: premium")
        print(f"   - Monthly limit: 10 presentations")
        print(f"   - Default password: {default_password}")
        print(f"   - User should change password after first login")

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python grant_premium.py <email>")
        sys.exit(1)

    email = sys.argv[1]
    grant_premium(email)
