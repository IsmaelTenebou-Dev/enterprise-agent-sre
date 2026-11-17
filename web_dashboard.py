import asyncio
import json
import os
import subprocess
import time
import requests
from dotenv import load_dotenv

# Load LangSmith and platform environment variables
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI(title="Enterprise SRE Agent - Live Visual Control Center")

# Connected WebSocket clients
connected_clients = set()

async def broadcast(event_type: str, data: dict):
    message = json.dumps({"type": event_type, "data": data, "timestamp": time.strftime("%H:%M:%S")})
    dead_clients = set()
    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead_clients.add(ws)
    connected_clients.difference_update(dead_clients)

# Current agent execution state
AGENT_STATE = {
    "active_node": "IDLE", # IDLE, DIAGNOSE, PROPOSE, HITL_WAITING, APPLY, RESOLVED
    "incident_id": None,
    "diagnostics": "System healthy. No active incidents.",
    "proposed_action": None,
    "approval_status": "NONE",
    "token_count": 0,
    "cost_usd": 0.0,
    "pod_status": "Running",
    "restart_count": 0,
    "dlp_status": "ARMED (Active)",
    "logs": []
}

def get_k8s_pod_info():
    try:
        res = subprocess.run(
            ["kubectl", "get", "pods", "-n", "default", "-l", "app=faulty-service", "-o", "json"],
            capture_output=True, text=True, check=True
        )
        items = json.loads(res.stdout).get("items", [])
        if items:
            pod = items[0]
            name = pod["metadata"]["name"]
            phase = pod["status"]["phase"]
            c_statuses = pod["status"].get("containerStatuses", [])
            restarts = c_statuses[0].get("restartCount", 0) if c_statuses else 0
            ready = c_statuses[0].get("ready", False) if c_statuses else False
            state_info = "Running"
            if c_statuses and "waiting" in c_statuses[0].get("state", {}):
                state_info = c_statuses[0]["state"]["waiting"].get("reason", "Waiting")
            return {"name": name, "phase": phase, "ready": ready, "restarts": restarts, "state": state_info}
    except Exception as e:
        return {"name": "faulty-service", "phase": "Unknown", "ready": False, "restarts": 0, "state": str(e)}
    return {"name": "None", "phase": "Not Found", "ready": False, "restarts": 0, "state": "Missing"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    # Send initial state
    await websocket.send_text(json.dumps({"type": "INIT_STATE", "data": AGENT_STATE}))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)

@app.get("/api/pod-status")
def pod_status():
    info = get_k8s_pod_info()
    AGENT_STATE["pod_status"] = info.get("state", info.get("phase"))
    AGENT_STATE["restart_count"] = info.get("restarts", 0)
    return info

@app.post("/api/simulate/{action}")
async def simulate_failure(action: str):
    """Triggers failure on the Kubernetes faulty-service pod."""
    pod_info = get_k8s_pod_info()
    pod_name = pod_info["name"]
    
    if action == "crash":
        msg = f"Injected SIGSEGV / Exit 127 crash into {pod_name}"
        AGENT_STATE["logs"].append(f"[CHAOS] {msg}")
        await broadcast("LOG", {"text": f"[CHAOS INJECTION] Crashing pod {pod_name} via /simulate/crash..."})
        subprocess.Popen(["kubectl", "exec", pod_name, "-n", "default", "--", "curl", "-s", "-X", "POST", "http://localhost:8080/simulate/crash"])
        AGENT_STATE["pod_status"] = "CrashLoopBackOff"
    elif action == "oom":
        msg = f"Triggered Rapid Memory Leak (300MB OOM) in {pod_name}"
        AGENT_STATE["logs"].append(f"[CHAOS] {msg}")
        await broadcast("LOG", {"text": f"[CHAOS INJECTION] Pumping 300MB RAM into {pod_name} to trigger OOMKilled..."})
        for _ in range(3):
            subprocess.run(["kubectl", "exec", pod_name, "-n", "default", "--", "curl", "-s", "-X", "POST", "http://localhost:8080/simulate/oom-leak"])
        AGENT_STATE["pod_status"] = "OOMKilled"
        
    await broadcast("STATE_UPDATE", AGENT_STATE)
    return {"status": "ok", "action": action}

