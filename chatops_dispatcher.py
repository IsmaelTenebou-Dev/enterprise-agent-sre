import os
import time
import hmac
import hashlib
import json
from typing import Dict, Any, Optional

# Shared HMAC Signing Secret for ChatOps webhook validation
CHATOPS_HMAC_SECRET = os.environ.get("CHATOPS_HMAC_SECRET", "sre-enterprise-secret-hmac-key-2026")

class ChatOpsDispatcher:
    """
    Enterprise ChatOps Notification & Approval Dispatcher.
    Generates Slack/Teams Block Kit incident cards and enforces
    HMAC-SHA256 cryptographic verification on human sign-off callbacks.
    """

    @staticmethod
    def generate_slack_block_kit_card(incident_id: str, severity: str, summary: str, technical_explanation: str, pr_url: str, branch: str) -> Dict[str, Any]:
        """Generates an enterprise-standard Slack Block Kit incident triage card."""
        color = "#E01E5A" if "P1" in severity else "#ECB22E"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 [Autonomous SRE Incident Alert] {incident_id}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:*\n`{severity}`"},
                    {"type": "mrkdwn", "text": f"*Target Environment:*\n`Kubernetes (Kind/EKS)`"},
                    {"type": "mrkdwn", "text": f"*Remediation Branch:*\n`{branch}`"},
                    {"type": "mrkdwn", "text": f"*GitOps Reconciler:*\n`ArgoCD Controller`"}
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Forensic Root Cause (Gemini 3.5 Analysis):*\n{technical_explanation}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Generated Pull Request:*\n<{pr_url}|View Remediation Diff on GitHub/GitOps>"
                }
            },
            {"type": "divider"},
            {
                "type": "actions",
                "block_id": f"sre_approval_block_{incident_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✔ Approve GitOps PR & Deploy", "emoji": True},
                        "style": "primary",
                        "value": json.dumps({"incident_id": incident_id, "action": "APPROVE"}),
                        "action_id": "approve_sre_mitigation"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✖ Reject & Escalate to Senior SRE", "emoji": True},
                        "style": "danger",
                        "value": json.dumps({"incident_id": incident_id, "action": "REJECT"}),
                        "action_id": "reject_sre_mitigation"
                    }
                ]
            }
        ]
        return {
            "attachments": [
                {
                    "color": color,
                    "blocks": blocks
                }
            ]
        }

    @staticmethod
    def sign_callback_payload(payload_bytes: bytes, timestamp: str) -> str:
        """Generates standard v0 HMAC-SHA256 signature for webhook callbacks."""
        sig_basestring = f"v0:{timestamp}:{payload_bytes.decode('utf-8')}".encode("utf-8")
        signature = hmac.new(
            CHATOPS_HMAC_SECRET.encode("utf-8"),
            sig_basestring,
            hashlib.sha256
        ).hexdigest()
        return f"v0={signature}"

    @staticmethod
    def verify_slack_signature(payload_bytes: bytes, timestamp: str, signature_header: str) -> bool:
        """
        Cryptographically verifies that the callback originates from authorized ChatOps / Slack.
        Protects against replay attacks (rejects requests older than 5 minutes).
        """
        if not timestamp or not signature_header:
            return False
            
        # 1. Anti-Replay Attack Check (5 minute threshold)
        try:
            req_time = int(timestamp)
            if abs(time.time() - req_time) > 300:
                print(f"[ChatOps Security] Rejected request: Timestamp drift exceeds 300s ({time.time() - req_time}s)")
                return False
        except ValueError:
            return False

        # 2. HMAC-SHA256 Signature Comparison
        expected_signature = ChatOpsDispatcher.sign_callback_payload(payload_bytes, timestamp)
        is_valid = hmac.compare_digest(expected_signature, signature_header)
        if not is_valid:
            print("[ChatOps Security] Rejected request: HMAC-SHA256 signature mismatch!")
        return is_valid
