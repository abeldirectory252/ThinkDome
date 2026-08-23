"""Hosted-site path containment regression tests."""

from pathlib import Path


def test_hosted_filename_resolution_cannot_escape_site_root(tmp_path):
    site_root = (tmp_path / "site").resolve()
    site_root.mkdir()
    outside = (tmp_path / "secret.txt").resolve()
    outside.write_text("secret", encoding="utf-8")

    requested = (site_root / "../../secret.txt").resolve()
    assert site_root not in requested.parents
