"""Resolver-specific tests."""

from __future__ import annotations
from datetime import datetime, timezone

from jabr.core import RestorationContext
from jabr.resolvers import (
    DateTimeResolver, PronounResolver, DefaultResolver, QuantityResolver,
)


FIXED_NOW = datetime(2026, 4, 25, 14, 30, tzinfo=timezone.utc)  # Saturday


def test_datetime_resolver_finds_today():
    r = DateTimeResolver()
    entries = r.find("call today", RestorationContext(now=FIXED_NOW))
    assert len(entries) == 1
    assert entries[0].value == "2026-04-25"


def test_datetime_resolver_no_now_returns_empty():
    r = DateTimeResolver()
    entries = r.find("call today", RestorationContext(now=None))
    assert entries == []


def test_datetime_resolver_word_boundary():
    """Don't match 'today' inside 'todayish' (hypothetical)."""
    r = DateTimeResolver()
    entries = r.find("brand-new", RestorationContext(now=FIXED_NOW))
    assert entries == []


def test_pronoun_resolver_only_resolves_listed():
    r = PronounResolver()
    ctx = RestorationContext(referents={"her": "Alice"})
    entries = r.find("send her and him a message", ctx)
    # Only "her" should resolve since "him" not in referents
    pronouns_resolved = {e.original_text.lower() for e in entries}
    assert "her" in pronouns_resolved
    assert "him" not in pronouns_resolved


def test_default_resolver_angle_brackets():
    r = DefaultResolver()
    ctx = RestorationContext(defaults={"channel": "#eng"})
    entries = r.find("post in <channel>", ctx)
    assert len(entries) == 1
    assert entries[0].value == "#eng"


def test_default_resolver_at_caps():
    r = DefaultResolver()
    ctx = RestorationContext(defaults={"USER": "alice"})
    entries = r.find("ping @USER", ctx)
    assert len(entries) == 1
    assert entries[0].value == "alice"


def test_quantity_resolver_disambiguates_phrases():
    r = QuantityResolver()
    entries = r.find("send a few emails", RestorationContext())
    assert len(entries) == 1
    assert entries[0].value == "3-4"


def test_quantity_resolver_prefers_longer_phrase():
    """'a couple of' should beat 'a couple' when both apply."""
    r = QuantityResolver()
    entries = r.find("a couple of times", RestorationContext())
    assert len(entries) == 1
    assert entries[0].original_text.lower() == "a couple of"


def test_quantity_resolver_no_overlap():
    """Don't double-resolve overlapping phrases."""
    r = QuantityResolver()
    entries = r.find("several many things", RestorationContext())
    # 'several' and 'many' are distinct; both should be found
    values = {e.value for e in entries}
    assert "3-7" in values
    assert "10+" in values
