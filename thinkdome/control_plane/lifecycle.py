"""Durable, idempotent control-plane lifecycle orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from thinkdome.control_plane.contracts import (
    NodeHeartbeat,
    SandboxPlacement,
    SandboxPlacementRequest,
)
from thinkdome.control_plane.placement import choose_node
from thinkdome.control_plane.repository import ControlPlaneRepository
from thinkdome.control_plane.quota import ProjectQuota, ProjectUsage


class IdempotencyConflict(ValueError):
    """An idempotency key was reused for a different tenant or operation."""


@dataclass(frozen=True)
class ProvisionedSandbox:
    """Control-plane result; node provisioning happens after this commit."""

    sandbox_id: str
    node_id: str
    organization_id: str
    project_id: str
    placement_version: int


class ControlPlaneLifecycle:
    """Coordinates durable intent before delegating to a node orchestrator."""

    def __init__(self, repository: ControlPlaneRepository) -> None:
        self.repository = repository

    def register_node(self, heartbeat: NodeHeartbeat):
        return self.repository.record_heartbeat(heartbeat)

    def create_sandbox(
        self,
        request: SandboxPlacementRequest,
        nodes: Iterable[NodeHeartbeat],
        *,
        idempotency_key: str,
        quota: ProjectQuota | None = None,
        usage: ProjectUsage | None = None,
    ) -> ProvisionedSandbox:
        if not idempotency_key or len(idempotency_key) > 256:
            raise ValueError("idempotency_key is required and must be <= 256 characters")
        existing = self.repository.get_idempotency(
            request.organization_id, "create_sandbox", idempotency_key
        )
        if existing:
            existing_res_id = getattr(existing, "resource_id", getattr(existing, "sandbox_id", None))
            if getattr(existing, "project_id", None) != request.project_id or existing_res_id != request.sandbox_id:
                raise IdempotencyConflict("idempotency key belongs to another project or sandbox")
            payload = json.loads(existing.response_json)
            return ProvisionedSandbox(**payload)

        get_placement = getattr(self.repository, "get_placement", None)
        if get_placement:
            prior = get_placement(request.sandbox_id)
            if prior:
                raise IdempotencyConflict("sandbox ID is already allocated")

        # Keep the service compatible with lightweight repository adapters used by
        # workers/tests while the production repository remains ORM-backed.
        if quota is None:
            get_quota = getattr(self.repository, "get_project_quota", None)
            if get_quota:
                try:
                    quota = get_quota(request.project_id, request.organization_id)
                except TypeError:
                    quota = get_quota(request.project_id)
            else:
                quota = ProjectQuota()
        if usage is None:
            get_usage = getattr(self.repository, "get_project_usage", None)
            usage = (
                get_usage(request.organization_id, request.project_id)
                if get_usage
                else ProjectUsage()
            )
        effective_quota = quota
        effective_usage = usage
        effective_quota.check(request, effective_usage)

        placement = choose_node(request, nodes)
        reserve_capacity = getattr(self.repository, "reserve_node_capacity", None)
        if reserve_capacity:
            reserve_capacity(placement.node_id, request)
        self.repository.save_placement(placement)
        reserve = getattr(self.repository, "reserve_sandbox", None)
        if reserve:
            reserve(request, placement)
        result = ProvisionedSandbox(
            sandbox_id=placement.sandbox_id,
            node_id=placement.node_id,
            organization_id=placement.organization_id,
            project_id=placement.project_id,
            placement_version=placement.placement_version,
        )
        persisted = self.repository.save_idempotency(
            request.organization_id,
            request.project_id,
            "create_sandbox",
            idempotency_key,
            result.sandbox_id,
            result.__dict__,
        )
        if persisted and getattr(persisted, "response_json", None):
            # If another worker inserted the same idempotency key while this
            # worker was reserving capacity, undo this worker's extra
            # reservation before replaying the winner's response.
            if getattr(persisted, "_created_by_call", True) is False:
                release = getattr(self.repository, "release_node_capacity", None)
                if release:
                    release(placement.node_id, request)
            return ProvisionedSandbox(**json.loads(persisted.response_json))
        return result
