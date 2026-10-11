"""The isolated staging card must show the entire source photograph."""

from app.paste_link_staging import STAGING_PAGE


def test_vehicle_photograph_uses_contain_not_cover():
    assert ".image img{width:100%;height:100%;object-fit:contain;display:none}" in STAGING_PAGE
    assert "object-fit:cover" not in STAGING_PAGE
