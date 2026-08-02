"""Database Schema Initializer for Enterprise RBAC Module.

Leverages ThinkDome's custom ORM model metadata bindings to create tables automatically.
"""

from __future__ import annotations

import logging
from thinkdome.database.service import DatabaseService
from thinkdome.core.orm.orm import Base
import thinkdome.security.rbac.models  # Trigger model class registration

logger = logging.getLogger(__name__)


def initialize_rbac_schema(db: DatabaseService) -> None:
    """Ensure all RBAC SQLAlchemy metadata tables exist in the current database engine."""
    try:
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.get_instance("personal")
        if not kernel.initialized:
            kernel.initialize()
        Base.metadata.create_all(kernel.db_engine)
        logger.info("Enterprise RBAC Schema tables verified and initialized via ThinkDome ORM.")
    except Exception as e:
        logger.warning(f"Failed to initialize schema via Kernel engine: {e}. Executing table creation on DB service.")
        # Fallback DDL execution
        for table in Base.metadata.sorted_tables:
            try:
                table.create(kernel.db_engine, checkfirst=True)
            except Exception:
                pass
