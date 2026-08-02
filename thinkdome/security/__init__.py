"""Security domain — identity, auth, RBAC, vault, scanner & permissions.

Subdirectories:
  - auth/         : AuthService, CredentialVault
  - rbac/         : RBAC services, models, schema
  - identity/     : Core security primitives, permissions, evaluator, cache
  - scanner/      : Static security scanner
  - repositories/ : Database repositories for users, roles, permissions, audit
  - api/          : REST API routers for auth, admin, RBAC
"""

from thinkdome.security.auth.service import AuthService
from thinkdome.security.auth.vault import CredentialVault
from thinkdome.security.rbac.service import UserService, RoleService, PermissionService
from thinkdome.security.scanner.service import SecurityScanner

__all__ = [
    "AuthService",
    "CredentialVault",
    "UserService",
    "RoleService",
    "PermissionService",
    "SecurityScanner",
]
