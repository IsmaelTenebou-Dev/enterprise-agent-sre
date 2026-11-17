import sys
from langgraph.checkpoint.postgres import PostgresSaver
from agent import get_compiled_graph, DB_URI, SREState

## Diagnostic test suite for Phase 2 LangGraph SRE state machine execution
def main():
    print("=== SRE Agent Verification Test Harness ===")
    
    ## 1. Establish connections to the postgres checkpointer container
    print(f"Connecting to database: {DB_URI}")
    try:
        ## using context manager to initialize PgSaver and perform migration tables setup
        with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
            checkpointer.setup()
            print("Postgres checkpointer connection established, table schemas initialized.")
            
            ## Compile the graph using checkpointer instance
            graph = get_compiled_graph(checkpointer)
            
            ## Define configuration parameter containing thread identifier
            # Using a random or hardcoded thread_id to identify this run
            thread_config = {"configurable": {"thread_id": "sre-thread-101"}}
            
            ## Initialize default input state values
            initial_state = {          
                "messages": ["User-triggered SRE cluster evaluation check."],
                "status": "START",
                "logs": "",
                "mitigation_action": "",
                "approval_status": "PENDING",
                "execution_depth": 0
            }
            
            print("\n--- Starting graph execution loop ---")
            ## 2. Trigger initial stream execution. This runs: diagnose -> propose_mitigation -> stops at apply_mitigation interrupt.
            events = graph.stream(initial_state, thread_config, stream_mode="values")
            last_state = None
            for event in events:
                last_state = event
                print(f"Node Transition -> Status: {event.get('status')}, Msg count: {len(event.get('messages', []))}")
                
            ## 3. Verify that the execution halted at the interrupt boundary
            current_state = graph.get_state(thread_config)
            print(f"\nGraph interrupted? {len(current_state.next) > 0}")
            print(f"Next Node to Execute: {current_state.next}")
            print(f"Current State Status: {current_state.values.get('status')}")
            print(f"Approval Status: {current_state.values.get('approval_status')}")
            print(f"Proposed Action: {current_state.values.get('mitigation_action')}")
            
            ## Confirm that the state matches expected intermediate boundary conditions
            assert "apply_mitigation" in current_state.next, "Verification Error: Graph failed to interrupt before mitigation step!"
            assert current_state.values.get("status") == "PROPOSED", "Verification Error: Unexpected end state status!"
            
            ## 4. Simulate user human-in-the-loop input (slack button click / CLI approval)
            print("\n--- Simulating User Approval Gate Update ---")
            # Update state with approved status. We merge current config values
            graph.update_state(
                thread_config,
                {"approval_status": "APPROVED", "messages": current_state.values.get("messages", []) + ["User approved SRE action."]},
                as_node="propose_mitigation"
            )
            
            ## 5. Resume execution by submitting None values to the stream
            print("\n--- Resuming graph execution loop ---")
            resume_events = graph.stream(None, thread_config, stream_mode="values")
            final_state = None
            for event in resume_events:
                final_state = event
                print(f"Node Transition -> Status: {event.get('status')}, Msg count: {len(event.get('messages', []))}")
                
            print("\n--- Final Execution State Verification ---")
            post_resume_state = graph.get_state(thread_config)
            print(f"Next Nodes remaining: {post_resume_state.next} (expecting empty)")
            print(f"Final State Status: {post_resume_state.values.get('status')}")
            
            # Assert execution resolved/finished successfully
            assert len(post_resume_state.next) == 0, "Verification Error: Graph has remaining nodes pending!"
            assert post_resume_state.values.get("status") in ["RESOLVED", "FAILED"], "Verification Error: Final status is invalid!"
            
            print("\n>>> SUCCESS: All Phase 2 SRE Agent graph and HITL checks have passed!")
            
    except Exception as e:
        print(f"\n!!! EXCEPTION raised during verification check: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
