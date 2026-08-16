import os
import sys
import time
import threading
import json
from typing import Any, Optional
from thinkdome.platform.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.sandbox.core.models import ExecuteRequest
from thinkdome.platform.orchestration.orchestrator_models import RunCodeInput, ShellExecInput

@register_tool
class RunCodeTool(BaseTool):
    name = "run_code"
    description = "Execute code inside the sandbox container (Python, JS, etc.)"
    required_scope = "code:run"
    input_schema = RunCodeInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        if "code" not in tool_input:
            raise ValueError("Parameter 'code' is required for run_code.")
        
        language = tool_input.get("language", "python")
        stdin = tool_input.get("stdin")
        ctx = get_context()

        # Enforce sandbox timeout if present
        timeout_ms = 5000
        if ctx.sandbox_limits and "timeout_sec" in ctx.sandbox_limits:
            timeout_ms = ctx.sandbox_limits["timeout_sec"] * 1000

        # Enforce sandbox network enablement if present
        allow_network = tool_input.get("allow_network", False)
        if ctx.sandbox_limits and "network_enabled" in ctx.sandbox_limits:
            allow_network = bool(ctx.sandbox_limits["network_enabled"])

        # Load env vars and inject credentials from vault if available
        env_vars = dict(tool_input.get("env_vars") or {})
        if ctx.credential_vault and ctx.username and ctx.sandbox_id:
            vault_secrets = ctx.credential_vault.inject_into_env(ctx.username, ctx.sandbox_id)
            env_vars.update(vault_secrets)

        exec_req = ExecuteRequest(
            code=tool_input["code"],
            language=language,
            stdin=stdin,
            security_profile=tool_input.get("security_profile", "HIGH_SECURITY"),
            env_vars=env_vars,
            caller_role=ctx.caller_role,
            allow_network=allow_network,
            memory_limit_mb=ctx.sandbox_limits.get("memory_mb") if ctx.sandbox_limits else None,
            cpu_cores=ctx.sandbox_limits.get("cpu_cores") if ctx.sandbox_limits else None,
            timeout_ms=timeout_ms,
            username=ctx.username,
        )
        
        resp = await ctx.execution_service.execute(exec_req)
        
        result_dict = {
            "stdout": resp.stdout,
            "stderr": resp.stderr,
            "exit_code": resp.exit_code,
            "timed_out": resp.timed_out,
            "duration_ms": resp.duration_ms
        }
        
        # Run security scanner on output
        if ctx.security_scanner:
            scan_res = ctx.security_scanner.scan(
                stdout=resp.stdout,
                stderr=resp.stderr,
                exit_code=resp.exit_code,
                token_id=ctx.username,
            )
            if scan_res.has_findings:
                result_dict["security_findings"] = [f.to_dict() for f in scan_res.findings]
        
        return json.dumps(result_dict, indent=2)


