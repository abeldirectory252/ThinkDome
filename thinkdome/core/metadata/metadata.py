"""ThinkDome Metadata Parser.

Dynamically maps JSON/YAML DocType descriptions to Python ORM classes,
automatically registering schemas for database creation and API routing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, Type, Optional

from thinkdome.core.orm.orm import (
    Model,
    Field,
    StringField,
    IntegerField,
    FloatField,
    BooleanField,
    SelectField,
)

logger = logging.getLogger(__name__)

# Global registry tracking dynamic models created from DocType manifests
_doctype_registry: Dict[str, Type[Model]] = {}


def load_doctype_manifest(path: Path) -> Type[Model]:
    """Parse JSON manifest, construct ORM class dynamically, and register it."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    name = data["name"]
    if name in _doctype_registry:
        return _doctype_registry[name]

    attrs: Dict[str, Any] = {}

    for field_meta in data.get("fields", []):
        fname = field_meta["name"]
        ftype = field_meta["type"]
        frequired = field_meta.get("required", False)
        fdefault = field_meta.get("default", None)

        if ftype == "String":
            attrs[fname] = StringField(required=frequired, default=fdefault)
        elif ftype == "Integer":
            attrs[fname] = IntegerField(required=frequired, default=fdefault)
        elif ftype == "Float":
            attrs[fname] = FloatField(required=frequired, default=fdefault)
        elif ftype == "Boolean":
            attrs[fname] = BooleanField(required=frequired, default=fdefault)
        elif ftype == "Select":
            attrs[fname] = SelectField(
                choices=field_meta.get("options", []),
                required=frequired,
                default=fdefault,
            )
        else:
            # Fallback default type
            attrs[fname] = StringField(required=frequired, default=fdefault)

    # Instantiate class using the metaclass structure of Model
    model_class = type(name, (Model,), attrs)
    _doctype_registry[name] = model_class

    logger.info(f"✓ Registered DocType model: {name}")
    return model_class


def get_doctype_model(name: str) -> Optional[Type[Model]]:
    """Retrieve dynamic ORM model by its DocType name identifier."""
    return _doctype_registry.get(name)
