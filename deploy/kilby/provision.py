"""Provision the Salcobrand services using Kilby's documented REST API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.request

API = "https://kilby.neuramorphic.ai/api/v1"


def call(path, body=None):
    request = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                    headers={"Authorization": "Bearer " + os.environ["KILBY_API_KEY"],
                                             "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = json.loads(error.read()).get("error", {})
        raise RuntimeError(f"Kilby HTTP {error.code}: {detail.get('message', 'Request failed')}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="cristhian-netizen/Salcobrand")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--installation", type=int, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path(".local/kilby/deployment-state.json"))
    args = parser.parse_args()
    if not os.environ.get("KILBY_API_KEY") or not os.environ.get("NEURAVISION_REMOTE_URL"):
        parser.error("Set KILBY_API_KEY and NEURAVISION_REMOTE_URL in the operator environment.")
    # These private values support a resumable provisioning run, including upload
    # of the initial snapshot. The state path belongs outside version control.
    args.state.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(args.state.read_text()) if args.state.exists() else {
        "bootstrap_token": secrets.token_urlsafe(48), "session_secret": secrets.token_urlsafe(48),
        "registration_code": secrets.token_urlsafe(32),
    }
    args.state.write_text(json.dumps(state, indent=2), encoding="utf-8")
    project = next((item for item in call("/projects")["projects"] if item["name"] == "Salcobrand"), None)
    if project is None:
        project = call("/projects", {"name": "Salcobrand"})
    environments = call(f"/projects/{project['id']}/environments")["environments"]
    environment = next(item for item in environments if item["name"] == "Production")["id"]
    database = next((item for item in call("/databases")["databases"] if item["name"] == "salcobrand"), None)
    if database is None:
        database = call("/databases", {"name": "salcobrand", "environment": environment,
                                      "version": "18", "plan": "starter", "storage_gb": 5})
    database = call(f"/databases/{database['id']}")
    if database["status"] != "available":
        raise RuntimeError("PostgreSQL is still starting. Run provisioning again once it is available.")
    with args.snapshot.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    runtime = {
        "DATABASE_URL": database["internal_url"], "DATA_DIR": "/data/app", "PORT": "8080",
        "SESSION_SECRET": state["session_secret"], "REGISTRATION_CODE": state["registration_code"],
        "NEURAVISION_ENVIRONMENT": "kilby", "NEURAVISION_TENANT_ID": "salcobrand",
        "NEURAVISION_TENANT_NAME": "Salcobrand", "NEURAVISION_ANALYSIS_BACKEND": "remote",
        "NEURAVISION_WARMUP": "0", "ROLE": "all", "APIS_STORE": "memory", "APIS_CW_METRICS": "0",
        "SALCOBRAND_BOOTSTRAP_TOKEN": state["bootstrap_token"], "SALCOBRAND_DATA_ARCHIVE_SHA256": checksum,
    }
    for name in ("NEURAVISION_REMOTE_URL", "NEURAVISION_REMOTE_USERNAME", "NEURAVISION_REMOTE_PASSWORD",
                 "NEURAVISION_REMOTE_POINT_PREFIX", "NEURAVISION_REMOTE_POINT_MAP", "INTEGRATION_NEURAVISION_KEY"):
        if os.environ.get(name):
            runtime[name] = os.environ[name]
    services = {item["name"]: item for item in call("/services")["services"]}
    for name, kind, plan, dockerfile, env in (
        ("salcobrand-api", "private", "standard", "backend.Dockerfile", runtime),
        ("salcobrand-web", "web", "starter", "frontend.Dockerfile", {"BACKEND_URL": "http://salcobrand-api:8080"}),
    ):
        service = services.get(name)
        if service is None:
            dockerfile_path = "deploy/kilby/" + dockerfile
            build_plan = {"root_dir": "", "strategy": "dockerfile", "runtime": "docker",
                          "framework": "", "dockerfile_path": dockerfile_path, "install_command": "",
                          "build_command": "", "start_command": "", "port": 8080,
                          "health_path": "/health" if kind == "private" else "/healthz", "plan_id": plan,
                          "env": [], "notes": [], "warnings": [], "candidates": []}
            body = {"name": name, "type": kind, "plan": plan, "environment": environment,
                    "port": 8080, "health_check_path": "/health" if kind == "private" else "/healthz",
                    "env": env, "source": {"kind": "git", "installation_id": args.installation,
                        "repo": args.repo, "branch": args.branch, "root_dir": "",
                        "dockerfile_path": dockerfile_path, "build_plan": build_plan, "auto_deploy": False}}
            if kind == "private":
                body["disk"] = {"mount_path": "/data", "size_gb": 5}
            service = call("/services", body)
        state[name] = {key: service.get(key) for key in ("id", "name", "url", "status")}
        args.state.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(json.dumps(state[name]))


if __name__ == "__main__":
    main()
