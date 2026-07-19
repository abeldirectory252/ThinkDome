"""ERP Lifecycle Hooks.

Executed dynamically during core events and operations.
Includes automated Chart of Accounts seeding on first boot.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from thinkdome.apps.erp.models.accounting import Account

logger = logging.getLogger(__name__)


def seed_chart_of_accounts() -> None:
    """Pre-populate the Chart of Accounts if it is currently empty."""
    try:
        # Check if accounts exist
        existing_count = len(Account.query().all())
        if existing_count > 0:
            return  # Already seeded

        logger.info("Initializing default Chart of Accounts seed data...")
        seed_path = Path(__file__).parent / "seed" / "chart_of_accounts.json"
        if not seed_path.exists():
            logger.warning(f"Chart of Accounts seed file not found at {seed_path}")
            return

        with open(seed_path, "r", encoding="utf-8") as f:
            coa_data = json.load(f)

        # Accounts list maps names to Account records
        account_map = {}

        for item in coa_data:
            # Check parent ID resolution
            parent_name = item.get("parent_account")
            parent_id = None
            if parent_name:
                parent_id = account_map.get(parent_name)

            acc = Account(
                name=item["name"],
                account_type=item["account_type"],
                root_type=item["root_type"],
                parent_account=parent_id,
                balance=0.0,
                currency="USD",
                is_group=item.get("is_group", False)
            )
            acc.save()
            account_map[item["name"]] = acc.id

        logger.info(f"Successfully seeded {len(coa_data)} Chart of Accounts nodes.")

    except Exception as e:
        logger.error(f"Error seeding Chart of Accounts: {e}")


# Run seed routine automatically on import (safely checking if DB exists)
try:
    seed_chart_of_accounts()
except Exception:
    # Safely pass if database schema is not fully established yet
    pass

# Hooks dictionary mapping core pipeline triggers to callbacks
hooks = {
    "erp.before_invoice_submit": [],
    "erp.after_payment_reconcile": [],
}
