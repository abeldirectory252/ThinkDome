import os

from thinkdome.core.config import get_site_database_url, get_workspace_root


def test_active_site_database_url_is_authoritative():
    previous = os.environ.get("THINKDOME_SITE")
    os.environ["THINKDOME_SITE"] = "think.local"
    try:
        assert get_site_database_url() == f"sqlite:///{get_workspace_root() / 'sites' / 'think.local' / 'storage' / 'thinkbox.db'}"
    finally:
        if previous is None:
            os.environ.pop("THINKDOME_SITE", None)
        else:
            os.environ["THINKDOME_SITE"] = previous
