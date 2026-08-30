"""MicroVM management API endpoints.
# _MICROVM_ADMIN_ROLES

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

from thinkdome.security.identity.core import is_admin_role


def _require_microvm_admin(user: dict) -> None:
    if not is_admin_role(user.get("role")):
        raise HTTPException(status_code=403, detail="MicroVM management requires an administrator role")


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
async def start_microvm(req: StartMicroVMRequest, request: Request, user: dict = Depends(get_current_user)):
    """Spawn a hardware-isolated MicroVM instance via Cloud Hypervisor/KVM."""
    _require_microvm_admin(user)
    try:
        executor = _get_microvm_executor(request)
        if not executor._initialized:
            await executor.initialize()

        inst = executor.spawn_vm(name=req.name, memory_mb=req.memory_mb, vcpus=req.vcpus)
        return {"status": "started", "vm": inst.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/microvm/list")
async def list_microvms(request: Request, user: dict = Depends(get_current_user)):
    """List all active MicroVM instances."""
    _require_microvm_admin(user)
    try:
        executor = _get_microvm_executor(request)
        return {"vms": [inst.to_dict() for inst in executor.instances.values()]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/microvm/{vm_id}")
async def get_microvm(vm_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Get details of a specific MicroVM instance."""
    _require_microvm_admin(user)
    executor = _get_microvm_executor(request)
    instance = executor.instances.get(vm_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")
    return {"vm": instance.to_dict()}


@router.delete("/microvm/{vm_id}")
async def stop_microvm(vm_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Shutdown and destroy a MicroVM instance (real CHV process + cleanup)."""
    _require_microvm_admin(user)
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
async def pause_microvm(vm_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Pause a running MicroVM (freezes guest CPU execution)."""
    _require_microvm_admin(user)
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
async def resume_microvm(vm_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Resume a paused MicroVM."""
    _require_microvm_admin(user)
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
async def snapshot_microvm(vm_id: str, req: SnapshotRequest, request: Request, user: dict = Depends(get_current_user)):
    """Take a full VM-level snapshot (memory + CPU + disk state).

    The VM is paused during the snapshot and automatically resumed after.
    """
    _require_microvm_admin(user)
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
async def restore_microvm(req: RestoreRequest, request: Request, user: dict = Depends(get_current_user)):
    """Restore a VM from a previous snapshot.

    Creates a new VM instance with the restored state.
    """
    _require_microvm_admin(user)
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
async def exec_in_microvm(vm_id: str, req: ExecRequest, request: Request, user: dict = Depends(get_current_user)):
    """Execute a command inside a running MicroVM guest via the HTTP command server."""
    _require_microvm_admin(user)
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
async def destroy_all_microvms(request: Request, user: dict = Depends(get_current_user)):
    """Destroy all active MicroVM instances and clean up infrastructure."""
    _require_microvm_admin(user)
    executor = _get_microvm_executor(request)
    try:
        await executor.shutdown()
        return {"status": "all_destroyed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
