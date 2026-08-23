"""ThinkDome Dynamic API Router.

Automatically generates CRUD and custom action endpoints based on DocType structures,
verifying JWT session context and permissions.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from thinkdome.core.kernel.kernel import Kernel
from thinkdome.core.metadata.metadata import get_doctype_model
from thinkdome.core.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])

_DOCTYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _validate_doctype(doctype: str) -> str:
    """Reject malformed model names before metadata lookup."""
    if not _DOCTYPE_RE.fullmatch(doctype):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid DocType")
    return doctype


# ── Dynamic Metadata-Driven CRUD ──────────────────────────────────────────────

@router.get("/{doctype}")
async def list_records(
    doctype: str,
    limit: int = 100,
    offset: int = 0,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Retrieve list of records matching the DocType schema."""
    _validate_doctype(doctype)
    if limit < 1 or limit > 1000 or offset < 0:
        raise HTTPException(status_code=400, detail="Invalid pagination")
    model_class = get_doctype_model(doctype.capitalize())
    if not model_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocType '{doctype}' not found",
        )

    # Permission check: standard user can only list their own resources
    query = model_class.query().limit(limit).offset(offset)
    owner = user.get("workspace_id", user.get("username"))
    if user.get("role") != "ADMIN" and "owner" in model_class._fields:
        query = query.filter(owner=owner)

    records = query.all()
    return [r.to_dict() for r in records]


@router.post("/{doctype}")
async def create_record(
    doctype: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Create a new model record based on payload values."""
    _validate_doctype(doctype)
    model_class = get_doctype_model(doctype.capitalize())
    if not model_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocType '{doctype}' not found",
        )

    # Automatically bind owner to authenticated username
    if "owner" in model_class._fields:
        payload["owner"] = user.get("workspace_id", user.get("username"))

    try:
        instance = model_class(**payload)
        instance.save()
        return instance.to_dict()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{doctype}/{record_id}")
async def get_record(
    doctype: str,
    record_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Retrieve a single record detail by id."""
    _validate_doctype(doctype)
    model_class = get_doctype_model(doctype.capitalize())
    if not model_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocType '{doctype}' not found",
        )

    record = model_class.get(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found",
        )

    # Owner permission enforcement
    owner = user.get("workspace_id", user.get("username"))
    if user.get("role") != "ADMIN" and getattr(record, "owner", None) != owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to requested resource",
        )

    return record.to_dict()


@router.put("/{doctype}/{record_id}")
async def update_record(
    doctype: str,
    record_id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Modify attribute fields on an existing record."""
    _validate_doctype(doctype)
    model_class = get_doctype_model(doctype.capitalize())
    if not model_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocType '{doctype}' not found",
        )

    record = model_class.get(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found",
        )

    owner = user.get("workspace_id", user.get("username"))
    if user.get("role") != "ADMIN" and getattr(record, "owner", None) != owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied to edit record",
        )

    try:
        # Apply updates
        for k, v in payload.items():
            # Ownership is immutable for ordinary users; otherwise a caller
            # could update a record they own and transfer it to another user.
            if k == "owner" and user.get("role") != "ADMIN":
                continue
            if k in record._fields:
                record._values[k] = v
        record.save()
        return record.to_dict()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{doctype}/{record_id}")
async def delete_record(
    doctype: str,
    record_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Deletes or soft-deletes a record from the database."""
    _validate_doctype(doctype)
    model_class = get_doctype_model(doctype.capitalize())
    if not model_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DocType '{doctype}' not found",
        )

    record = model_class.get(record_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found",
        )

    owner = user.get("workspace_id", user.get("username"))
    if user.get("role") != "ADMIN" and getattr(record, "owner", None) != owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied to delete record",
        )

    record.delete(soft=True)
    return {"status": "success", "message": f"Record '{record_id}' deleted successfully"}
