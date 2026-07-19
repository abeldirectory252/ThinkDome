"""Audit configuration loader.

Loads materiality thresholds, business hours, SoD conflict matrix,
and sampling parameters from audit_config.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "audit_config.json"
_config_cache: Optional[Dict[str, Any]] = None


def _load_config() -> Dict[str, Any]:
    """Load and cache audit configuration."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load audit config: {e}. Using defaults.")
        _config_cache = {
            "materiality": {
                "percentage_of_revenue": 0.01,
                "percentage_of_assets": 0.005,
                "minimum_threshold": 1000,
                "round_number_threshold": 100,
            },
            "business_hours": {
                "start": "09:00",
                "end": "18:00",
                "timezone": "UTC",
                "weekend_days": [5, 6],
            },
            "thresholds": {
                "large_transaction_multiplier": 3.0,
                "duplicate_date_window_days": 30,
                "stale_reconciliation_days": 90,
                "backdated_entry_days": 30,
                "year_end_days": 15,
                "benford_chi_squared_critical": 15.507,
                "negative_stock_tolerance": 0.001,
            },
            "sampling": {
                "default_sample_size": 25,
                "max_sample_size": 100,
                "confidence_level": 0.95,
                "expected_error_rate": 0.01,
            },
            "sod_conflict_matrix": [],
        }
    return _config_cache


def reload_config() -> None:
    """Force reload of audit configuration."""
    global _config_cache
    _config_cache = None
    _load_config()


def get_materiality() -> Dict[str, Any]:
    """Return materiality threshold configuration."""
    return _load_config().get("materiality", {})


def get_materiality_threshold() -> float:
    """Return the minimum materiality threshold amount."""
    return get_materiality().get("minimum_threshold", 1000)


def get_business_hours() -> Dict[str, Any]:
    """Return business hours configuration."""
    return _load_config().get("business_hours", {})


def get_weekend_days() -> List[int]:
    """Return weekend day numbers (0=Monday, 6=Sunday)."""
    return get_business_hours().get("weekend_days", [5, 6])


def get_thresholds() -> Dict[str, Any]:
    """Return threshold configuration."""
    return _load_config().get("thresholds", {})


def get_sampling_config() -> Dict[str, Any]:
    """Return sampling configuration."""
    return _load_config().get("sampling", {})


def get_sod_matrix() -> List[Dict[str, str]]:
    """Return the segregation of duties conflict matrix."""
    return _load_config().get("sod_conflict_matrix", [])


def is_after_hours(hour: int, minute: int = 0) -> bool:
    """Check if a given time is outside business hours."""
    bh = get_business_hours()
    start_parts = bh.get("start", "09:00").split(":")
    end_parts = bh.get("end", "18:00").split(":")
    start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
    end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
    current_minutes = hour * 60 + minute
    return current_minutes < start_minutes or current_minutes >= end_minutes


def is_weekend(weekday: int) -> bool:
    """Check if a weekday number is a weekend (0=Monday, 6=Sunday)."""
    return weekday in get_weekend_days()
