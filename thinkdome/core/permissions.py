"""FastAPI Decorators and Authorization Dependencies for RBAC."""

from __future__ import annotations

import functools
from typing import Callable, Any, Optional
from fastapi import HTTPException, status, Depends, Request

from thinkdome.api.dependencies import get_current_user
from thinkdome.security.permission_evaluator import permission_evaluator


def has_permission(resource: str, action: str, module: str = "core") -> Callable:
    """Decorator to enforce dynamic permission checking on FastAPI path operations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract request and current_user from kwargs if injected by FastAPI
            request: Optional[Request] = kwargs.get("request")
            current_user: Optional[dict] = kwargs.get("current_user")

            if not current_user and request and hasattr(request.state, "user"):
                current_user = request.state.user

            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required to evaluate permission."
                )

            user_id = current_user.get("id") or current_user.get("user_id") or current_user.get("username")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid user identity context."
                )

            allowed = permission_evaluator.has_permission(
                user_id=user_id,
                module=module,
                resource=resource,
                action=action,
            )

            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied. Required permission: '{module}:{resource}:{action}'"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def has_role(role_name: str) -> Callable:
    """Decorator to enforce role checking on FastAPI path operations."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_user: Optional[dict] = kwargs.get("current_user")
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required."
                )

            user_id = current_user.get("id") or current_user.get("user_id") or current_user.get("username")
            if not permission_evaluator.has_role(user_id, role_name):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role permission denied. Required role: '{role_name}'"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


class PermissionChecker:
    """FastAPI Dependency class for inline route authorization checks."""

    def __init__(self, resource: str, action: str, module: str = "core") -> None:
        self.resource = resource
        self.action = action
        self.module = module

    def __call__(self, current_user: dict = Depends(get_current_user)) -> dict:
        user_id = current_user.get("id") or current_user.get("user_id") or current_user.get("username")
        allowed = permission_evaluator.has_permission(
            user_id=user_id,
            module=self.module,
            resource=self.resource,
            action=self.action,
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: '{self.module}:{self.resource}:{self.action}' required."
            )
        return current_user
