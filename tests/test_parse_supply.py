import pytest

from scraper import parse_supply


def test_parse_supply_basic():
    html = '''<div class="info">
    <dt class="col-6">Available items</dt>
    <dd class="col-6">42</dd>
    </div>'''
    assert parse_supply(html) == 42


def test_parse_supply_not_found_returns_none():
    html = '<div>nothing here</div>'
    assert parse_supply(html) is None
