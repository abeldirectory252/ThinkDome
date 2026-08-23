"""MicroVM management API endpoints.

Provides REST API for managing Cloud Hypervisor MicroVM instances:
  - Start / Stop / List VMs
  - Pause / Resume VMs
  - Snapshot / Restore VMs
  - Execute commands inside guest VMs via vsock
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from thinkdome.core.dependencies import get_current_user

from thinkdome.sandbox.executors.microvm import MicroVMExecutor, VMStatus

router = APIRouter(tags=["microvm"], dependencies=[Depends(get_current_user)])


# ─── Request/Response Models ────────────────────────────────────────────────

class StartMicroVMRequest(BaseModel):
    name: str = Field("agent-microvm", description="Name of the MicroVM instance")
    vcpus: int = Field(2, description="Number of virtual CPUs")
    memory_mb: int = Field(512, description="Guest memory in MB")


class SnapshotRequest(BaseModel):
    snapshot_id: Optional[str] = Field(None, description="Custom snapshot ID (auto-generated if omitted)")
    description: str = Field("", description="Human-readable description")


class RestoreRequest(BaseModel):
    snapshot_id: str = Field(..., description="ID of the snapshot to restore from")
    vm_name: str = Field("restored-vm", description="Name for the restored VM")


class ExecRequest(BaseModel):
    cmd: str = Field(..., description="Shell command to execute inside the guest")
    blocking: bool = Field(True, description="Wait for command completion")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_microvm_executor(request: Request) -> MicroVMExecutor:
    """Extract or create a MicroVMExecutor from the app state."""
    try:
        execution_service = request.app.state.execution_service
        executor = execution_service._get_executor("python")
        if isinstance(executor, MicroVMExecutor):
            return executor
    except Exception:
        pass

    # Fallback: create a standalone executor
    from thinkdome.core.config import get_settings
    executor = MicroVMExecutor(get_settings())
    return executor


# ─── VM Lifecycle Endpoints ──────────────────────────────────────────────────

@router.post("/microvm/start", status_code=201)
async def start_microvm(req: StartMicroVMRequest, request: Request):
    """Spawn a hardware-isolated MicroVM instance via Cloud Hypervisor/KVM."""
    try:
        executor = _get_microvm_executor(request)
        if not executor._initialized:
            await executor.initialize()

        inst = executor.spawn_vm(name=req.name, memory_mb=req.memory_mb, vcpus=req.vcpus)
        return {"status": "started", "vm": inst.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/microvm/list")
async def list_microvms(request: Request):
    """List all active MicroVM instances."""
    try:
        executor = _get_microvm_executor(request)
        return {"vms": [inst.to_dict() for inst in executor.instances.values()]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/microvm/{vm_id}")
async def get_microvm(vm_id: str, request: Request):
    """Get details of a specific MicroVM instance."""
    executor = _get_microvm_executor(request)
    instance = executor.instances.get(vm_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")
    return {"vm": instance.to_dict()}


@router.delete("/microvm/{vm_id}")
async def stop_microvm(vm_id: str, request: Request):
    """Shutdown and destroy a MicroVM instance (real CHV process + cleanup)."""
    try:
        executor = _get_microvm_executor(request)
        if vm_id not in executor.instances:
            raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")

        await executor.destroy_vm(vm_id)
        return {"status": "destroyed", "vm_id": vm_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── VM State Control ───────────────────────────────────────────────────────

@router.post("/microvm/{vm_id}/pause")
async def pause_microvm(vm_id: str, request: Request):
    """Pause a running MicroVM (freezes guest CPU execution)."""
    executor = _get_microvm_executor(request)
    instance = executor.instances.get(vm_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")
    if not instance.chv_client:
        raise HTTPException(status_code=500, detail="VM has no CHV API client")

    try:
        instance.chv_client.pause_vm()
        from thinkdome.sandbox.executors.microvm import VMStatus
        instance.status = VMStatus.PAUSED
        return {"status": "paused", "vm_id": vm_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microvm/{vm_id}/resume")
async def resume_microvm(vm_id: str, request: Request):
    """Resume a paused MicroVM."""
    executor = _get_microvm_executor(request)
    instance = executor.instances.get(vm_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")
    if not instance.chv_client:
        raise HTTPException(status_code=500, detail="VM has no CHV API client")

    try:
        instance.chv_client.resume_vm()
        from thinkdome.sandbox.executors.microvm import VMStatus
        instance.status = VMStatus.RUNNING
        return {"status": "resumed", "vm_id": vm_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Snapshot & Restore ─────────────────────────────────────────────────────

@router.post("/microvm/{vm_id}/snapshot")
async def snapshot_microvm(vm_id: str, req: SnapshotRequest, request: Request):
    """Take a full VM-level snapshot (memory + CPU + disk state).

    The VM is paused during the snapshot and automatically resumed after.
    """
    executor = _get_microvm_executor(request)
    if vm_id not in executor.instances:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")

    try:
        import uuid
        snapshot_id = req.snapshot_id or f"snap_{uuid.uuid4().hex[:12]}"
        result_id = await executor.snapshot_vm(vm_id, snapshot_id)
        return {"status": "snapshot_created", "snapshot_id": result_id, "vm_id": vm_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/microvm/restore")
async def restore_microvm(req: RestoreRequest, request: Request):
    """Restore a VM from a previous snapshot.

    Creates a new VM instance with the restored state.
    """
    executor = _get_microvm_executor(request)
    if not executor._initialized:
        await executor.initialize()

    try:
        instance = await executor.restore_vm(req.vm_name, req.snapshot_id)
        return {"status": "restored", "vm": instance.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Guest Command Execution ────────────────────────────────────────────────

@router.post("/microvm/{vm_id}/exec")
async def exec_in_microvm(vm_id: str, req: ExecRequest, request: Request):
    """Execute a command inside a running MicroVM guest via the HTTP command server."""
    executor = _get_microvm_executor(request)
    instance = executor.instances.get(vm_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")
    if not instance.guest_http_client:
        raise HTTPException(status_code=500, detail="VM has no guest HTTP client")

    try:
        output, error = await instance.guest_http_client.run_command(
            req.cmd, blocking=req.blocking
        )
        return {"output": output, "error": error, "vm_id": vm_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Destroy All ─────────────────────────────────────────────────────────────

@router.delete("/microvm")
async def destroy_all_microvms(request: Request):
    """Destroy all active MicroVM instances and clean up infrastructure."""
    executor = _get_microvm_executor(request)
    try:
        await executor.shutdown()
        return {"status": "all_destroyed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
