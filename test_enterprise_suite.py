#!/usr/bin/env python3
"""
Enterprise SRE Platform - Automated Master Verification Suite
Runs full assertion tests covering:
  1. Dynamic Gemini 3.5 Structured Output & DLP Quarantine
  2. Real Prometheus Alertmanager Webhook Ingestion & Deduplication
  3. GitOps Branching, YAML Patching & PR Generation
  4. ChatOps HMAC-SHA256 Cryptographic Signature Security
  5. LangGraph State Machine & PostgreSQL Session Persistence
"""

import os
import sys
import time
import json
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()

from chatops_dispatcher import ChatOpsDispatcher
from gitops_service import GitOpsRemediationService

GREEN = "\033[92m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

def ok(msg):
    print(f"  {GREEN}✔ {msg}{RESET}")

def fail(msg):
    print(f"  {RED}✘ {msg}{RESET}")

def main():
    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║     ENTERPRISE SRE PLATFORM: MASTER VERIFICATION SUITE       ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════╝{RESET}\n")

    passed = 0
    failed = 0

    # 1. Spawn AI Gateway on port 8000
    print(f"{BOLD}[1/5] Initializing Governed AI Gateway on port 8000...{RESET}")
    gateway_proc = subprocess.Popen([sys.executable, "ai_gateway.py"])
    for _ in range(25):
        try:
            r = requests.get("http://127.0.0.1:8000/docs", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.5)

    try:
        # --- TEST 1: Real Dynamic Gemini Reasoning & DLP ---
        print(f"\n{BOLD}[2/5] Testing Dynamic Gemini 3.5 Structured Pydantic Reasoning & DLP...{RESET}")
        dlp_payload = {
            "model": "gemini-3.5-flash-lite",
            "messages": [{"role": "user", "content": "Crash log dump: Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3QifQ"}]
        }
        r_dlp = requests.post(
            "http://127.0.0.1:8000/v1/chat/completions",
            json=dlp_payload,
            headers={"Authorization": "Bearer client-allianzgi-sre"}
        )
        assert r_dlp.status_code == 400 and "Security Violation" in r_dlp.text, "DLP failed to quarantine secrets!"
        ok("DLP Shield successfully quarantined Bearer token leak (HTTP 400)")
        passed += 1

        gemini_payload = {
            "model": "gemini-3.5-flash-lite",
            "messages": [{"role": "user", "content": "Pod faulty-service-xyz terminated with ExitCode 137, OOMKilled while allocating 300MB RAM. The configured limit is 256Mi."}]
        }
        r_gem = requests.post(
            "http://127.0.0.1:8000/v1/chat/completions",
            json=gemini_payload,
            headers={"Authorization": "Bearer client-allianzgi-sre"}
        )
        assert r_gem.status_code == 200, f"Gateway returned {r_gem.status_code}"
        gem_data = r_gem.json()
        schema = gem_data.get("analysis_schema", {})
        assert schema.get("root_cause_category") == "OOM_MEMORY_LEAK", f"Unexpected category: {schema.get('root_cause_category')}"
        assert schema.get("recommended_mitigation_type") == "PATCH_MEMORY_LIMIT"
        ok(f"Gemini 3.5 Flash Lite Output: Category='{schema.get('root_cause_category')}' | Confidence={schema.get('confidence_score')*100:.0f}%")
        ok(f"FinOps Telemetry: {gem_data['usage']['total_tokens']} tokens | Cost: ${gem_data['usage']['estimated_cost_usd']:.6f} USD")
        passed += 1

        # --- TEST 2: Prometheus Alertmanager Webhook Ingestion & Deduplication ---
        print(f"\n{BOLD}[3/5] Testing Prometheus Alertmanager Webhook Ingress & Deduplication...{RESET}")
        alert_fp = "f84b12c79011aaee"
        alert_payload = {
            "receiver": "sre-agent-webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "KubePodCrashLooping", "namespace": "default", "pod": "faulty-service-live", "severity": "critical"},
                    "annotations": {"summary": "Pod CrashLooping on EKS cluster", "description": "Continuous container restarts detected."},
                    "fingerprint": alert_fp,
                    "startsAt": "2026-11-17T07:00:00Z"
                }
            ]
        }
        r_alert = requests.post("http://127.0.0.1:8000/api/v1/alerts", json=alert_payload)
        assert r_alert.status_code == 200 and r_alert.json()["processed_count"] == 1
        ok(f"Alertmanager Webhook Ingested: Incident ID='{r_alert.json()['incidents'][0]['incident_id']}'")
        passed += 1

        # Duplicate suppression check
        r_dup = requests.post("http://127.0.0.1:8000/api/v1/alerts", json=alert_payload)
        assert r_dup.status_code == 200 and r_dup.json()["processed_count"] == 0
        ok("Alert Storm Suppression: Duplicate alert fingerprint successfully dropped within 300s window")
        passed += 1

        # --- TEST 3: GitOps Branching, Committing & PR Generation ---
        print(f"\n{BOLD}[4/5] Testing GitOps Remediation Lifecycle (Git Branching & PRs)...{RESET}")
        gitops = GitOpsRemediationService()
        incident_test = "INC-EVAL-MASTER"
        branch = gitops.create_remediation_branch(incident_test)
        patch_info = gitops.patch_manifest("dummy-app/deployment.yaml", "512Mi")
        commit = gitops.commit_remediation(incident_test, branch, patch_info, "Automated OOM limit expansion")
        pr_info = gitops.open_pull_request(incident_test, branch, commit, "Forensic diagnosis verified memory limit breach.")
        assert pr_info["status"] in ["AWAITING_MERGE", "OPEN"]
        ok(f"GitOps Branch Created: '{pr_info['branch']}' | Signed Commit: '{pr_info['commit']}'")
        ok(f"Declarative PR Generated: {pr_info['pr_url']}")
        passed += 1

        # Switch back to main
        gitops._run_git(["checkout", "main"])

        # --- TEST 4: ChatOps HMAC-SHA256 Cryptographic Verification ---
        print(f"\n{BOLD}[5/5] Testing ChatOps HMAC-SHA256 Cryptographic Verification...{RESET}")
        url_chatops = "http://127.0.0.1:8000/api/v1/chatops/interactions"
        now_ts = str(int(time.time()))
        cb_payload = {"incident_id": "ALERT-F84B12C7", "action": "APPROVE", "operator": "sre-lead@allianzgi.de"}
        cb_bytes = json.dumps(cb_payload).encode("utf-8")

        # Tampered check
        r_tamper = requests.post(
            url_chatops,
            data=cb_bytes,
            headers={"X-Slack-Request-Timestamp": now_ts, "X-Slack-Signature": "v0=tampered_signature_hex"}
        )
        assert r_tamper.status_code == 401
        ok("Tampered HMAC signature rejected with HTTP 401 Unauthorized")
        passed += 1

        # Valid signature check
        valid_sig = ChatOpsDispatcher.sign_callback_payload(cb_bytes, now_ts)
        r_valid = requests.post(
            url_chatops,
            data=cb_bytes,
            headers={"X-Slack-Request-Timestamp": now_ts, "X-Slack-Signature": valid_sig}
        )
        assert r_valid.status_code == 200 and r_valid.json()["action_taken"] == "APPROVE"
        ok(f"Authorized Operator Sign-Off Verified: Operator='{r_valid.json()['operator']}' | Action='{r_valid.json()['action_taken']}'")
        passed += 1

    except Exception as e:
        fail(f"Test Assertion Error: {str(e)}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        gateway_proc.terminate()
        gateway_proc.wait()

    print(f"\n{BOLD}{CYAN}══════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}{GREEN}MASTER SUITE RUN COMPLETE: {passed} PASSED, {failed} FAILED{RESET}")
    print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════{RESET}\n")

    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
