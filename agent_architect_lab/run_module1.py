"""
Module 1 Execution Script (run_module1.py)

Runs the basic 2-node graph and prints how SREState updates across nodes.
"""

from graph import build_basic_graph

def main():
    print("=" * 60)
    print("🚀 MODULE 1: Testing Basic LangGraph State Flow")
    print("=" * 60)
    
    # 1. Compile the graph
    app = build_basic_graph()
    
    # 2. Initial state passed to the graph
    initial_state = {
        "messages": ["Triggering incident investigation."],
        "target_service": "payment-service",
        "status": "INITIALIZED",
        "proposed_patch": ""
    }
    
    print("\n📥 Initial Input State:")
    print(f"   Target Service: {initial_state['target_service']}")
    print(f"   Status: {initial_state['status']}")
    
    # 3. Invoke the graph
    final_state = app.invoke(initial_state)
    
    # 4. Print final state
    print("\n" + "=" * 60)
    print("🏁 FINAL STATE OUTPUT:")
    print("=" * 60)
    print(f"Status: {final_state['status']}")
    print(f"\nMessage History ({len(final_state['messages'])} items):")
    for idx, msg in enumerate(final_state['messages'], 1):
        print(f"  {idx}. {msg}")
        
    print("\nProposed Patch Generated:")
    print(final_state['proposed_patch'])
    print("=" * 60)

if __name__ == "__main__":
    main()
