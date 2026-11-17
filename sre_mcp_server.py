import subprocess
import json
import yaml
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("sre-mcp-server")

@mcp.tool()
def get_pods(namespace: str = "default") -> str:
    """Gets the listing of pods in the given Kubernetes namespace with status details."""
    try:
        res = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(res.stdout)
        summary = []
        for item in data.get("items", []):
            name = item["metadata"]["name"]
            status = item["status"]["phase"]
            container_statuses = item["status"].get("containerStatuses", [])
            restarts = 0
            if container_statuses:
                restarts = container_statuses[0].get("restartCount", 0)
            summary.append(f"Pod: {name} | Status: {status} | Restarts: {restarts}")
        return "\n".join(summary) if summary else "No pods found."
    except Exception as e:
        return f"Error executing get_pods: {str(e)}"

@mcp.tool()
def get_pod_logs(pod_name: str, namespace: str = "default") -> str:
    """Fetches the logs of the specified pod."""
    try:
        res = subprocess.run(
            ["kubectl", "logs", pod_name, "-n", namespace, "--tail=50"],
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout
    except Exception as e:
        return f"Error fetching logs for {pod_name}: {str(e)}"

@mcp.tool()
def restart_deployment(deployment_name: str, namespace: str = "default") -> str:
    """Performs a rollout restart on the specified deployment."""
    try:
        res = subprocess.run(
            ["kubectl", "rollout", "restart", f"deployment/{deployment_name}", "-n", namespace],
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception as e:
        return f"Error restarting deployment {deployment_name}: {str(e)}"

@mcp.tool()
def patch_memory_limit(deployment_name: str, limit: str, namespace: str = "default") -> str:
    """Patches the first container's memory limit of the specified deployment specification."""
    try:
        patch_json = json.dumps([
            {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": limit}
        ])
        res = subprocess.run(
            ["kubectl", "patch", "deployment", deployment_name, "-n", namespace, "--type=json", "-p", patch_json],
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception as e:
        return f"Error patching memory limit for deployment {deployment_name}: {str(e)}"

@mcp.tool()
def create_gitops_pull_request(incident_id: str, deployment_path: str, new_limit: str, justification: str) -> str:
    """
    Production GitOps Tool: Checks out an incident remediation branch,
    patches the YAML manifest, commits changes with full audit signatures,
    and opens a declarative Pull Request for ArgoCD reconciliation.
    """
    from gitops_service import GitOpsRemediationService
    try:
        service = GitOpsRemediationService()
        branch = service.create_remediation_branch(incident_id)
        patch_info = service.patch_manifest(deployment_path, new_limit)
        commit = service.commit_remediation(incident_id, branch, patch_info, justification)
        pr = service.open_pull_request(incident_id, branch, commit, justification)
        return json.dumps({
            "status": "SUCCESS",
            "branch": branch,
            "commit": commit,
            "pr_url": pr.get("pr_url"),
            "diff_summary": pr.get("diff_summary", "")
        }, indent=2)
    except Exception as e:
        return f"Error executing create_gitops_pull_request: {str(e)}"

@mcp.tool()
def commit_gitops_patch(deployment_path: str, limit: str) -> str:
    """Updates the target deployment YAML manifest specification memory limit via GitOps branch."""
    from gitops_service import GitOpsRemediationService
    try:
        service = GitOpsRemediationService()
        incident_id = f"INC-{int(subprocess.run(['date', '+%s'], capture_output=True, text=True).stdout.strip())}"
        branch = service.create_remediation_branch(incident_id)
        patch_info = service.patch_manifest(deployment_path, limit)
        commit = service.commit_remediation(incident_id, branch, patch_info, "Automated SRE limits patch")
        return f"Successfully created GitOps remediation commit {commit} on branch {branch} updating {deployment_path} to {limit}."
    except Exception as e:
        return f"Error executing GitOps commit: {str(e)}"

@mcp.resource("aws://cost-explorer/monthly-summary")
def get_aws_cost_summary() -> str:
    """Returns a mock breakdown of AWS monthly infrastructure costs for cost safety analysis."""
    cost_data = {
        "billing_period": "2026-07",
        "total_estimated_usd": 12450.75,
        "services": [
            {"service_name": "Amazon Elastic Compute Cloud (EC2)", "cost_usd": 7890.30},
            {"service_name": "Amazon Elastic Kubernetes Service (EKS)", "cost_usd": 1450.00},
            {"service_name": "Amazon Relational Database Service (RDS)", "cost_usd": 1820.45},
            {"service_name": "NAT Gateway / Network Data Transfer", "cost_usd": 1290.00}
        ],
        "anomaly_detected": False
    }
    return json.dumps(cost_data, indent=2)

if __name__ == "__main__":
    mcp.run()
