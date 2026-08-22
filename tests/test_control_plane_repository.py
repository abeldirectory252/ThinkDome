"""Repository contract tests; integration setup supplies the active ORM DB."""

from thinkdome.apps.sandbox.models import Organization, Project


def test_control_plane_models_expose_tenant_scoped_fields():
    assert "organization_id" in Organization._fields
    assert "organization_id" in Project._fields
    assert "project_id" in Project._fields
