#!/usr/bin/env python3
"""
Script to create temporary premium subscription accounts
Safe to commit - no hardcoded credentials
"""
import sqlite3
import sys
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

def create_temp_premium(email, password, days=30, generations_limit=10):
    """Create a temporary premium account that expires after specified days"""

    # Use production path if DATABASE_PATH env var is set, otherwise local
    DB_PATH = os.environ.get('DATABASE_PATH', 'slidegen.db')

    print(f"\n🔧 Using database: {DB_PATH}")

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if user exists
        existing_user = cursor.execute('SELECT * FROM users WHERE email = ?', (email.lower(),)).fetchone()

        subscription_expires = datetime.now() + timedelta(days=days)
        password_hash = generate_password_hash(password)

        if existing_user:
            # Update existing user
            cursor.execute('''
                UPDATE users
                SET password_hash = ?,
                    subscription_status = 'premium',
                    subscription_expires = ?,
                    generations_limit = ?,
                    generations_used = 0,
                    last_reset = ?
                WHERE email = ?
            ''', (password_hash, subscription_expires.isoformat(), generations_limit,
                  datetime.now().isoformat(), email.lower()))

            print(f"✅ Updated existing account: {email}")
        else:
            # Create new user
            cursor.execute('''
                INSERT INTO users
                (email, password_hash, subscription_status, subscription_expires,
                 generations_limit, generations_used, last_reset)
                VALUES (?, ?, 'premium', ?, ?, 0, ?)
            ''', (email.lower(), password_hash, subscription_expires.isoformat(),
                  generations_limit, datetime.now().isoformat()))

            print(f"✅ Created new account: {email}")

        conn.commit()
        conn.close()

        print()
        print("🎁 Temporary Premium Account Details")
        print("=" * 60)
        print(f"Email:           {email}")
        print(f"Status:          Premium")
        print(f"Expires:         {subscription_expires.strftime('%Y-%m-%d at %I:%M %p')}")
        print(f"Duration:        {days} days")
        print(f"Generation Limit: {generations_limit} presentations")
        print(f"Used:            0")
        print("=" * 60)
        print()

        return True

    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 create_temp_premium.py <email> <password> [days] [limit]")
        print()
        print("Arguments:")
        print("  email       Email address for the account")
        print("  password    Password for the account")
        print("  days        Duration in days (default: 30)")
        print("  limit       Monthly generation limit (default: 10)")
        print()
        print("Examples:")
        print("  python3 create_temp_premium.py user@example.com password123")
        print("  python3 create_temp_premium.py user@example.com password123 7 5")
        print()
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10

    success = create_temp_premium(email, password, days, limit)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
