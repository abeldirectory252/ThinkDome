"""Regression coverage for authentication registration validation."""

from thinkdome.security.auth.service import AuthService


class _DatabaseStub:
    def fetch_one(self, *_args):
        return None

    def execute(self, *_args):
        return None

    def log_audit(self, **_kwargs):
        return None


def test_register_validates_username_without_local_regex_shadowing():
    service = object.__new__(AuthService)
    service.db_service = _DatabaseStub()

    assert service.register("valid_user", "a-secure-password") is True
    assert service.register("x", "a-secure-password") is False
