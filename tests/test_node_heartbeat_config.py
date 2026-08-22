from thinkdome.core.config import Settings


def test_control_plane_internal_url_is_explicitly_configurable():
    assert Settings(CONTROL_PLANE_INTERNAL_URL="https://control.internal:8443").CONTROL_PLANE_INTERNAL_URL.startswith("https://")
