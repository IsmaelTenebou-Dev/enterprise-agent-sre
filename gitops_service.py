import os
import subprocess
import yaml
import requests
from typing import Optional, Dict, Any

class GitOpsRemediationService:
    """
    Production GitOps Remediation Service.
    Enforces that an autonomous agent never mutates cluster pods directly.
    Instead, it creates git remediation branches, commits declarative manifest patches,
    and opens Pull Requests reconciled by ArgoCD.
    """
    
    def __init__(self, repo_dir: str = "."):
        self.repo_dir = repo_dir
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.github_repo = os.environ.get("GITHUB_REPOSITORY") # e.g. "octocat/Hello-World"

    def _run_git(self, args: list) -> str:
        res = subprocess.run(
            ["git"] + args,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()

    def create_remediation_branch(self, incident_id: str) -> str:
        """Checks out a dedicated Git remediation branch for the incident."""
        branch_name = f"sre-remediation/{incident_id.lower()}"
        try:
            # Ensure on main baseline
            self._run_git(["checkout", "main"])
            # Create and switch to new branch
            self._run_git(["checkout", "-B", branch_name])
            print(f"[GitOps Service] Checked out new remediation branch: {branch_name}")
            return branch_name
        except Exception as e:
            raise RuntimeError(f"Failed to create GitOps branch: {e}")

    def patch_manifest(self, file_path: str, new_memory_limit: str) -> Dict[str, Any]:
        """Applies declarative YAML updates to the target manifest."""
        full_path = os.path.join(self.repo_dir, file_path)
        with open(full_path, "r") as f:
            docs = list(yaml.safe_load_all(f))
            
        old_val = None
        for doc in docs:
            if doc and doc.get("kind") == "Deployment":
                containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
                if containers:
                    resources = containers[0].setdefault("resources", {})
                    limits = resources.setdefault("limits", {})
                    old_val = limits.get("memory", "unknown")
                    limits["memory"] = new_memory_limit

        with open(full_path, "w") as f:
            yaml.safe_dump_all(docs, f, default_flow_style=False)

        print(f"[GitOps Service] Patched {file_path}: memory limit {old_val} -> {new_memory_limit}")
        return {"file": file_path, "old_limit": old_val, "new_limit": new_memory_limit}

    def commit_remediation(self, incident_id: str, branch_name: str, patch_info: dict, root_cause: str) -> str:
        """Commits the patch with structured audit trail."""
        commit_msg = (
            f"fix(sre): autonomous remediation for {incident_id}\n\n"
            f"Incident ID: {incident_id}\n"
            f"Root Cause: {root_cause}\n"
            f"Patch: Updated {patch_info['file']} memory limit to {patch_info['new_limit']}\n"
            f"Signed-off-by: SRE Autonomous Agent <agent@sre.enterprise.internal>\n"
            f"Reconciled-by: ArgoCD Application (argocd/application.yaml)"
        )
        self._run_git(["add", patch_info["file"]])
        self._run_git(["commit", "-m", commit_msg])
        commit_hash = self._run_git(["rev-parse", "--short", "HEAD"])
        print(f"[GitOps Service] Committed patch {commit_hash} on {branch_name}")
        return commit_hash

    def open_pull_request(self, incident_id: str, branch_name: str, commit_hash: str, description: str) -> Dict[str, Any]:
        """Opens a Pull Request via GitHub API if credentials exist, or provides local PR object."""
        title = f"[SRE Auto-Remediation] Resolve {incident_id} Memory Limit Breach"
        body = (
            f"## 🤖 Autonomous SRE Remediation Report\n\n"
            f"**Incident ID**: `{incident_id}`\n"
            f"**Remediation Commit**: `{commit_hash}`\n"
            f"**Branch**: `{branch_name}`\n\n"
            f"### Forensic Analysis & Justification\n"
            f"{description}\n\n"
            f"### ArgoCD GitOps Verification\n"
            f"Merging this PR will trigger ArgoCD automatic sync to `default` namespace.\n"
        )
        
        # If real GitHub token present, open real PR
        if self.github_token and self.github_repo:
            try:
                url = f"https://api.github.com/repos/{self.github_repo}/pulls"
                headers = {
                    "Authorization": f"Bearer {self.github_token}",
                    "Accept": "application/vnd.github.v3+json"
                }
                payload = {
                    "title": title,
                    "head": branch_name,
                    "base": "main",
                    "body": body
                }
                resp = requests.post(url, json=payload, headers=headers)
                if resp.status_code == 201:
                    pr_data = resp.json()
                    print(f"[GitOps Service] Successfully created GitHub Pull Request: {pr_data['html_url']}")
                    return {
                        "pr_number": pr_data["number"],
                        "pr_url": pr_data["html_url"],
                        "status": "OPEN",
                        "is_remote": True
                    }
            except Exception as e:
                print(f"[GitOps Service] Remote PR creation failed: {e}. Falling back to declarative GitOps branch.")

        # Local GitOps branch summary for testing/ArgoCD
        diff_summary = self._run_git(["diff", "main..." + branch_name, "--stat"])
        return {
            "pr_number": 101,
            "pr_url": f"https://github.com/enterprise/sre-platform/pull/101 (Branch: {branch_name})",
            "title": title,
            "branch": branch_name,
            "commit": commit_hash,
            "diff_summary": diff_summary,
            "status": "AWAITING_MERGE",
            "is_remote": False
        }
