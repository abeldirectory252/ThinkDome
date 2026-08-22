import pytest

from thinkdome.control_plane.node_server import create_node_app
from thinkdome.core.config import Settings


def test_node_server_requires_a_secret_key():
    with pytest.raises(RuntimeError, match="NODE_AUTH_KEY_HEX"):
        create_node_app(Settings(NODE_AUTH_KEY_HEX=None))


def test_production_node_requires_mutual_tls_configuration():
    settings = Settings(
        NODE_AUTH_KEY_HEX="aa" * 32,
        NODE_REQUIRE_MTLS=True,
        NODE_TLS_CERTFILE=None,
        NODE_TLS_KEYFILE=None,
        NODE_TLS_CAFILE=None,
    )
    with pytest.raises(RuntimeError, match="NODE_TLS_CERTFILE"):
        settings.node_tls_config()


def test_development_node_can_disable_tls_for_local_testing():
    settings = Settings(NODE_REQUIRE_MTLS=False)
    assert settings.node_tls_config() == {}
