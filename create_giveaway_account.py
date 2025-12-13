#!/usr/bin/env python3
"""
Standalone script to create a temporary premium giveaway account
Does not modify any existing subscription system code
"""
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = 'slidegen.db'

# Account details
EMAIL = 'free_giveaway_3@prespilot.com'
PASSWORD = 'tiktokgiveaway129348'
DAYS = 30
GENERATIONS_LIMIT = 10

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if user exists
    existing_user = cursor.execute('SELECT * FROM users WHERE email = ?', (EMAIL.lower(),)).fetchone()

    subscription_expires = datetime.now() + timedelta(days=DAYS)
    password_hash = generate_password_hash(PASSWORD)

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
        ''', (password_hash, subscription_expires.isoformat(), GENERATIONS_LIMIT,
              datetime.now().isoformat(), EMAIL.lower()))

        print(f"✅ Updated existing account: {EMAIL}")
    else:
        # Create new user
        cursor.execute('''
            INSERT INTO users
            (email, password_hash, subscription_status, subscription_expires,
             generations_limit, generations_used, last_reset)
            VALUES (?, ?, 'premium', ?, ?, 0, ?)
        ''', (EMAIL.lower(), password_hash, subscription_expires.isoformat(),
              GENERATIONS_LIMIT, datetime.now().isoformat()))

        print(f"✅ Created new account: {EMAIL}")

    conn.commit()
    conn.close()

    print()
    print("🎁 Giveaway Account Created")
    print("=" * 50)
    print(f"Email:      {EMAIL}")
    print(f"Password:   {PASSWORD}")
    print(f"Status:     Premium")
    print(f"Expires:    {subscription_expires.strftime('%Y-%m-%d at %I:%M %p')}")
    print(f"Duration:   {DAYS} days")
    print(f"Limit:      {GENERATIONS_LIMIT} presentations")
    print(f"Used:       0")
    print("=" * 50)

if __name__ == '__main__':
    main()