@register_tool
class ShellExecTool(BaseTool):
    name = "shell_exec"
    description = "Execute a shell command inside the sandbox container"
    required_scope = "shell:run"
    input_schema = ShellExecInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        command = tool_input.get("command")
        if not command:
            raise ValueError("Parameter 'command' is required for shell_exec.")

        cwd = tool_input.get("cwd")
        timeout_sec = min(tool_input.get("timeout", 30), 300)
        ctx = get_context()

        # Build wrapper python script to execute the command inside the sandbox environment.
        # This routes the execution to run with cgroups, seccomp, and VPC network limits.
        python_code = f"""
import subprocess
import os
import sys

cwd = {repr(cwd)}
command = {repr(command)}

# Determine sandbox base directory
base_dir = "/workspace" if os.path.exists("/workspace") else os.getcwd()

if cwd:
    cleaned = cwd.lstrip("/\\\\")
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].lstrip("/\\\\")
    resolved_cwd = os.path.abspath(os.path.join(base_dir, cleaned))
    
    if not resolved_cwd.startswith(os.path.abspath(base_dir)):
        resolved_cwd = base_dir
    try:
        os.makedirs(resolved_cwd, exist_ok=True)
        os.chdir(resolved_cwd)
    except Exception as e:
        print(f"Failed to change directory to {{resolved_cwd}}: {{e}}", file=sys.stderr)
        sys.exit(1)
else:
    try:
        os.chdir(base_dir)
    except Exception:
        pass

try:
    proc = subprocess.run(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout={timeout_sec},
    )
    sys.stdout.buffer.write(proc.stdout)
    sys.stderr.buffer.write(proc.stderr)
    sys.exit(proc.returncode)
except subprocess.TimeoutExpired:
    print(f"Command timed out after {timeout_sec} seconds", file=sys.stderr)
    sys.exit(-1)
except Exception as e:
    print(f"Failed to run command: {{e}}", file=sys.stderr)
    sys.exit(-1)
"""

        # Execute the wrapper script inside the sandbox using the standard run_code executor
        run_code_input = {
            "code": python_code,
            "language": "python",
            "allow_network": True,  # Network access governed by the token role
        }

        # Retrieve RunCodeTool instance and run it
        from thinkdome.platform.orchestration.tools import registry
        run_tool = registry.get_tool("run_code")
        if not run_tool:
            raise RuntimeError("run_code tool not found in registry")
        
        run_result_str = await run_tool.func(run_code_input)
        run_result = json.loads(run_result_str)

        return json.dumps({
            "stdout": run_result.get("stdout", ""),
            "stderr": run_result.get("stderr", ""),
            "exit_code": run_result.get("exit_code", -1),
            "timed_out": run_result.get("timed_out", False),
        }, indent=2)


@register_tool
class SnapshotSandboxTool(BaseTool):
    name = "snapshot_sandbox"
    description = "Take a point-in-time snapshot checkpoint of the active sandbox state and workspace for backtracking"
    required_scope = "sandbox:snapshot"

    async def execute(self, tool_input: dict[str, Any]) -> str:
        ctx = get_context()
        sandbox_id = tool_input.get("sandbox_id") or ctx.sandbox_id or "default_sandbox"
        tag = tool_input.get("tag") or tool_input.get("name")
        description = tool_input.get("description", "")
        workspace_path = str(ctx.workspace_dir) if ctx.workspace_dir else None

        from thinkdome.sandbox.snapshots.service import SnapshotService
        svc = getattr(ctx.execution_service, "snapshot_service", None) or SnapshotService()
        meta = svc.create_snapshot(
            sandbox_id=sandbox_id,
            tag=tag,
            description=description,
            owner=ctx.username,
            workspace_path=workspace_path,
        )
        return json.dumps(meta, indent=2)


@register_tool
class RestoreSandboxTool(BaseTool):
    name = "restore_sandbox"
    description = "Backtrack sandbox state and workspace files back to a previously saved snapshot checkpoint"
    required_scope = "sandbox:restore"

    async def execute(self, tool_input: dict[str, Any]) -> str:
        ctx = get_context()
        sandbox_id = tool_input.get("sandbox_id") or ctx.sandbox_id or "default_sandbox"
        snapshot_id = tool_input.get("snapshot_id")
        if not snapshot_id:
            raise ValueError("Parameter 'snapshot_id' is required for restore_sandbox.")
        workspace_path = str(ctx.workspace_dir) if ctx.workspace_dir else None

        from thinkdome.sandbox.snapshots.service import SnapshotService
        svc = getattr(ctx.execution_service, "snapshot_service", None) or SnapshotService()
        res = svc.restore_snapshot(
            sandbox_id=sandbox_id,
            snapshot_id=snapshot_id,
            workspace_path=workspace_path,
        )
        return json.dumps(res, indent=2)


@register_tool
class ListSnapshotsTool(BaseTool):
    name = "list_snapshots"
    description = "List all available snapshot checkpoints for backtracking agent workflows"
    required_scope = "sandbox:snapshot"

    async def execute(self, tool_input: dict[str, Any]) -> str:
        ctx = get_context()
        sandbox_id = tool_input.get("sandbox_id") or ctx.sandbox_id
        from thinkdome.sandbox.snapshots.service import SnapshotService
        svc = getattr(ctx.execution_service, "snapshot_service", None) or SnapshotService()
        snaps = svc.list_snapshots(sandbox_id=sandbox_id, owner=ctx.username)
        return json.dumps({"snapshots": snaps}, indent=2)


