import subprocess
import time
import requests
import sys
from agent import pool, extract_tenant_context

def run_enterprise_verification():
    print("=== SRE Agent Phase 5 Enterprise Verification ===")
    
    # 1. Spawn AI Gateway proxy in background
    print("\n[Step 1] Spawning AI Gateway server on port 8000...")
    gateway_proc = subprocess.Popen(
        [sys.executable, "ai_gateway.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for gateway to become available
    url = "http://127.0.0.1:8000/v1/chat/completions"
    headers = {"Authorization": "Bearer client-allianzgi-sre"}
    
    for _ in range(10):
        if gateway_proc.poll() is not None:
            stdout, stderr = gateway_proc.communicate()
            raise RuntimeError(f"AI Gateway failed to start: {stderr}")
        try:
            requests.get("http://127.0.0.1:8000/docs", timeout=0.5)
            break
        except requests.exceptions.RequestException:
            time.sleep(0.5)
    
    passed = 0
    failed = 0
    
    try:
        # 2. Verify connection pool & multi-tenancy context
        print("\n[Step 2] Testing connection pool and thread prefix extraction...")
        # Get connection from psycopg_pool connection pool
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                res = cur.fetchone()
                assert res[0] == 1, "Failed connection pool fetch!"
        print(" -> Pool connection successfully verified!")
        passed += 1
        
        tenant_id, thread_id = extract_tenant_context({"configurable": {"thread_id": "allianzgi:fault-9524"}})
        assert tenant_id == "allianzgi"
        assert thread_id == "fault-9524"
        print(" -> Tenant context parsing successfully verified!")
        passed += 1
        
        # 3. Verify AI Gateway completions & Rate limiting
        print("\n[Step 3] Querying AI Gateway for crash diagnostic recommendation...")
        payload = {
            "model": "mock-claude-3-5",
            "messages": [{"role": "user", "content": "Application crashed with exit code 137. OOMKilled"}]
        }
        resp = requests.post(url, json=payload, headers=headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        print(f" -> AI Gateway response: {data['choices'][0]['message']['content']}")
        assert "512Mi" in data['choices'][0]['message']['content']
        print(" -> AI Gateway completion recommendation successfully verified!")
        passed += 1
        
        # 4. Verify DLP Data Loss Prevention (Security filter blocking tokens)
        print("\n[Step 4] Testing security filtering (DLP) blocker...")
        # Inject standard fake JWT in request messages (should be blocked by DLP)
        payload_token = {
            "model": "mock-claude-3-5",
            "messages": [{"role": "user", "content": "Dump logs: Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Ik1vY2sifQ"}]
        }
        resp_dlp = requests.post(url, json=payload_token, headers=headers)
        print(f" -> Response Status: {resp_dlp.status_code}")
        print(f" -> Response Details: {resp_dlp.text}")
        assert resp_dlp.status_code == 400, f"DLP did not trigger! Expected status 400, got {resp_dlp.status_code}"
        assert "Security Violation" in resp_dlp.text, "Error details missing security warning!"
        print(" -> DLP blocked JWT token successfully!")
        passed += 1
        
    except Exception as e:
        print(f" -> Enterprise Verification FAILED: {str(e)}")
        failed += 1
    finally:
        # Terminate gateway
        print("\n[Cleanup] Stopping AI Gateway server...")
        gateway_proc.terminate()
        gateway_proc.wait()
        
    print(f"\nEnterprise run results: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    run_enterprise_verification()
