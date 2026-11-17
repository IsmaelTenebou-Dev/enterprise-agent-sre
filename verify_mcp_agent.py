import psycopg
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from agent import get_compiled_graph, DB_URI

def test_mcp_agent_loop():
    print("=== SRE Agent Phase 3 Verification Loop (MCP) ===")
    
    print(f"Connecting to database checkpointer: {DB_URI}")
    connection_kwargs = {
        "autocommit": True,
        "prepare_threshold": 0,
    }
    
    with psycopg.connect(DB_URI, **connection_kwargs) as conn:
        checkpointer = PostgresSaver(conn)
        checkpointer.setup()
        
        graph = get_compiled_graph(checkpointer)
        
        # Thread ID for Phase 3 test session
        config = {"configurable": {"thread_id": "test-thread-mcp-phase3"}}
        
        initial_state = {
            "messages": ["Starting MCP-based fault analysis for deployment/faulty-service."],
            "status": "INVESTIGATING",
            "logs": "",
            "mitigation_action": "",
            "approval_status": "PENDING",
            "execution_depth": 0
        }
        
        print("\n--- Phase 1: Diagnostics and Mitigation Proposal ---")
        events = graph.stream(initial_state, config, stream_mode="values")
        for event in events:
            print(f"State status: {event.get('status')} | Depth: {event.get('execution_depth')}")
            if event.get("mitigation_action"):
                print(f"Proposed mitigation: {event.get('mitigation_action')}")
                
        state = graph.get_state(config)
        print(f"Graph execution interrupted. Next expected node: {state.next}")
        print(f"Proposed action: {state.values.get('mitigation_action')}")
        print(f"Approval status: {state.values.get('approval_status')}")
        
        assert "apply_mitigation" in state.next, "Error: Graph did not pause before apply_mitigation node."
        
        print("\n--- Phase 2: Simulating User Approval and Mitigating ---")
        print("Simulating user approval. Updating approval_status -> APPROVED...")
        graph.update_state(config, {"approval_status": "APPROVED"}, as_node="propose_mitigation")
        
        print("Resuming graph execution...")
        events_resume = graph.stream(None, config, stream_mode="values")
        for event in events_resume:
            print(f"State status: {event.get('status')} | Messages: {event.get('messages')[-1]}")
            
        final_state = graph.get_state(config)
        print(f"\nFinal status: {final_state.values.get('status')}")
        print("Final message history:")
        for msg in final_state.values.get("messages", []):
            print(f" - {msg}")
            
        assert final_state.values.get("status") in ["RESOLVED", "FAILED"], "Error: Graph did not terminate in expected terminal status."
        print("\nMCP Verification successfully completed!")

if __name__ == "__main__":
    test_mcp_agent_loop()