@register_tool
class HostHtmlTool(BaseTool):
    name = "host_html"
    description = "Host HTML content temporarily on HTTP/Apache web server with a clean unique token URL and automatic TTL timeout"
    required_scope = "web:host"

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import secrets
        import shutil
        from pathlib import Path

        html = tool_input.get("html")
        if not html:
            raise ValueError("Parameter 'html' is required for host_html.")

        filename = tool_input.get("filename", "index.html")
        site_name = tool_input.get("site_name", "hosted_site")
        port = tool_input.get("port", 8080)
        ttl_sec = min(max(int(tool_input.get("ttl_sec", 300)), 10), 86400)
        ctx = get_context()

        # Dynamically sync TTL text in HTML markup if standard template placeholder or 300 Seconds is present
        import re
        ttl_text = f"{ttl_sec} Seconds"
        html = re.sub(r'300\s*Seconds', ttl_text, html, flags=re.IGNORECASE)
        html = html.replace('{ttl_sec}', str(ttl_sec))

        # Generate clean, obfuscated random token for URL (no site_name exposed)
        site_id = secrets.token_hex(12)

        # Save HTML file locally in storage/hosted_sites/{site_id}/{filename} for FastAPI serving
        storage_dir = Path(__file__).resolve().parents[3] / "storage" / "hosted_sites" / site_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        html_path = storage_dir / filename
        html_path.write_text(html, encoding="utf-8")

        # Schedule auto-cleanup of hosted site files after ttl_sec
        def cleanup_site():
            time.sleep(ttl_sec)
            if storage_dir.exists():
                shutil.rmtree(storage_dir, ignore_errors=True)

        threading.Thread(target=cleanup_site, daemon=True).start()

        # Build python runner script that saves HTML inside container as well
        python_code = f"""
import os, sys, subprocess, time, socket, threading

site_base = "/workspace" if os.path.exists("/workspace") else os.getcwd()
site_dir = os.path.abspath(os.path.join(site_base, "{site_name}"))
os.makedirs(site_dir, exist_ok=True)
filepath = os.path.join(site_dir, "{filename}")

with open(filepath, "w", encoding="utf-8") as f:
    f.write({repr(html)})

# Attempt Apache Web Server hosting if apachectl or apache2 is present
apache_started = False
try:
    for cmd in ["apachectl start", "service apache2 start", "systemctl start apache2", "apache2ctl start"]:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            apache_started = True
            for docroot in ["/var/www/html", "/var/www"]:
                if os.path.exists(docroot) and os.access(docroot, os.W_OK):
                    target = os.path.join(docroot, "{filename}")
                    with open(target, "w", encoding="utf-8") as f:
                        f.write({repr(html)})
            break
except Exception:
    pass

server_type = "Apache HTTP Server" if apache_started else "HTTP Temporary Server"
hosted_url = "http://localhost:8000/v1/hosted/{site_id}"

print(f"✅ HTML Content Hosted Successfully")
print(f"Web Engine: {{server_type}}")
print(f"Site Token: {site_id}")
print(f"Document File: {{filepath}}")
print(f"TTL Timeout: {ttl_sec} seconds")
print(f"Access URL: {{hosted_url}}")
sys.stdout.flush()
"""

        exec_req = ExecuteRequest(
            code=python_code,
            language="python",
            security_profile=tool_input.get("security_profile", "HIGH_SECURITY"),
            caller_role=ctx.caller_role,
            allow_network=True,
            timeout_ms=10000,
            username=ctx.username,
        )

        resp = await ctx.execution_service.execute(exec_req)

        hosted_url = f"http://localhost:8000/v1/hosted/{site_id}"

        result_dict = {
            "status": "hosted",
            "site_id": site_id,
            "filename": filename,
            "port": port,
            "ttl_sec": ttl_sec,
            "url": hosted_url,
            "stdout": resp.stdout,
            "stderr": resp.stderr,
            "exit_code": resp.exit_code,
        }

        return json.dumps(result_dict, indent=2)


