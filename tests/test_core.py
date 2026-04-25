"""Core tests for restore() and unrestore()."""

from __future__ import annotations
from datetime import datetime, timezone

import pytest

from jabr.core import (
    restore, unrestore, RestorationContext, RestorationError,
    RestorationTrace,
)


FIXED_NOW = datetime(2026, 4, 25, 14, 30, tzinfo=timezone.utc)


def ctx(**overrides):
    return RestorationContext(now=FIXED_NOW, timezone="UTC", **overrides)


# --- Reversibility (the central property) ---------------------------------


def test_roundtrip_simple_date():
    p = "book me a flight for tomorrow"
    r = restore(p, ctx())
    assert r.output != p
    assert "tomorrow" in r.output
    assert "[[jabr:" in r.output
    assert unrestore(r.output, r.trace) == p


def test_roundtrip_no_resolvable_terms():
    """A prompt with nothing to restore round-trips identically."""
    p = "hello world"
    r = restore(p, ctx())
    assert r.output == p
    assert unrestore(r.output, r.trace) == p


def test_roundtrip_multiple_terms():
    p = "remind me tomorrow that yesterday I told her to send a few emails"
    r = restore(
        p,
        ctx(referents={"her": "Alice"}),
    )
    assert unrestore(r.output, r.trace) == p


def test_roundtrip_with_placeholders():
    p = "send a message to <user> in <channel>"
    r = restore(p, ctx(defaults={"user": "alice@example.com",
                                  "channel": "#engineering"}))
    assert "[[jabr:" in r.output
    assert unrestore(r.output, r.trace) == p


# --- Determinism ----------------------------------------------------------


def test_determinism_same_inputs_same_output():
    p = "schedule for tomorrow at 9am"
    c = ctx()
    r1 = restore(p, c)
    r2 = restore(p, c)
    assert r1.output == r2.output
    assert r1.trace.to_json() == r2.trace.to_json()


def test_different_now_yields_different_output():
    p = "ping me tomorrow"
    c1 = RestorationContext(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    c2 = RestorationContext(now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    r1 = restore(p, c1)
    r2 = restore(p, c2)
    assert r1.output != r2.output


# --- Tag invariants -------------------------------------------------------


def test_tags_are_well_formed():
    """Every tag follows [[jabr:<id>:<kind>:<value>]] format."""
    import re
    p = "tomorrow morning"
    r = restore(p, ctx())
    pattern = re.compile(r"\[\[jabr:[0-9a-f]+:[a-z_]+:[^\[\]]+\]\]")
    matches = pattern.findall(r.output)
    assert len(matches) == len(r.trace.entries)


def test_tag_ids_appear_in_trace():
    p = "remind me tomorrow"
    r = restore(p, ctx())
    import re
    pattern = re.compile(r"\[\[jabr:([0-9a-f]+):")
    ids_in_output = set(pattern.findall(r.output))
    ids_in_trace = {e.entry_id for e in r.trace.entries}
    assert ids_in_output == ids_in_trace


# --- Trace integrity ------------------------------------------------------


def test_unrestore_with_correct_trace_succeeds():
    p = "tomorrow at noon"
    r = restore(p, ctx())
    assert unrestore(r.output, r.trace) == p


def test_unrestore_with_wrong_trace_raises():
    p1 = "tomorrow"
    p2 = "next monday"
    r1 = restore(p1, ctx())
    r2 = restore(p2, ctx())
    # Use r1's output with r2's trace — should fail integrity check
    with pytest.raises(RestorationError):
        unrestore(r1.output, r2.trace)


def test_unrestore_without_trace_still_works():
    """The output alone (without trace) is enough to recover the input,
    because tags are self-describing. The trace is for integrity checking."""
    p = "tomorrow morning"
    r = restore(p, ctx())
    assert unrestore(r.output) == p


# --- Trace serialization --------------------------------------------------


def test_trace_json_roundtrip():
    p = "schedule a few meetings tomorrow"
    r = restore(p, ctx())
    j = r.trace.to_json()
    restored_trace = RestorationTrace.from_json(j)
    assert restored_trace == r.trace


# --- Span correctness -----------------------------------------------------


def test_spans_point_to_actual_text():
    p = "remind me tomorrow about yesterday"
    r = restore(p, ctx())
    for entry in r.trace.entries:
        start, end = entry.original_span
        assert p[start:end].lower() == entry.original_text.lower()


# --- Property: tag insertions never modify original characters -----------


def test_original_chars_preserved_in_output():
    """Every character of the input prompt appears in the output, in order,
    interspersed with tags."""
    p = "tomorrow she will send several emails"
    r = restore(p, ctx(referents={"she": "Alice"}))
    # Strip all tags from output; result must equal original
    assert unrestore(r.output) == p


# --- Empty / edge inputs --------------------------------------------------


def test_empty_string():
    r = restore("", ctx())
    assert r.output == ""
    assert r.trace.entries == ()
    assert unrestore(r.output, r.trace) == ""


def test_whitespace_only():
    r = restore("   ", ctx())
    assert r.output == "   "
    assert unrestore(r.output, r.trace) == "   "


# --- Confidence reporting -------------------------------------------------


def test_high_confidence_for_explicit_referents():
    p = "tell her hi"
    r = restore(p, ctx(referents={"her": "Alice"}))
    pronoun_entries = [e for e in r.trace.entries if e.kind == "pronoun"]
    assert len(pronoun_entries) == 1
    assert pronoun_entries[0].confidence == 1.0


def test_lower_confidence_for_vague_quantities():
    p = "send several emails"
    r = restore(p, ctx())
    quantity_entries = [e for e in r.trace.entries if e.kind == "quantity"]
    assert len(quantity_entries) == 1
    assert 0.5 <= quantity_entries[0].confidence < 1.0


# --- Specific resolutions -------------------------------------------------


def test_tomorrow_resolves_to_correct_date():
    p = "tomorrow"
    r = restore(p, ctx())
    e = r.trace.entries[0]
    assert e.value == "2026-04-26"


def test_yesterday_resolves_to_correct_date():
    p = "yesterday"
    r = restore(p, ctx())
    e = r.trace.entries[0]
    assert e.value == "2026-04-24"


def test_next_monday_picks_following_monday():
    """FIXED_NOW = Sat Apr 25, 2026. 'next monday' = Apr 27."""
    p = "next monday"
    r = restore(p, ctx())
    assert any(e.value == "2026-04-27" for e in r.trace.entries)


def test_morning_includes_date_and_time_range():
    p = "this morning"
    r = restore(p, ctx())
    entries = [e for e in r.trace.entries if e.kind == "datetime"]
    assert len(entries) == 1
    assert "2026-04-25" in entries[0].value
    assert "06:00" in entries[0].value
