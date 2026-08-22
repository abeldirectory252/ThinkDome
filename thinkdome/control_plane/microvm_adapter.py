"""Node-local MicroVM implementation of the orchestrator contract."""

from __future__ import annotations

import asyncio
from typing import Dict

from thinkdome.sandbox.executors.base import ExecRequest
from thinkdome.sandbox.executors.microvm.executor import MicroVMExecutor
from thinkdome.control_plane.orchestrator import (
    NodeOrchestrator,
    OrchestratorAuthorization,
    OrchestratorExecutionRequest,
    OrchestratorResult,
    OrchestratorSandboxRequest,
)


class MicroVMNodeAdapter(NodeOrchestrator):
    """Maps one control-plane sandbox ID to one node-local MicroVM instance."""

    def __init__(self, executor: MicroVMExecutor) -> None:
        self.executor = executor
        self._sandbox_vms: Dict[str, str] = {}

    async def create_sandbox(self, request: OrchestratorSandboxRequest) -> None:
        sandbox_id = request.authorization.sandbox_id
        if sandbox_id in self._sandbox_vms:
            return
        instance = await asyncio.to_thread(
            self.executor.spawn_vm,
            name=f"sandbox-{sandbox_id}",
            memory_mb=max(1, request.memory_bytes // (1024 * 1024)),
            vcpus=max(1, (request.cpu_millis + 999) // 1000),
        )
        self._sandbox_vms[sandbox_id] = instance.vm_id

    async def execute(self, request: OrchestratorExecutionRequest) -> OrchestratorResult:
        sandbox_id = request.authorization.sandbox_id
        if sandbox_id not in self._sandbox_vms:
            raise RuntimeError(f"sandbox '{sandbox_id}' is not provisioned on this node")
        result = await self.executor.execute(ExecRequest(
            code=request.code,
            language=request.language,
            stdin=request.stdin,
            env_vars=dict(request.environment),
        ))
        return OrchestratorResult(
            request_id=request.authorization.request_id,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
            error_code=getattr(result, "error_code", None),
        )

    async def pause_sandbox(self, authorization: OrchestratorAuthorization) -> None:
        raise NotImplementedError("MicroVM pause/resume requires snapshot support")

    async def resume_sandbox(self, authorization: OrchestratorAuthorization) -> None:
        raise NotImplementedError("MicroVM pause/resume requires snapshot support")

    async def terminate_sandbox(self, authorization: OrchestratorAuthorization) -> None:
        vm_id = self._sandbox_vms.pop(authorization.sandbox_id, None)
        if vm_id:
            await self.executor.destroy_vm(vm_id)