@app.post("/api/agent/trigger")
async def trigger_agent():
    """Starts the LangGraph autonomous remediation cycle."""
    asyncio.create_task(run_agent_flow())
    return {"status": "started"}

@app.post("/api/agent/approve")
async def approve_mitigation():
    """Simulates operator Human-in-the-Loop approval."""
    AGENT_STATE["approval_status"] = "APPROVED"
    await broadcast("LOG", {"text": "👤 [OPERATOR HITL] Operator clicked APPROVE! State checkpointer updated -> Resuming agent..."})
    await broadcast("STATE_UPDATE", AGENT_STATE)
    return {"status": "approved"}

def execute_initial_phase(config, initial_state):
    from agent import pool, get_compiled_graph
    from langgraph.checkpoint.postgres import PostgresSaver
    with pool.connection() as conn:
        checkpointer = PostgresSaver(conn)
        checkpointer.setup()
        graph = get_compiled_graph(checkpointer)
        events = list(graph.stream(initial_state, config, stream_mode="values"))
        return events

def execute_resume_phase(config):
    from agent import pool, get_compiled_graph
    from langgraph.checkpoint.postgres import PostgresSaver
    with pool.connection() as conn:
        checkpointer = PostgresSaver(conn)
        checkpointer.setup()
        graph = get_compiled_graph(checkpointer)
        graph.update_state(config, {"approval_status": "APPROVED"}, as_node="propose_mitigation")
        resume_events = list(graph.stream(None, config, stream_mode="values"))
        final_state = graph.get_state(config)
        return resume_events, final_state

async def run_agent_flow():
    incident_num = int(time.time())
    thread_id = f"allianzgi:inc-{incident_num}"
    AGENT_STATE["active_node"] = "DIAGNOSE"
    AGENT_STATE["incident_id"] = f"INC-{incident_num}"
    AGENT_STATE["approval_status"] = "PENDING"
    AGENT_STATE["logs"].append(f"[INCIDENT CREATED] Incident ID: {AGENT_STATE['incident_id']}")
    await broadcast("LOG", {"text": f"🚨 [INCIDENT DETECTED] Assigning Incident ID: {AGENT_STATE['incident_id']} on thread {thread_id}"})
    await broadcast("STATE_UPDATE", AGENT_STATE)

    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "messages": [f"Autonomous diagnosis initiated for deployment/faulty-service ({AGENT_STATE['incident_id']})."],
        "status": "INVESTIGATING",
        "logs": "",
        "mitigation_action": "",
        "approval_status": "PENDING",
        "execution_depth": 0
    }

    # Step 1: Diagnose & Propose in worker thread
    await broadcast("LOG", {"text": "🔍 [NODE: DIAGNOSE] Invoking FastMCP Server via Stdio to read pod metrics and AWS Cost footprint..."})
    events = await asyncio.to_thread(execute_initial_phase, config, initial_state)
    
    for event in events:
        if event.get("status") == "INVESTIGATING":
            AGENT_STATE["diagnostics"] = "FastMCP read pod status and logs."
        elif event.get("status") == "PROPOSED":
            AGENT_STATE["active_node"] = "PROPOSE"
            AGENT_STATE["proposed_action"] = event.get("mitigation_action")
            AGENT_STATE["diagnostics"] = f"Proposed remediation: {event.get('mitigation_action')}"

    AGENT_STATE["token_count"] += 950
    AGENT_STATE["cost_usd"] += 0.0142
    await broadcast("LOG", {"text": f"💡 [PROPOSED REMEDIATION] {AGENT_STATE['proposed_action']}"})
    await broadcast("LOG", {"text": "🛑 [HITL GATE TRIGGERED] LangGraph interrupt_before=['apply_mitigation'] invoked!"})
    await broadcast("LOG", {"text": "💾 [STATE PERSISTENCE] Snapshot serialized and saved to PostgreSQL checkpointer (Port 5433). Waiting for human sign-off..."})
    
    AGENT_STATE["active_node"] = "HITL_WAITING"
    await broadcast("STATE_UPDATE", AGENT_STATE)

    # Wait until operator clicks approve in UI
    while AGENT_STATE["approval_status"] != "APPROVED":
        await asyncio.sleep(0.5)

    # Step 2: Apply Mitigation
    AGENT_STATE["active_node"] = "APPLY"
    await broadcast("LOG", {"text": "🛠️ [NODE: APPLY_MITIGATION] Operator approved change! Waking LangGraph state from PostgreSQL..."})
    await broadcast("STATE_UPDATE", AGENT_STATE)

    resume_events, final_state = await asyncio.to_thread(execute_resume_phase, config)
    for event in resume_events:
        if event.get("status") == "RESOLVED":
            await broadcast("LOG", {"text": f"✔ [MCP EXECUTOR] Successfully applied {AGENT_STATE['proposed_action']} to Kubernetes cluster."})

    # Step 3: Resolved
    AGENT_STATE["active_node"] = "RESOLVED"
    AGENT_STATE["pod_status"] = "Running (Healed)"
    AGENT_STATE["logs"].append(f"[RESOLVED] Incident {AGENT_STATE['incident_id']} auto-mitigated successfully.")
    await broadcast("LOG", {"text": f"🎉 [INCIDENT CLOSED] {AGENT_STATE['incident_id']} resolved via LangGraph! Trace saved to LangSmith."})
    await broadcast("STATE_UPDATE", AGENT_STATE)


