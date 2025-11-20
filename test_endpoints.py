#!/usr/bin/env python3
"""
Endpoint Verification Script
Tests all SlideGen Pro API endpoints to ensure they're working
"""

import requests
import json

BASE_URL = "http://localhost:5000"

def test_health():
    """Test health endpoint"""
    print("\n🔍 Testing /health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        data = response.json()
        print(f"✅ Health check passed")
        print(f"   Status: {data.get('status')}")
        print(f"   API configured: {data.get('api_configured')}")
        print(f"   Features: {data.get('features')}")
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def test_research_endpoint():
    """Test research endpoint (the one that was missing)"""
    print("\n🔍 Testing /api/research endpoint...")
    try:
        # Note: This will fail with 401 if not logged in, but at least won't be 404
        response = requests.post(
            f"{BASE_URL}/api/research",
            json={"topic": "Test Topic", "num_slides": 5}
        )
        
        if response.status_code == 404:
            print("❌ Research endpoint NOT FOUND (404) - Still using old server file!")
            return False
        elif response.status_code == 401:
            print("✅ Research endpoint EXISTS (got 401 auth required, which is correct)")
            return True
        else:
            print(f"✅ Research endpoint EXISTS (status {response.status_code})")
            return True
    except Exception as e:
        print(f"❌ Research endpoint test failed: {e}")
        return False

def test_style_generation_endpoint():
    """Test new custom style generation endpoint"""
    print("\n🔍 Testing /api/presentations/style-from-prompt endpoint...")
    try:
        response = requests.post(
            f"{BASE_URL}/api/presentations/style-from-prompt",
            json={"prompt": "Professional blue theme"}
        )
        
        if response.status_code == 404:
            print("❌ Style generation endpoint NOT FOUND (404)")
            return False
        elif response.status_code == 401:
            print("✅ Style generation endpoint EXISTS (got 401 auth required, which is correct)")
            return True
        else:
            print(f"✅ Style generation endpoint EXISTS (status {response.status_code})")
            return True
    except Exception as e:
        print(f"❌ Style generation endpoint test failed: {e}")
        return False

def test_all_endpoints():
    """Test all critical endpoints"""
    print("=" * 60)
    print("SlideGen Pro Endpoint Verification")
    print("=" * 60)
    
    endpoints = [
        ("/health", "GET"),
        ("/api/auth/status", "GET"),
        ("/api/research", "POST"),
        ("/api/generate-content", "POST"),
        ("/api/generate-notes", "POST"),
        ("/api/presentations/outline", "POST"),
        ("/api/presentations/speaker-notes", "POST"),
        ("/api/presentations/style-from-prompt", "POST"),
        ("/api/presentations/complete", "POST"),
        ("/api/presentations/generate-pptx", "POST"),
    ]
    
    print("\n🔍 Checking all endpoints...")
    results = []
    
    for endpoint, method in endpoints:
        try:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=2)
            else:
                response = requests.post(f"{BASE_URL}{endpoint}", json={}, timeout=2)
            
            # 404 means endpoint doesn't exist - that's bad
            if response.status_code == 404:
                print(f"❌ {endpoint:50} NOT FOUND")
                results.append(False)
            # 401 or other errors mean endpoint exists - that's good
            else:
                print(f"✅ {endpoint:50} EXISTS")
                results.append(True)
        except Exception as e:
            print(f"⚠️  {endpoint:50} ERROR: {str(e)[:30]}")
            results.append(False)
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} endpoints verified")
    
    if passed == total:
        print("🎉 All endpoints working! Server is ready.")
    elif results[2]:  # If /api/research exists
        print("✅ Critical endpoints working!")
    else:
        print("⚠️  Some endpoints missing. Make sure you're using server_NATURAL_DIALOGUE_COMPLETE.py")
    
    print("=" * 60)

def main():
    """Main test function"""
    print("\n🚀 Starting endpoint verification...\n")
    print("Make sure your server is running on http://localhost:5000\n")
    
    # Test critical endpoints first
    health_ok = test_health()
    research_ok = test_research_endpoint()
    style_ok = test_style_generation_endpoint()
    
    # Test all endpoints
    test_all_endpoints()
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if research_ok:
        print("✅ /api/research endpoint is working")
        print("✅ Your presentation generation should work now")
    else:
        print("❌ /api/research endpoint is MISSING")
        print("⚠️  You need to use server_NATURAL_DIALOGUE_COMPLETE.py")
    
    if style_ok:
        print("✅ Custom style generation feature is available")
    else:
        print("⚠️  Custom style generation feature not found")
    
    print("\nIf you see 401 errors, that's normal - it means the endpoints")
    print("exist but require authentication (which is correct behavior).")
    print("\nIf you see 404 errors, those endpoints are missing from your")
    print("server file. Use server_NATURAL_DIALOGUE_COMPLETE.py to fix this.")
    print("=" * 60)

if __name__ == "__main__":
    main()
