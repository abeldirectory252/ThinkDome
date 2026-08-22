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
            # Shell commands are offline by default.  Network access must be
            # explicitly requested and is still constrained by caller role.
            "allow_network": bool(tool_input.get("allow_network", False)),
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

        # Hosted content is persisted by the control plane, not by the
        # unprivileged execution container.  Keep the document name confined
        # to the generated site directory as an additional path-safety check.
        filename = Path(str(tool_input.get("filename", "index.html"))).name
        if not filename or filename in {".", ".."}:
            filename = "index.html"
        port = tool_input.get("port", 8080)
        ttl_sec = min(max(int(tool_input.get("ttl_sec", 300)), 10), 86400)
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

        hosted_url = f"http://localhost:8000/v1/hosted/{site_id}"
        stdout = (
            "✅ HTML Content Hosted Successfully\n"
            "Web Engine: ThinkDome hosted storage\n"
            f"Site Token: {site_id}\n"
            f"Document File: {filename}\n"
            f"TTL Timeout: {ttl_sec} seconds\n"
            f"Access URL: {hosted_url}\n"
        )

        result_dict = {
            "status": "hosted",
            "site_id": site_id,
            "filename": filename,
            "port": port,
            "ttl_sec": ttl_sec,
            "url": hosted_url,
            "stdout": stdout,
            "stderr": "",
            "exit_code": 0,
        }

        return json.dumps(result_dict, indent=2)