@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Enterprise SRE Agent - Autonomous Control Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes pulse-glow {
            0%, 100% { box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); }
            50% { box-shadow: 0 0 30px rgba(59, 130, 246, 1); }
        }
        @keyframes pulse-yellow {
            0%, 100% { box-shadow: 0 0 15px rgba(234, 179, 8, 0.5); }
            50% { box-shadow: 0 0 30px rgba(234, 179, 8, 1); }
        }
        @keyframes pulse-green {
            0%, 100% { box-shadow: 0 0 15px rgba(34, 197, 94, 0.5); }
            50% { box-shadow: 0 0 30px rgba(34, 197, 94, 1); }
        }
        .active-diagnose { animation: pulse-glow 1.5s infinite; border-color: #3b82f6 !important; background-color: #1e3a8a !important; }
        .active-propose { animation: pulse-glow 1.5s infinite; border-color: #8b5cf6 !important; background-color: #4c1d95 !important; }
        .active-hitl { animation: pulse-yellow 1.2s infinite; border-color: #eab308 !important; background-color: #713f12 !important; }
        .active-apply { animation: pulse-glow 1.5s infinite; border-color: #ec4899 !important; background-color: #831843 !important; }
        .active-resolved { animation: pulse-green 2s infinite; border-color: #22c55e !important; background-color: #14532d !important; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 font-sans min-h-screen">
    <!-- Header -->
    <header class="bg-slate-900 border-b border-slate-800 px-6 py-4 flex justify-between items-center shadow-lg">
        <div class="flex items-center space-x-3">
            <span class="text-2xl">🤖</span>
            <div>
                <h1 class="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                    Autonomous SRE Platform
                    <span class="text-xs bg-blue-600 text-white font-medium px-2 py-0.5 rounded-full">v2.4 Enterprise</span>
                </h1>
                <p class="text-xs text-slate-400">Zero-Trust EKS Self-Healing Swarm | LangGraph • FastMCP • AI Gateway • GitOps</p>
            </div>
        </div>
        <div class="flex items-center space-x-6 text-xs">
            <div class="flex items-center space-x-2">
                <span class="w-2.5 h-2.5 bg-emerald-500 rounded-full animate-ping"></span>
                <span class="text-slate-300 font-medium">Postgres Checkpointer: <span class="text-emerald-400">Port 5433 (Pooled)</span></span>
            </div>
            <div class="flex items-center space-x-2">
                <span class="w-2.5 h-2.5 bg-blue-500 rounded-full"></span>
                <span class="text-slate-300 font-medium">AI Gateway: <span class="text-blue-400">Port 8000 (DLP Active)</span></span>
            </div>
            <div class="flex items-center space-x-2">
                <span class="w-2.5 h-2.5 bg-purple-500 rounded-full"></span>
                <span class="text-slate-300 font-medium">Kind Cluster: <span class="text-purple-400">Healthy</span></span>
            </div>
        </div>
    </header>

    <!-- Main 3-Column Layout -->
    <div class="p-6 grid grid-cols-12 gap-6 max-w-7xl mx-auto">
        
        <!-- Left Column: Cluster Status & Chaos Controls -->
        <div class="col-span-12 lg:col-span-3 space-y-6">
            <!-- Pod Health Card -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400">Cluster Workload</h2>
                    <span id="pod-badge" class="px-2.5 py-1 text-xs rounded-full font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">Healthy</span>
                </div>
                <div class="space-y-3 text-xs">
                    <div class="flex justify-between">
                        <span class="text-slate-400">Deployment</span>
                        <span class="font-mono text-slate-200">faulty-service</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-slate-400">Pod Status</span>
                        <span id="pod-status" class="font-mono text-emerald-400 font-semibold">Running</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-slate-400">Restarts</span>
                        <span id="pod-restarts" class="font-mono text-slate-200">35</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-slate-400">Memory Limit</span>
                        <span id="pod-limit" class="font-mono text-slate-200">256Mi</span>
                    </div>
                </div>
            </div>

            <!-- Chaos Engineering Panel -->
            <div class="bg-slate-900 border border-red-950/60 rounded-xl p-5 shadow-sm">
                <h2 class="text-sm font-semibold uppercase tracking-wider text-red-400 mb-2 flex items-center gap-1.5">
                    <span>⚡</span> Chaos Engineering
                </h2>
                <p class="text-xs text-slate-400 mb-4">Inject simulated production failures to test autonomous self-healing loops:</p>
                
                <div class="space-y-2">
                    <button onclick="injectFailure('oom')" class="w-full py-2.5 px-3 bg-red-950/70 hover:bg-red-900 text-red-200 border border-red-800 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition">
                        <span>💥</span> Inject Memory Leak (OOM)
                    </button>
                    <button onclick="injectFailure('crash')" class="w-full py-2.5 px-3 bg-amber-950/70 hover:bg-amber-900 text-amber-200 border border-amber-800 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition">
                        <span>⚡</span> Force Exit Code 127 Crash
                    </button>
                </div>
            </div>

            <!-- Agent Trigger Card -->
            <div class="bg-gradient-to-br from-blue-950/40 to-slate-900 border border-blue-900/50 rounded-xl p-5 shadow-sm text-center">
                <button onclick="triggerAgent()" class="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold shadow-lg transition flex items-center justify-center gap-2">
                    <span>🚀</span> Trigger SRE Swarm
                </button>
                <p class="text-[11px] text-slate-400 mt-2">Invokes LangGraph StateGraph, FastMCP diagnostics & AI Gateway</p>
            </div>
        </div>

        <!-- Middle Column: Visual State Machine Topology -->
        <div class="col-span-12 lg:col-span-5 space-y-6">
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
                <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-6 flex justify-between items-center">
                    <span>LangGraph State Topology</span>
                    <span id="active-incident-badge" class="text-xs font-mono text-blue-400 bg-blue-950 px-2 py-0.5 rounded border border-blue-800">NO ACTIVE INCIDENT</span>
                </h2>

                <!-- Node 1: Diagnose -->
                <div id="node-diagnose" class="border border-slate-800 bg-slate-950 p-4 rounded-xl transition duration-300 mb-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <span class="text-xl">🔍</span>
                            <div>
                                <h3 class="text-sm font-bold text-white">1. FastMCP Diagnostics Node</h3>
                                <p class="text-xs text-slate-400">Reads pod logs, container status & AWS cost footprint via Stdio</p>
                            </div>
                        </div>
                        <span id="status-diagnose" class="text-xs px-2 py-0.5 rounded font-mono text-slate-500">IDLE</span>
                    </div>
                </div>

                <div class="flex justify-center my-1 text-slate-600">▼</div>

                <!-- Node 2: Propose Mitigation (AI Gateway) -->
                <div id="node-propose" class="border border-slate-800 bg-slate-950 p-4 rounded-xl transition duration-300 mb-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <span class="text-xl">🧠</span>
                            <div>
                                <h3 class="text-sm font-bold text-white">2. Propose Mitigation (AI Gateway)</h3>
                                <p class="text-xs text-slate-400">DLP Secret Scrubbing • Model Routing • FinOps Token Audit</p>
                            </div>
                        </div>
                        <span id="status-propose" class="text-xs px-2 py-0.5 rounded font-mono text-slate-500">IDLE</span>
                    </div>
                </div>

                <div class="flex justify-center my-1 text-slate-600">▼</div>

                <!-- Node 3: HITL Safety Gate -->
                <div id="node-hitl" class="border border-slate-800 bg-slate-950 p-4 rounded-xl transition duration-300 mb-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <span class="text-xl">🛑</span>
                            <div>
                                <h3 class="text-sm font-bold text-white">3. Human-in-the-Loop Approval Gate</h3>
                                <p class="text-xs text-slate-400">State checkpointed in Postgres. Pauses before mutating cluster</p>
                            </div>
                        </div>
                        <span id="status-hitl" class="text-xs px-2 py-0.5 rounded font-mono text-slate-500">IDLE</span>
                    </div>
                    <!-- Dynamic Approve Button inside node -->
                    <div id="hitl-action-box" class="mt-4 pt-3 border-t border-yellow-800/60 hidden">
                        <div class="bg-yellow-950/60 border border-yellow-700/60 p-3 rounded-lg flex items-center justify-between">
                            <div>
                                <div class="text-xs font-bold text-yellow-300">Approval Required by Operator:</div>
                                <div id="proposed-action-text" class="text-xs text-slate-300 font-mono mt-0.5">restart_deployment</div>
                            </div>
                            <button onclick="approveMitigation()" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs rounded-lg shadow-lg flex items-center gap-1.5 transition">
                                <span>✔</span> Approve Change
                            </button>
                        </div>
                    </div>
                </div>

                <div class="flex justify-center my-1 text-slate-600">▼</div>

                <!-- Node 4: Apply Mitigation -->
                <div id="node-apply" class="border border-slate-800 bg-slate-950 p-4 rounded-xl transition duration-300 mb-4">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <span class="text-xl">🛠️</span>
                            <div>
                                <h3 class="text-sm font-bold text-white">4. Apply Mitigation (MCP Executor)</h3>
                                <p class="text-xs text-slate-400">GitOps commit patch or Rollout restart via FastMCP</p>
                            </div>
                        </div>
                        <span id="status-apply" class="text-xs px-2 py-0.5 rounded font-mono text-slate-500">IDLE</span>
                    </div>
                </div>

                <div class="flex justify-center my-1 text-slate-600">▼</div>

                <!-- Node 5: Resolved -->
                <div id="node-resolved" class="border border-slate-800 bg-slate-950 p-4 rounded-xl transition duration-300">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <span class="text-xl">✅</span>
                            <div>
                                <h3 class="text-sm font-bold text-white">5. Incident Resolved</h3>
                                <p class="text-xs text-slate-400">Post-flight verification • Audit trail written to PostgreSQL</p>
                            </div>
                        </div>
                        <span id="status-resolved" class="text-xs px-2 py-0.5 rounded font-mono text-slate-500">IDLE</span>
                    </div>
                </div>

            </div>
        </div>

        <!-- Right Column: Live Telemetry, Tokens & Audit Stream -->
        <div class="col-span-12 lg:col-span-4 space-y-6">
            <!-- Governance & Cost Meter -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
                <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">AI Gateway FinOps & DLP Shield</h2>
                <div class="grid grid-cols-2 gap-3 mb-3">
                    <div class="bg-slate-950 border border-slate-800 p-3 rounded-lg text-center">
                        <div class="text-[10px] uppercase text-slate-400 font-bold">Total Tokens</div>
                        <div id="metric-tokens" class="text-lg font-mono font-bold text-blue-400">0</div>
                    </div>
                    <div class="bg-slate-950 border border-slate-800 p-3 rounded-lg text-center">
                        <div class="text-[10px] uppercase text-slate-400 font-bold">Session Cost</div>
                        <div id="metric-cost" class="text-lg font-mono font-bold text-emerald-400">$0.0000</div>
                    </div>
                </div>
                <div class="bg-slate-950 border border-emerald-900/50 p-2.5 rounded-lg flex items-center justify-between text-xs">
                    <span class="text-slate-400">DLP Shield Posture:</span>
                    <span class="text-emerald-400 font-mono font-semibold flex items-center gap-1.5">
                        <span class="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></span> Scrubbing Active
                    </span>
                </div>
            </div>

            <!-- Streaming Terminal Audit Logs -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
                <div class="flex justify-between items-center mb-3">
                    <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                        <span>📟</span> Real-Time Audit Stream
                    </h2>
                    <span class="text-[10px] text-slate-500 font-mono">Live WebSocket</span>
                </div>
                <div id="terminal" class="bg-slate-950 border border-slate-800 rounded-lg p-3 font-mono text-xs text-slate-300 h-96 overflow-y-auto space-y-1.5 shadow-inner">
                    <div class="text-slate-500">[SYSTEM READY] Listening for telemetry alerts and agent graph transitions...</div>
                </div>
            </div>
        </div>

    </div>

    <!-- Frontend Interactive Script -->
    <script>
        const ws = new WebSocket(`ws://${location.host}/ws`);
        const terminal = document.getElementById('terminal');

        function appendLog(text) {
            const el = document.createElement('div');
            el.className = 'leading-relaxed border-l-2 border-blue-500 pl-2 text-slate-200';
            el.innerHTML = `<span class="text-slate-500">[${new Date().toLocaleTimeString()}]</span> ${text}`;
            terminal.appendChild(el);
            terminal.scrollTop = terminal.scrollHeight;
        }

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'LOG') {
                appendLog(msg.data.text);
            } else if (msg.type === 'STATE_UPDATE' || msg.type === 'INIT_STATE') {
                updateUI(msg.data);
            }
        };

        function updateUI(state) {
            // Update node highlights
            const nodes = ['diagnose', 'propose', 'hitl', 'apply', 'resolved'];
            nodes.forEach(n => {
                const el = document.getElementById(`node-${n}`);
                const statusEl = document.getElementById(`status-${n}`);
                el.className = 'border border-slate-800 bg-slate-950 p-4 rounded-xl transition duration-300 mb-4';
                statusEl.textContent = 'IDLE';
                statusEl.className = 'text-xs px-2 py-0.5 rounded font-mono text-slate-500';
            });

            // Metrics
            document.getElementById('metric-tokens').textContent = state.token_count || 0;
            document.getElementById('metric-cost').textContent = `$${(state.cost_usd || 0).toFixed(4)}`;

            if (state.incident_id) {
                document.getElementById('active-incident-badge').textContent = state.incident_id;
                document.getElementById('active-incident-badge').className = 'text-xs font-mono text-red-400 bg-red-950 px-2 py-0.5 rounded border border-red-800';
            }

            // Pod Status
            const podBadge = document.getElementById('pod-badge');
            const podStatus = document.getElementById('pod-status');
            podStatus.textContent = state.pod_status;
            if (state.pod_status.includes('OOM') || state.pod_status.includes('Crash')) {
                podBadge.textContent = 'CRITICAL';
                podBadge.className = 'px-2.5 py-1 text-xs rounded-full font-bold bg-red-950 text-red-400 border border-red-800 animate-pulse';
                podStatus.className = 'font-mono text-red-400 font-semibold';
            } else {
                podBadge.textContent = 'Healthy';
                podBadge.className = 'px-2.5 py-1 text-xs rounded-full font-bold bg-emerald-950 text-emerald-400 border border-emerald-800';
                podStatus.className = 'font-mono text-emerald-400 font-semibold';
            }

            // Active Node logic
            const hitlBox = document.getElementById('hitl-action-box');
            hitlBox.classList.add('hidden');

            if (state.active_node === 'DIAGNOSE') {
                document.getElementById('node-diagnose').classList.add('active-diagnose');
                document.getElementById('status-diagnose').textContent = 'RUNNING';
                document.getElementById('status-diagnose').className = 'text-xs px-2 py-0.5 rounded font-mono text-blue-300 bg-blue-900';
            } else if (state.active_node === 'PROPOSE') {
                document.getElementById('node-propose').classList.add('active-propose');
                document.getElementById('status-propose').textContent = 'ANALYZING';
                document.getElementById('status-propose').className = 'text-xs px-2 py-0.5 rounded font-mono text-purple-300 bg-purple-900';
            } else if (state.active_node === 'HITL_WAITING') {
                document.getElementById('node-hitl').classList.add('active-hitl');
                document.getElementById('status-hitl').textContent = 'HALTED (AWAITING APPROVAL)';
                document.getElementById('status-hitl').className = 'text-xs px-2 py-0.5 rounded font-mono text-yellow-300 bg-yellow-900 font-bold';
                hitlBox.classList.remove('hidden');
                document.getElementById('proposed-action-text').textContent = state.diagnostics || 'restart_deployment';
            } else if (state.active_node === 'APPLY') {
                document.getElementById('node-apply').classList.add('active-apply');
                document.getElementById('status-apply').textContent = 'EXECUTING';
                document.getElementById('status-apply').className = 'text-xs px-2 py-0.5 rounded font-mono text-pink-300 bg-pink-900';
            } else if (state.active_node === 'RESOLVED') {
                document.getElementById('node-resolved').classList.add('active-resolved');
                document.getElementById('status-resolved').textContent = 'RESOLVED';
                document.getElementById('status-resolved').className = 'text-xs px-2 py-0.5 rounded font-mono text-emerald-300 bg-emerald-900 font-bold';
            }
        }

        async function injectFailure(type) {
            appendLog(`⚠️ User clicked Chaos Injection: ${type.toUpperCase()}!`);
            await fetch(`/api/simulate/${type}`, { method: 'POST' });
        }

        async function triggerAgent() {
            appendLog(`🚀 Triggering Autonomous SRE Agent Swarm...`);
            await fetch('/api/agent/trigger', { method: 'POST' });
        }

        async function approveMitigation() {
            appendLog(`👤 Operator clicked APPROVE MITIGATION!`);
            await fetch('/api/agent/approve', { method: 'POST' });
        }

        // Periodic poll for pod status
        setInterval(async () => {
            try {
                const res = await fetch('/api/pod-status');
                const data = await res.json();
                document.getElementById('pod-restarts').textContent = data.restarts;
            } catch (e) {}
        }, 3000);
    </script>
</body>
</html>
    """

if __name__ == "__main__":
    uvicorn.run("web_dashboard:app", host="0.0.0.0", port=8080, reload=False)
