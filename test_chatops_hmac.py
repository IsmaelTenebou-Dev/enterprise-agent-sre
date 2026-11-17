import subprocess
import time
import requests
import sys
import json
from chatops_dispatcher import ChatOpsDispatcher

def test_chatops_security():
    print("=== Testing ChatOps HMAC Security & Approval Callback ===")
    
    # 1. Spawn AI Gateway on port 8000
    gateway_proc = subprocess.Popen([sys.executable, "ai_gateway.py"])
    
    for _ in range(20):
        try:
            requests.get("http://127.0.0.1:8000/docs", timeout=0.5)
            break
        except Exception:
            time.sleep(0.5)
            
    try:
        url = "http://127.0.0.1:8000/api/v1/chatops/interactions"
        payload = {"incident_id": "ALERT-SEC-101", "action": "APPROVE", "operator": "lead-sre@allianzgi.de"}
        payload_bytes = json.dumps(payload).encode("utf-8")
        now_ts = str(int(time.time()))
        
        # Test 1: Unsigned Request
        print("\n[Test 1] Dispatching unsigned request (Expect 401 Unauthorized)...")
        r1 = requests.post(url, data=payload_bytes)
        print(f" -> Response Status: {r1.status_code}")
        assert r1.status_code == 401, f"Expected 401, got {r1.status_code}"
        print(" -> Test 1 PASSED: Unsigned request successfully blocked.")

        # Test 2: Tampered Signature
        print("\n[Test 2] Dispatching request with tampered HMAC signature (Expect 401)...")
        headers_tampered = {
            "X-Slack-Request-Timestamp": now_ts,
            "X-Slack-Signature": "v0=deadbeef1234567890abcdefdeadbeef1234567890abcdefdeadbeef12345678"
        }
        r2 = requests.post(url, data=payload_bytes, headers=headers_tampered)
        print(f" -> Response Status: {r2.status_code}")
        assert r2.status_code == 401, f"Expected 401, got {r2.status_code}"
        print(" -> Test 2 PASSED: Tampered signature successfully blocked.")

        # Test 3: Anti-Replay Attack Check (Old Timestamp)
        print("\n[Test 3] Dispatching request with expired timestamp (Replay attack simulation)...")
        old_ts = str(int(time.time()) - 400) # 400s old > 300s window
        old_sig = ChatOpsDispatcher.sign_callback_payload(payload_bytes, old_ts)
        headers_replay = {
            "X-Slack-Request-Timestamp": old_ts,
            "X-Slack-Signature": old_sig
        }
        r3 = requests.post(url, data=payload_bytes, headers=headers_replay)
        print(f" -> Response Status: {r3.status_code}")
        assert r3.status_code == 401, f"Expected 401, got {r3.status_code}"
        print(" -> Test 3 PASSED: Expired timestamp replay attack successfully blocked.")

        # Test 4: Valid Cryptographic HMAC Signature
        print("\n[Test 4] Dispatching authorized request with valid HMAC-SHA256 signature...")
        valid_sig = ChatOpsDispatcher.sign_callback_payload(payload_bytes, now_ts)
        headers_valid = {
            "X-Slack-Request-Timestamp": now_ts,
            "X-Slack-Signature": valid_sig
        }
        r4 = requests.post(url, data=payload_bytes, headers=headers_valid)
        print(f" -> Response Status: {r4.status_code}")
        print(f" -> Response Body: {r4.json()}")
        assert r4.status_code == 200, f"Expected 200, got {r4.status_code}"
        assert r4.json()["status"] == "success"
        assert r4.json()["action_taken"] == "APPROVE"
        print(" -> Test 4 PASSED: Authorized HMAC signature successfully validated and processed!")

        # Test 5: Verify Slack Block Kit Card Generator
        print("\n[Test 5] Verifying Slack Block Kit Card Generator...")
        card = ChatOpsDispatcher.generate_slack_block_kit_card(
            incident_id="INC-4091",
            severity="P1_CRITICAL",
            summary="Pod OOMKilled",
            technical_explanation="Allocated 300MB RAM breaching 256Mi limit.",
            pr_url="https://github.com/enterprise/sre-platform/pull/101",
            branch="sre-remediation/inc-4091"
        )
        assert len(card["attachments"][0]["blocks"]) >= 5
        print(f" -> Verified Block Kit Attachments: {len(card['attachments'][0]['blocks'])} blocks generated.")
        print(" -> Test 5 PASSED: Slack Block Kit incident triage card successfully generated!")

        print("\n✔ CHATOPS SECURITY & APPROVAL CALLBACK VERIFICATION PASSED 100%!")
    finally:
        gateway_proc.terminate()
        gateway_proc.wait()

if __name__ == "__main__":
    test_chatops_security()
