import os
import subprocess
import json
import asyncio
from typing import TypedDict, List
from dotenv import load_dotenv

# Load LangSmith and platform environment variables
load_dotenv()

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from psycopg_pool import ConnectionPool

## Database connection string to target our postgres checkpointer
DB_URI = "postgresql://sre_user:sre_password@localhost:5433/sre_state_db"

## Initialize psycopg Connection Pool for high concurrency scalability
pool = ConnectionPool(
    conninfo=DB_URI,
    min_size=2,
    max_size=20,
    open=True,
    kwargs={"autocommit": True, "prepare_threshold": 0}
)

class SREState(TypedDict):
    """
    SREState represents the shared state variables passed between graph nodes.
    This schema maintains trace information, system findings, and structural checkpoints.
    """
    messages: List[str]            ## Message history trace of current diagnostic thread
    status: str                    ## Overall state machine phase: INVESTIGATING, PROPOSED, MITIGATING, RESOLVED, FAILED
    logs: str                      ## Log traces pulled from kubernetes faulty-service
    mitigation_action: str         ## Structural action recommended (e.g. increase memory allocation limit)
    approval_status: str           ## Gateway verification status: PENDING, APPROVED, DENIED
    execution_depth: int           ## Loop loop invocation counters acting as a circuit breaker

