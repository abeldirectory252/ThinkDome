"""ThinkDome Custom ORM.

Implements model base classes, field descriptors, query builders, transactions,
and soft deletion mapped dynamically to SQLAlchemy tables under the hood.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple, Type
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    Table,
    UniqueConstraint,
    select,
    insert,
    update,
    delete,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


# ── Field Descriptors ─────────────────────────────────────────────────────────

class Field:
    """Base class for all model fields representing metadata structure."""

    def __init__(
        self,
        required: bool = False,
        default: Any = None,
        choices: Optional[List[Any]] = None,
        primary_key: bool = False,
    ) -> None:
        self.name = ""
        self.required = required
        self.default = default
        self.choices = choices
        self.primary_key = primary_key

    def __get__(self, instance: Optional[Model], owner: Type[Model]) -> Any:
        if instance is None:
            return self
        return instance._values.get(self.name, self.default)

    def __set__(self, instance: Model, value: Any) -> None:
        if self.choices and value is not None and value not in self.choices:
            raise ValueError(f"Value '{value}' for field '{self.name}' must be one of {self.choices}")
        instance._values[self.name] = value


class StringField(Field):
    """Textual field descriptor."""
    pass


class IntegerField(Field):
    """Integer field descriptor."""
    pass


class FloatField(Field):
    """Floating point numeric field descriptor."""
    pass


class BooleanField(Field):
    """Boolean flag field descriptor."""
    pass


class SelectField(Field):
    """Select option list field descriptor."""

    def __init__(self, choices: List[Any], **kwargs) -> None:
        super().__init__(choices=choices, **kwargs)


class UUIDField(Field):
    """UUID token field descriptor auto-generating random IDs."""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("default", lambda: str(uuid.uuid4()))
        super().__init__(**kwargs)


def _get_active_db():
    from thinkdome.core.kernel.kernel import Kernel
    kernel = Kernel.current()
    if not kernel.initialized:
        kernel.initialize()
    return kernel.db


# ── Query Builder ─────────────────────────────────────────────────────────────

class Query:
    """Chainable Query Builder translating ORM constraints into database results."""

    def __init__(self, model_class: Type[Model]) -> None:
        self.model_class = model_class
        self.filters: Dict[str, Any] = {}
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None

    def filter(self, **kwargs) -> Query:
        """Add exact match filter criteria."""
        self.filters.update(kwargs)
        return self

    def limit(self, value: int) -> Query:
        """Limit maximum row count returned."""
        self._limit = value
        return self

    def offset(self, value: int) -> Query:
        """Skip a specified number of initial rows."""
        self._offset = value
        return self

    def all(self) -> List[Model]:
        """Fetch all records matching filters."""
        db = _get_active_db()
        
        table = self.model_class._table
        stmt = select(table)

        # Include soft-delete check by default if column exists
        if "is_deleted" in table.c:
            stmt = stmt.where(table.c.is_deleted == False)

        for key, val in self.filters.items():
            if key in table.c:
                stmt = stmt.where(table.c[key] == val)

        if self._limit is not None:
            stmt = stmt.limit(self._limit)
        if self._offset is not None:
            stmt = stmt.offset(self._offset)

        results = db.execute(stmt).all()
        models = []
        for row in results:
            # Map row mappings back to model values
            row_dict = dict(row._mapping)
            model_inst = self.model_class(_loaded=True, **row_dict)
            models.append(model_inst)
        return models

    def first(self) -> Optional[Model]:
        """Fetch the first record matching filters or None."""
        self._limit = 1
        res = self.all()
        return res[0] if res else None


# ── Model Metaclass ───────────────────────────────────────────────────────────

class ModelMetaclass(type):
    """Metaclass mapping Field attributes to SQLAlchemy Table definitions."""

    def __new__(cls, name: str, bases: tuple, attrs: dict) -> Any:
        if name == "Model":
            return super().__new__(cls, name, bases, attrs)

        fields: Dict[str, Field] = {}
        for k, v in list(attrs.items()):
            if isinstance(v, Field):
                v.name = k
                fields[k] = v

        attrs["_fields"] = fields
        attrs.setdefault("__tablename__", name.lower() + "s")

        # Map to SQLAlchemy Columns registered on shared Base metadata
        columns = [
            Column("id", String, primary_key=True, default=lambda: str(uuid.uuid4())),
            Column("is_deleted", Boolean, default=False),
        ]

        for fname, fval in fields.items():
            if fname == "id":
                continue
            
            # Map Python ORM field types to SQLAlchemy SQL types
            col_type: Any = String
            if isinstance(fval, IntegerField):
                col_type = Integer
            elif isinstance(fval, FloatField):
                col_type = Float
            elif isinstance(fval, BooleanField):
                col_type = Boolean

            columns.append(
                Column(
                    fname,
                    col_type,
                    nullable=not fval.required,
                    default=fval.default,
                )
            )

        # Dynamic table binding
        constraints = []
        unique_together = attrs.get("__unique_together__", ())
        if unique_together:
            constraints.append(UniqueConstraint(*unique_together))
        table = Table(
            attrs["__tablename__"], Base.metadata, *columns, *constraints,
            extend_existing=True,
        )
        attrs["_table"] = table

        model_class = super().__new__(cls, name, bases, attrs)
        
        # Auto-register to metadata registry for dynamic API routing
        from thinkdome.core.metadata.metadata import _doctype_registry
        _doctype_registry[name] = model_class
        
        return model_class


# ── Base Model Class ──────────────────────────────────────────────────────────

class Model(metaclass=ModelMetaclass):
    """Base class for all ThinkDome metadata-driven ORM entities."""

    def __init__(self, _loaded: bool = False, **kwargs) -> None:
        self._values: Dict[str, Any] = {}
        self._loaded = _loaded
        
        # Load default values
        for name, field in self._fields.items():
            default = field.default
            if callable(default):
                default = default()
            self._values[name] = default

        self._values.setdefault("id", str(uuid.uuid4()))
        self._values.setdefault("is_deleted", False)

        for k, v in kwargs.items():
            self._values[k] = v

    @property
    def id(self) -> str:
        return self._values["id"]

    @classmethod
    def query(cls) -> Query:
        """Create a new chainable Query builder context."""
        return Query(cls)

    @classmethod
    def get(cls, doc_id: str) -> Optional[Model]:
        """Fetch a single record by its primary key ID."""
        return cls.query().filter(id=doc_id).first()

    def save(self) -> None:
        """Persist current model state (inserts or updates record in DB)."""
        db = _get_active_db()

        # Run before_validate and after_validate hooks
        self._run_hook("before_validate")
        self.validate()
        self._run_hook("after_validate")

        table = self._table
        
        if not self._loaded:
            self._run_hook("before_create")
            stmt = insert(table).values(**self._values)
            db.execute(stmt)
            db.commit()
            self._loaded = True
            self._run_hook("after_create")
        else:
            self._run_hook("before_update")
            stmt = update(table).where(table.c.id == self.id).values(**self._values)
            db.execute(stmt)
            db.commit()
            self._run_hook("after_update")

    def delete(self, soft: bool = True) -> None:
        """Remove record from database. Performs soft-deletion by default."""
        db = _get_active_db()

        self._run_hook("before_delete")
        table = self._table

        if soft:
            self._values["is_deleted"] = True
            stmt = update(table).where(table.c.id == self.id).values(is_deleted=True)
            db.execute(stmt)
        else:
            stmt = delete(table).where(table.c.id == self.id)
            db.execute(stmt)

        db.commit()
        self._run_hook("after_delete")

    def validate(self) -> None:
        """Execute validation constraints for required fields and selections."""
        for name, field in self._fields.items():
            val = self._values.get(name)
            if field.required and val is None:
                raise ValueError(f"Field '{name}' is marked as required but holds no value.")

    def to_dict(self) -> Dict[str, Any]:
        """Convert model representation to JSON-serializable dictionary."""
        return self._values.copy()

    def _run_hook(self, hook_name: str) -> None:
        """Dynamically invoke registry hooks linked to this model."""
        from thinkdome.core.kernel.kernel import Kernel
        kernel = Kernel.current()
        callbacks = kernel.hooks.get(f"{self.__class__.__name__.lower()}.{hook_name}", [])
        for callback in callbacks:
            callback(self)
