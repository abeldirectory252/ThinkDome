"""Base Generic Repository mapped to ThinkDome custom ORM Model."""

from __future__ import annotations

from typing import Generic, TypeVar, Type, Optional, List, Dict, Any
from thinkdome.core.orm.orm import Model

T = TypeVar("T", bound=Model)


class BaseRepository(Generic[T]):
    """Generic repository providing decoupled data operations using ThinkDome ORM."""

    def __init__(self, model_class: Type[T]) -> None:
        self.model_class = model_class

    def get_by_id(self, entity_id: str) -> Optional[T]:
        """Fetch entity by primary key ID."""
        return self.model_class.get(entity_id)

    def find_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Retrieve all active records with pagination."""
        return self.model_class.query().limit(limit).offset(offset).all()

    def find_by(self, **kwargs) -> List[T]:
        """Filter records matching exact field key-value pairs."""
        return self.model_class.query().filter(**kwargs).all()

    def find_one_by(self, **kwargs) -> Optional[T]:
        """Fetch single record matching filter criteria."""
        return self.model_class.query().filter(**kwargs).first()

    def save(self, entity: T) -> T:
        """Persist or update an entity record."""
        entity.save()
        return entity

    def delete(self, entity_id: str, soft: bool = True) -> bool:
        """Remove entity by ID using soft or hard deletion."""
        entity = self.get_by_id(entity_id)
        if not entity:
            return False
        entity.delete(soft=soft)
        return True
