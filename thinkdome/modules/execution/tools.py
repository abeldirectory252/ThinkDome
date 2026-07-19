import os
import json
from typing import Any, Optional
from thinkdome.core.tools import BaseTool, register_tool, get_context
from thinkdome.modules.execution.execution_models import ExecuteRequest
from thinkdome.modules.orchestrator.orchestrator_models import RunCodeInput, ShellExecInput

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
        from thinkdome.core.tools import registry
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
