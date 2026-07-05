#!/usr/bin/env python3
"""Utility script to create and seed an active sandbox in ThinkDome.

Usage:
    python3 create_test_sandbox.py
"""

import sys
import httpx

API_URL = "http://localhost:8000"

def main():
    print("🔑 Authenticating as admin...")
    try:
        login_resp = httpx.post(
            f"{API_URL}/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=10.0
        )
        login_resp.raise_for_status()
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        print("Please ensure the ThinkDome API is running: uvicorn thinkdome.server:create_app --host 0.0.0.0 --port 8000 --factory")
        sys.exit(1)

    token = login_resp.json()["access_token"]
    print(f"✅ Authenticated! Token: {token[:12]}...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 1. Create a sandbox
    print("\n📦 Renting/creating a new active sandbox...")
    sandbox_data = {
        "name": "ide-sandbox",
        "memory_mb": 512,
        "cpu_cores": 1.0,
        "timeout_sec": 3600,
        "network_enabled": True
    }

    try:
        sb_resp = httpx.post(
            f"{API_URL}/v1/admin/sandboxes",
            json=sandbox_data,
            headers=headers,
            timeout=10.0
        )
        sb_resp.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to create sandbox: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"   Details: {e.response.text}")
        sys.exit(1)

    sb_info = sb_resp.json()
    sandbox_id = sb_info.get("sandbox_id")
    print(f"✅ Sandbox successfully created!")
    print(f"   - Sandbox ID: {sandbox_id}")
    print(f"   - Name: {sb_info.get('name')}")
    print(f"   - Owner: {sb_info.get('owner')}")
    print(f"   - Memory Limit: {sb_info.get('memory_mb')} MB")
    print(f"   - Network Access: {sb_info.get('network_enabled')}")

    # 2. Try orchestrating a quick code run to verify it works
    print("\n⚡ Testing execution orchestration in the new sandbox...")
    exec_payload = {
        "id": "init_verify_job",
        "type": "tool_use",
        "name": "run_code",
        "input": {
            "language": "python",
            "code": "print('Hello from the newly provisioned sandbox!')"
        }
    }
    
    # We supply the X-Sandbox-Id header to route to our specific sandbox
    headers["X-Sandbox-Id"] = sandbox_id

    try:
        exec_resp = httpx.post(
            f"{API_URL}/v1/orchestrate",
            json=exec_payload,
            headers=headers,
            timeout=15.0
        )
        exec_resp.raise_for_status()
        print(f"✅ Execution verified successfully!")
        print(f"   Result Output: {exec_resp.json().get('content')}")
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"   Details: {e.response.text}")

if __name__ == "__main__":
    main()
