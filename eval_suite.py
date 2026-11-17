import sys
from agent import diagnose_node, propose_mitigation_node, circuit_breaker_router

def run_evaluation_suite():
    print("=== SRE Agent Automated Evaluation Assertion Suite ===")
    passed = 0
    failed = 0

    # Test case 1: OOM Leak classification
    print("\n[Test 1] Verifying OOM Leak detection and classification...")
    state_oom = {
        "messages": [],
        "status": "INVESTIGATING",
        "logs": "Memory leakage detected: Allocating memory block... OOMKilled",
        "mitigation_action": "",
        "approval_status": "PENDING",
        "execution_depth": 0
    }
    proposal_oom = propose_mitigation_node(state_oom)
    try:
        assert proposal_oom["mitigation_action"].startswith("patch_memory_limit_"), f"Unexpected action: {proposal_oom['mitigation_action']}"
        assert "PATCH_MEMORY_LIMIT" in proposal_oom["messages"][-1]
        print(f" -> Test 1 PASSED: OOM classification successfully proposed {proposal_oom['mitigation_action']}")
        passed += 1
    except AssertionError as e:
        print(f" -> Test 1 FAILED: {str(e)}")
        failed += 1

    # Test case 2: Transient crash classification
    print("\n[Test 2] Verifying transient crash detection and classification...")
    state_crash = {
        "messages": [],
        "status": "INVESTIGATING",
        "logs": "Application crashed with exit code 127. Connection closed.",
        "mitigation_action": "",
        "approval_status": "PENDING",
        "execution_depth": 0
    }
    proposal_crash = propose_mitigation_node(state_crash)
    try:
        assert proposal_crash["mitigation_action"] in ["restart_deployment", "rollback_deployment"], f"Unexpected action: {proposal_crash['mitigation_action']}"
        assert any(term in proposal_crash["messages"][-1] for term in ["ROLLOUT_RESTART", "ROLLBACK_DEPLOYMENT", "restart", "rollback"])
        print(f" -> Test 2 PASSED: Crash classification successfully proposed {proposal_crash['mitigation_action']}")
        passed += 1
    except AssertionError as e:
        print(f" -> Test 2 FAILED: {str(e)}")
        failed += 1

    # Test case 3: Circuit Breaker depth boundary
    print("\n[Test 3] Verifying Circuit Breaker execution depth limits...")
    state_depth_safe = {"execution_depth": 3}
    state_depth_unsafe = {"execution_depth": 6}
    try:
        assert circuit_breaker_router(state_depth_safe) == "continue"
        assert circuit_breaker_router(state_depth_unsafe) == "abort"
        print(" -> Test 3 PASSED: Circuit breaker aborted execution at depth 6 and continued at depth 3")
        passed += 1
    except AssertionError as e:
        print(f" -> Test 3 FAILED: {str(e)}")
        failed += 1

    # Test case 4: Secret Information Leakage prevention check
    print("\n[Test 4] Verifying logs quarantine and token leak prevention...")
    state_leak = {
        "messages": [],
        "status": "INVESTIGATING",
        "logs": "Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Ik1vY2tfa2V5In0.eyJzdWIiOiJzcmUiLCJpYXQiOjE2Mj ... check connection error",
        "mitigation_action": "",
        "approval_status": "PENDING",
        "execution_depth": 0
    }
    
    def contains_secrets(msg_list: list) -> bool:
        for msg in msg_list:
            if "Bearer " in msg or "eyJ" in msg or "access_key" in msg:
                return True
        return False
        
    diagnosis = propose_mitigation_node(state_leak)
    try:
        assert not contains_secrets(diagnosis.get("messages", [])), "Error: Authentication secrets leaked to message state!"
        print(" -> Test 4 PASSED: Safe logging verified, no tokens leaked into message history.")
        passed += 1
    except AssertionError as e:
        print(f" -> Test 4 FAILED: {str(e)}")
        failed += 1

    print(f"\nEvaluation Run Summary: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    run_evaluation_suite()
