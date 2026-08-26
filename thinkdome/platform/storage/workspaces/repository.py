"""ORM repositories for Workspace Desk records."""

from thinkdome.security.repositories.base import BaseRepository
from thinkdome.platform.storage.workspaces.entities import WorkspaceDeskMenu, WorkspaceDeskPage, WorkspaceRecord


class WorkspaceRepository(BaseRepository[WorkspaceRecord]):
    def __init__(self) -> None:
        super().__init__(WorkspaceRecord)

    def for_owner(self, owner_id: str):
        return self.find_by(owner_id=owner_id)


class WorkspaceDeskPageRepository(BaseRepository[WorkspaceDeskPage]):
    def __init__(self) -> None:
        super().__init__(WorkspaceDeskPage)

    def for_workspace(self, workspace_id: str):
        return self.find_by(workspace_id=workspace_id)


class WorkspaceDeskMenuRepository(BaseRepository[WorkspaceDeskMenu]):
    def __init__(self) -> None:
        super().__init__(WorkspaceDeskMenu)

    def for_workspace(self, workspace_id: str):
        return self.find_one_by(workspace_id=workspace_id)
