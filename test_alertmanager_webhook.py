import subprocess
import time
import requests
import sys

def test_alertmanager_ingestion():
    print("=== Testing Prometheus Alertmanager Webhook Ingress ===")
    
    # 1. Spawn AI Gateway on port 8000
    gateway_proc = subprocess.Popen([sys.executable, "ai_gateway.py"])
    
    # Wait for gateway to accept traffic
    for _ in range(20):
        try:
            requests.get("http://127.0.0.1:8000/docs", timeout=0.5)
            break
        except Exception:
            time.sleep(0.5)
            
    try:
        # Standard Prometheus Alertmanager v4 JSON format
        alert_payload = {
            "receiver": "sre-agent-webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "KubePodCrashLooping",
                        "namespace": "default",
                        "pod": "faulty-service-5cff58658b-mnb95",
                        "severity": "critical"
                    },
                    "annotations": {
                        "summary": "Pod faulty-service is in CrashLoopBackOff",
                        "description": "Container faulty-service terminated with ExitCode 127. Process exited prematurely."
                    },
                    "fingerprint": "b73a9821cd8844fa",
                    "startsAt": "2026-11-17T06:45:00Z"
                }
            ]
        }
        
        print("\n[Step 1] Dispatching firing Alertmanager webhook to http://127.0.0.1:8000/api/v1/alerts...")
        resp = requests.post("http://127.0.0.1:8000/api/v1/alerts", json=alert_payload)
        print(f" -> Response Status: {resp.status_code}")
        data = resp.json()
        print(f" -> Response Body: {data}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert data["processed_count"] == 1, "Expected 1 incident processed!"
        incident = data["incidents"][0]
        print(f" -> Verified Incident Spawned: {incident['incident_id']} (Thread: {incident['thread_id']})")
        
        # 2. Test Deduplication
        print("\n[Step 2] Dispatching duplicate firing alert (Testing deduplication suppression)...")
        resp_dup = requests.post("http://127.0.0.1:8000/api/v1/alerts", json=alert_payload)
        data_dup = resp_dup.json()
        print(f" -> Duplicate Response Body: {data_dup}")
        assert data_dup["processed_count"] == 0, "Duplicate alert was NOT suppressed!"
        print(" -> Alert deduplication successfully suppressed duplicate incident storm!")
        
        # 3. Wait for agent to triage in background
        print("\n[Step 3] Waiting for LangGraph agent to triage alert in background...")
        from agent import pool, get_compiled_graph
        from langgraph.checkpoint.postgres import PostgresSaver

        state = None
        for _ in range(20):
            time.sleep(1)
            with pool.connection() as conn:
                checkpointer = PostgresSaver(conn)
                checkpointer.setup()
                graph = get_compiled_graph(checkpointer)
                state = graph.get_state({"configurable": {"thread_id": incident["thread_id"]}})
                if "apply_mitigation" in state.next:
                    break

        print(f" -> Checkpointed Next Node: {state.next}")
        print(f" -> Checkpointed Status: {state.values.get('status')}")
        print(f" -> Checkpointed Action: {state.values.get('mitigation_action')}")
        assert "apply_mitigation" in state.next, "Agent failed to reach HITL gate for alert incident!"
        print(" -> LangGraph checkpointer state verified in PostgreSQL for Alertmanager incident!")
            
        print("\n✔ ALERTMANAGER WEBHOOK INGESTION VERIFICATION PASSED 100%!")
    finally:
        gateway_proc.terminate()
        gateway_proc.wait()

if __name__ == "__main__":
    test_alertmanager_ingestion()
