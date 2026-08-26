"""Initialize Workspace Desk tables registered with the ThinkDome ORM."""

import logging

from thinkdome.core.orm.orm import Base
import thinkdome.platform.storage.workspaces.entities  # register ORM models

logger = logging.getLogger(__name__)


def initialize_workspace_schema() -> None:
    from thinkdome.core.kernel.kernel import Kernel
    kernel = Kernel.current()
    if not kernel.initialized:
        kernel.initialize()
    Base.metadata.create_all(kernel.db_engine)
    for table in ("workspace_records", "workspace_desk_pages", "workspace_desk_menus"):
        for index in Base.metadata.tables[table].indexes:
            index.create(kernel.db_engine, checkfirst=True)
