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
        indexed: bool = False,
        unique: bool = False,
    ) -> None:
        self.name = ""
        self.required = required
        self.default = default
        self.choices = choices
        self.primary_key = primary_key
        self.indexed = indexed
        self.unique = unique

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


class TextField(Field):
    """Unbounded text field, used for structured JSON owned by the ORM."""
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
        self._order_by: Optional[tuple[str, str]] = None

    def filter(self, **kwargs) -> Query:
        """Add exact match filter criteria."""
        self.filters.update(kwargs)
        return self

    def order_by(self, field: str, direction: str = "asc") -> Query:
        """Order records by field and direction ('asc' or 'desc')."""
        self._order_by = (field, direction.lower())
        return self

    def limit(self, value: int) -> Query:
        """Limit maximum row count returned."""
        self._limit = value
        return self

    def offset(self, value: int) -> Query:
        """Skip a specified number of initial rows."""
        self._offset = value
        return self

    def count(self) -> int:
        """Return total matching records count directly via ORM aggregation."""
        from sqlalchemy import func
        db = _get_active_db()
        table = self.model_class._table
        stmt = select(func.count()).select_from(table)

        if "is_deleted" in table.c and not getattr(self.model_class, "__omit_soft_delete__", False):
            stmt = stmt.where(table.c.is_deleted == False)

        for key, val in self.filters.items():
            if key.endswith("__in") and key[:-4] in table.c:
                values = tuple(val)
                if not values:
                    return 0
                stmt = stmt.where(table.c[key[:-4]].in_(values))
            elif key in table.c:
                stmt = stmt.where(table.c[key] == val)

        return db.execute(stmt).scalar() or 0

    def delete(self, soft: bool = True) -> int:
        """Delete records matching filter criteria directly via ORM."""
        db = _get_active_db()
        table = self.model_class._table

        if soft and "is_deleted" in table.c and not getattr(self.model_class, "__omit_soft_delete__", False):
            stmt = update(table).values(is_deleted=True)
            for key, val in self.filters.items():
                if key in table.c:
                    stmt = stmt.where(table.c[key] == val)
        else:
            stmt = delete(table)
            for key, val in self.filters.items():
                if key in table.c:
                    stmt = stmt.where(table.c[key] == val)

        res = db.execute(stmt)
        db.commit()
        return getattr(res, "rowcount", 0)

    def all(self) -> List[Model]:
        """Fetch all records matching filters."""
        db = _get_active_db()
        
        table = self.model_class._table
        stmt = select(table)

        # Include soft-delete check by default if column exists
        if "is_deleted" in table.c and not getattr(self.model_class, "__omit_soft_delete__", False):
            stmt = stmt.where(table.c.is_deleted == False)

        for key, val in self.filters.items():
            if key.endswith("__in") and key[:-4] in table.c:
                # Keep set-based reads inside the ORM instead of requiring
                # repositories to issue one lookup per related record.
                values = tuple(val)
                if not values:
                    return []
                stmt = stmt.where(table.c[key[:-4]].in_(values))
            elif key in table.c:
                stmt = stmt.where(table.c[key] == val)

        if self._order_by:
            field_name, direction = self._order_by
            if field_name in table.c:
                col = table.c[field_name]
                stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())

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
        primary_key_name = attrs.get("__primary_key__")
        if not primary_key_name:
            for fname, fval in fields.items():
                if getattr(fval, "primary_key", False):
                    primary_key_name = fname
                    break
        if not primary_key_name:
            primary_key_name = "id"
        attrs["__primary_key__"] = primary_key_name
        attrs["_primary_key_name"] = primary_key_name

        # Map to SQLAlchemy Columns registered on shared Base metadata
        primary_key_type = String
        if isinstance(fields.get(primary_key_name), IntegerField):
            primary_key_type = Integer
        primary_key_default = (lambda: str(uuid.uuid4())) if (primary_key_name == "id" and primary_key_type is String) else None
        columns = [
            Column(
                primary_key_name,
                primary_key_type,
                primary_key=True,
                default=primary_key_default,
            )
        ]
        if not attrs.get("__omit_soft_delete__", False):
            columns.append(Column("is_deleted", Boolean, default=False))

        for fname, fval in fields.items():
            if fname == primary_key_name:
                continue
            
            # Map Python ORM field types to SQLAlchemy SQL types
            col_type: Any = String
            if isinstance(fval, IntegerField):
                col_type = Integer
            elif isinstance(fval, TextField):
                col_type = Text
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
                    index=fval.indexed,
                    unique=fval.unique,
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

        primary_key_name = self.__class__._primary_key_name
        is_int_pk = isinstance(self._fields.get(primary_key_name), IntegerField)
        if not is_int_pk:
            self._values.setdefault(primary_key_name, str(uuid.uuid4()))
        else:
            self._values.setdefault(primary_key_name, None)
        if not self.__class__.__dict__.get("__omit_soft_delete__", False):
            self._values.setdefault("is_deleted", False)

        for k, v in kwargs.items():
            self._values[k] = v

    @property
    def id(self) -> Any:
        return self._values[self.__class__._primary_key_name]

    @classmethod
    def query(cls) -> Query:
        """Create a new chainable Query builder context."""
        return Query(cls)

    @classmethod
    def get(cls, doc_id: Any) -> Optional[Model]:
        """Fetch a single record by its primary key ID."""
        primary_key_name = cls._primary_key_name
        return cls.query().filter(**{primary_key_name: doc_id}).first()

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
            insert_vals = {
                k: v for k, v in self._values.items()
                if not (k == self.__class__._primary_key_name and v is None)
            }
            stmt = insert(table).values(**insert_vals)
            res = db.execute(stmt)
            db.commit()
            if hasattr(res, "inserted_primary_key") and res.inserted_primary_key:
                self._values[self.__class__._primary_key_name] = res.inserted_primary_key[0]
            self._loaded = True
            self._run_hook("after_create")
        else:
            self._run_hook("before_update")
            stmt = update(table).where(table.c[self.__class__._primary_key_name] == self.id).values(**self._values)
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
            stmt = update(table).where(table.c[self.__class__._primary_key_name] == self.id).values(is_deleted=True)
            db.execute(stmt)
        else:
            stmt = delete(table).where(table.c[self.__class__._primary_key_name] == self.id)
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
