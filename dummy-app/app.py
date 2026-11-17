import os
import time
from fastapi import FastAPI, Response, status

app = FastAPI(title="SRE Faulty Simulator Service")

# Global memory holder to simulate OOM leaks
memory_leak_leakage = []

@app.get("/healthz")
def healthz(response: Response):
    """
    Standard kubernetes liveness/readiness probe target.
    """
    return {"status": "ok", "uptime_seconds": time.monotonic()}

@app.post("/simulate/crash")
def simulate_crash():
    """
    Forces immediate process exit to trigger CrashLoopBackOff.
    """
    print("Simulating crash down...")
    os._exit(127)

@app.post("/simulate/oom-leak")
def simulate_oom():
    """
    Simulates memory exhaustion (Out of Memory) by allocating global bytes.
    """
    print("Allocating memory...")
    # Allocate approximately 100MB of strings per call
    for _ in range(10):
        memory_leak_leakage.append("a" * (10 * 1024 * 1024))
    return {"message": "Allocated 100MB memory block. Current size: " + str(len(memory_leak_leakage)) + " blocks"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080)
