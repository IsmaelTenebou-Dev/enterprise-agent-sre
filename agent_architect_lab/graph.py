"""
Module 1: Graph Topology (graph.py)

Concept: StateGraph defines Nodes (States/Functions) and Edges (Transitions/Routing).
Node 1 (diagnose_issue): Simulates reading logs and identifying the failure.
Node 2 (propose_fix): Generates a proposed remediation patch.
"""

from langgraph.graph import StateGraph, START, END
from state import SREState

def diagnose_issue(state: SREState) -> dict:
    """Node 1: Inspects the target microservice and identifies the root cause."""
    service = state.get("target_service", "unknown-service")
    print(f"\n🔍 [Node: diagnose_issue] Investigating service: '{service}'...")
    
    # Simulate diagnostic output
    diagnostic_msg = f"Diagnosed '{service}': Detected Out-Of-Memory (OOMKilled, Exit Code 137). Current memory limit 256Mi is exceeded."
    
    return {
        "messages": [diagnostic_msg],
        "status": "DIAGNOSED_OOM"
    }

def propose_fix(state: SREState) -> dict:
    """Node 2: Generates a proposed YAML remediation patch."""
    print("🛠️  [Node: propose_fix] Generating remediation patch...")
    
    patch = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service
spec:
  template:
    spec:
      containers:
      - name: app
        resources:
          limits:
            memory: "512Mi" # Increased from 256Mi"""
            
    summary_msg = "Proposed Patch: Increase container memory limit from 256Mi to 512Mi."
    
    return {
        "messages": [summary_msg],
        "proposed_patch": patch,
        "status": "PATCH_PROPOSED"
    }

def build_basic_graph():
    """Assembles the StateGraph topology."""
    workflow = StateGraph(SREState)
    
    # Add Nodes
    workflow.add_node("diagnose_issue", diagnose_issue)
    workflow.add_node("propose_fix", propose_fix)
    
    # Define Edges (Routing)
    workflow.add_edge(START, "diagnose_issue")
    workflow.add_edge("diagnose_issue", "propose_fix")
    workflow.add_edge("propose_fix", END)
    
    # Compile Graph
    return workflow.compile()