def call_mcp_tool(tool_name: str, arguments: dict = None) -> str:
    """Helper to synchronously spawn the MCP server, invoke a tool, and return result text."""
    if arguments is None:
        arguments = {}
    async def run():
        server_params = StdioServerParameters(
            command="./venv/bin/python",
            args=["sre_mcp_server.py"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool_name, arguments=arguments)
                if res.content and len(res.content) > 0:
                    return res.content[0].text
                return ""
    try:
        return asyncio.run(run())
    except Exception as e:
        return f"MCP Tool execution failed: {str(e)}"

def read_mcp_resource(uri: str) -> str:
    """Helper to synchronously spawn the MCP server, read a resource, and return value."""
    async def run():
        server_params = StdioServerParameters(
            command="./venv/bin/python",
            args=["sre_mcp_server.py"],
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.read_resource(uri)
                if res.contents and len(res.contents) > 0:
                    return res.contents[0].text
                return ""
    try:
        return asyncio.run(run())
    except Exception as e:
        return f"MCP Resource read failed: {str(e)}"

def diagnose_node(state: SREState) -> dict:
    """
    Inspects the Kubernetes environment using the SRE MCP server
    to check pod status and grab AWS cost information.
    """
    print(">>> SRE Agent [Node: Diagnose] checking cluster via MCP...")
    
    ## 1. Read the AWS Cost monthly summary resource
    cost_info = read_mcp_resource("aws://cost-explorer/monthly-summary")
    cost_msg = f"Audited EKS cost footprint from MCP: {cost_info}"
    
    ## 2. Retrieve pod lists through MCP Server
    res_pods = call_mcp_tool("get_pods", {"namespace": "default"})
    if "Error" in res_pods or not res_pods:
        return {
            "status": "FAILED",
            "messages": state["messages"] + [f"Failed to fetch pods via MCP: {res_pods}"]
        }
        
    lines = res_pods.split("\n")
    pod_name = None
    pod_status = "Unknown"
    for line in lines:
        if "faulty-service-" in line:
            parts = line.split(" | ")
            pod_name = parts[0].split(": ")[1].strip()
            pod_status = parts[1].split(": ")[1].strip()
            break
            
    if not pod_name:
        return {
            "status": "FAILED",
            "messages": state["messages"] + ["No active faulty-service pods detected in default namespace.", cost_msg]
        }
        
    ## 3. Retrieve pod logs through MCP Server
    log_content = call_mcp_tool("get_pod_logs", {"pod_name": pod_name, "namespace": "default"})
    debug_msg = f"Diagnosed pod {pod_name} in state '{pod_status}' via MCP."
    
    return {
        "status": "INVESTIGATING",
        "logs": log_content,
        "messages": state["messages"] + [cost_msg, debug_msg]
    }

def propose_mitigation_node(state: SREState) -> dict:
    """
    Analyzes gathered log outputs using dynamic LLM reasoning via the AI Gateway
    with strict Pydantic SREIncidentAnalysis schema validation.
    Tracks execution recursion count to prevent infinite loop token drain.
    """
    print(">>> SRE Agent [Node: Propose Mitigation] analyzing diagnostics via AI Gateway...")
    
    ## Increment depth counter for Circuit Breaker pattern
    current_depth = state.get("execution_depth")
    current_depth = (current_depth if current_depth is not None else 0) + 1
    
    log_data = state.get("logs", "")
    message_list = list(state.get("messages", []))
    
    # Dynamic LLM analysis via AI Gateway
    from ai_gateway import analyze_incident_with_gemini, sanitize_and_validate
    
    # 1. DLP Quarantine Check
    try:
        sanitize_and_validate(log_data)
    except Exception as e:
        return {
            "status": "FAILED",
            "mitigation_action": "ESCALATE_SECURITY_BREACH",
            "execution_depth": current_depth,
            "approval_status": "REJECTED",
            "messages": message_list + [f"AI Gateway DLP Blocked Request: {str(e)}"]
        }
        
    # 2. Dynamic Gemini Root Cause Analysis
    analysis = analyze_incident_with_gemini(log_data)
    
    # Map structured mitigation to execution action
    if analysis.recommended_mitigation_type == "PATCH_MEMORY_LIMIT":
        target_val = analysis.suggested_patch_value or "512Mi"
        proposed_action = f"patch_memory_limit_{target_val}"
    elif analysis.recommended_mitigation_type == "ROLLOUT_RESTART":
        proposed_action = "restart_deployment"
    elif analysis.recommended_mitigation_type == "ROLLBACK_DEPLOYMENT":
        proposed_action = "rollback_deployment"
    else:
        proposed_action = "escalate_human"

    msg = (
        f"[{analysis.severity}] {analysis.summary} "
        f"(Confidence: {analysis.confidence_score * 100:.0f}%). "
        f"Root Cause: {analysis.technical_explanation} "
        f"Proposing {analysis.recommended_mitigation_type}."
    )
        
    return {
        "status": "PROPOSED",
        "mitigation_action": proposed_action,
        "execution_depth": current_depth,
        "approval_status": "PENDING",
        "messages": message_list + [msg]
    }

def apply_mitigation_node(state: SREState) -> dict:
    """
    Implements structural patches or rollouts using the SRE MCP server.
    """
    print(">>> SRE Agent [Node: Apply Mitigation] processing repair actions via MCP...")
    
    if state.get("approval_status") != "APPROVED":
        msg = "Mitigation execution rejected: manual gateway state is not 'APPROVED'."
        return {
            "status": "FAILED",
            "messages": state["messages"] + [msg]
        }
        
    action = state.get("mitigation_action")
    messages = list(state.get("messages", []))
    
    if action == "patch_memory_limit_512Mi":
        res = call_mcp_tool("commit_gitops_patch", {"deployment_path": "dummy-app/deployment.yaml", "limit": "512Mi"})
        if "Error" not in res:
            msg = f"Successfully updated GitOps manifest limits via MCP: {res}"
            status = "RESOLVED"
        else:
            msg = f"GitOps manifest limits update failed via MCP: {res}"
            status = "FAILED"
    else:
        res = call_mcp_tool("restart_deployment", {"deployment_name": "faulty-service", "namespace": "default"})
        if "Error" not in res:
            msg = f"Executed rollout restart via MCP: {res}"
            status = "RESOLVED"
        else:
            msg = f"Rollout restart execution action failed via MCP: {res}"
            status = "FAILED"
            
    return {
        "status": status,
        "messages": messages + [msg]
    }

def circuit_breaker_router(state: SREState) -> str:
    """
    Acts as our safety circuit breaker routing decision logic.
    Terminates the execution loop if recursion is too high.
    """
    depth = state.get("execution_depth", 0)
    if depth > 5:
        print("!!! Alert: Circuit breaker triggered due to execution depth >= 5.")
        return "abort"
    return "continue"

## Define our state graph structure
builder = StateGraph(SREState)

## Register nodes
builder.add_node("diagnose", diagnose_node)
builder.add_node("propose_mitigation", propose_mitigation_node)
builder.add_node("apply_mitigation", apply_mitigation_node)

## Define graph routes
builder.add_edge(START, "diagnose")
builder.add_edge("diagnose", "propose_mitigation")

## Route using conditional check edge for the circuit breaker pattern
builder.add_conditional_edges(
    "propose_mitigation",
    circuit_breaker_router,
    {
        "continue": "apply_mitigation",
        "abort": END
    }
)
builder.add_edge("apply_mitigation", END)

## Set up compilation boundary with global Postgres checkpointer
def get_compiled_graph(checkpointer: PostgresSaver):
    """
    Compiles the target agent workflow. Sets up the Human-In-The-Loop gateway
    by establishing an interrupt boundary before running mitigation execution steps.
    """
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["apply_mitigation"]
    )

def extract_tenant_context(config: dict) -> tuple:
    """
    Extracts client_id (tenant) and thread_id from standard config route.
    Supports format: "client_id:thread_id"
    """
    thread_id = config.get("configurable", {}).get("thread_id", "default:default")
    if ":" in thread_id:
        client_id, actual_thread = thread_id.split(":", 1)
        return client_id, actual_thread
    return "default", thread_id
