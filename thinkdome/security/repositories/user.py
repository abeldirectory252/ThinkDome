"""User & Profile Repository layer using ThinkDome ORM."""

from __future__ import annotations

from typing import Optional, List
from thinkdome.security.repositories.base import BaseRepository
from thinkdome.security.rbac.models import User, UserProfile


class UserRepository(BaseRepository[User]):
    """Repository handling database operations for User and UserProfile entities."""

    def __init__(self) -> None:
        super().__init__(User)

    def get_by_username(self, username: str) -> Optional[User]:
        """Find active user record by username."""
        return self.find_one_by(username=username)

    def find_by_username(self, username: str) -> Optional[User]:
        """Find active user record by username (alias)."""
        return self.get_by_username(username)

    def get_by_email(self, email: str) -> Optional[User]:
        """Find active user record by email."""
        return self.find_one_by(email=email)

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Fetch UserProfile entity associated with user_id."""
        return UserProfile.query().filter(user_id=user_id).first()

    def create_profile(self, profile: UserProfile) -> UserProfile:
        """Persist a new UserProfile entity."""
        profile.save()
        return profile

    def update_status(self, user_id: str, status: str) -> Optional[User]:
        """Update user account status flag."""
        user = self.get_by_id(user_id)
        if user:
            user._values["status"] = status
            user.save()
        return user
