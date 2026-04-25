"""Hypothesis-based property tests for jabr.

These tests exercise restore/unrestore on randomly-generated inputs to
verify reversibility for a much broader set of (prompt, context) than the
hand-curated examples in test_core.py.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from string import printable, ascii_letters

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from jabr.core import (
    restore, unrestore, RestorationContext, RestorationError,
)


# Strategy: arbitrary printable Unicode strings, including bracket characters,
# colons, backslashes, and other adversarial content. We deliberately
# allow strings that contain literal "[[jabr:" sequences to verify that
# restore/unrestore handle pre-existing tag-shaped content gracefully.
ADVERSARIAL_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Zs"),
        whitelist_characters="[]\\:_-+={},.<>!@#$%^&*()|/?\"'`~",
    ),
    min_size=0,
    max_size=200,
)


# Strategy: realistic-looking prompts that may or may not contain restorable
# terms. We mix arbitrary strings with seeded restoration triggers to
# exercise both paths.
RESTORATION_TRIGGERS = st.sampled_from([
    "tomorrow", "yesterday", "today", "tonight",
    "this morning", "this afternoon", "this evening",
    "right now", "now",
    "next monday", "last friday",
    "a few", "several", "many",
])


@st.composite
def realistic_prompts(draw):
    """A prompt that's a mix of arbitrary text and restoration triggers."""
    parts = draw(st.lists(
        st.one_of(ADVERSARIAL_TEXT, RESTORATION_TRIGGERS),
        min_size=0, max_size=10,
    ))
    return " ".join(parts)


@st.composite
def restoration_contexts(draw):
    """Random RestorationContext."""
    has_now = draw(st.booleans())
    now = None
    if has_now:
        # Random datetime within +/- 1000 days of a fixed reference
        offset = draw(st.integers(min_value=-1000, max_value=1000))
        now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
    referents = draw(st.dictionaries(
        keys=st.sampled_from(["he", "she", "it", "they", "him", "her", "them"]),
        values=st.text(alphabet=ascii_letters, min_size=1, max_size=20),
        max_size=4,
    ))
    defaults = draw(st.dictionaries(
        keys=st.text(alphabet=ascii_letters, min_size=1, max_size=10),
        values=st.text(alphabet=ascii_letters + "#@", min_size=1, max_size=20),
        max_size=4,
    ))
    return RestorationContext(
        now=now,
        timezone="UTC",
        referents=referents,
        defaults=defaults,
    )


# --- The central reversibility property ----------------------------------


@given(prompt=ADVERSARIAL_TEXT, context=restoration_contexts())
@settings(max_examples=500, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_reversibility_arbitrary_text(prompt, context):
    """For arbitrary printable Unicode prompts and arbitrary contexts,
    unrestore(restore(p).output, trace) == p."""
    result = restore(prompt, context)
    recovered = unrestore(result.output, result.trace)
    assert recovered == prompt, (
        f"Reversibility failed for prompt={prompt!r}\n"
        f"  output={result.output!r}\n"
        f"  recovered={recovered!r}"
    )


@given(prompt=realistic_prompts(), context=restoration_contexts())
@settings(max_examples=500, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_reversibility_realistic_prompts(prompt, context):
    """For realistic prompts (mix of arbitrary text + restoration triggers),
    reversibility holds."""
    result = restore(prompt, context)
    assert unrestore(result.output, result.trace) == prompt


# --- Adversarial: input contains tag-shaped substrings -------------------


@given(prompt=st.text(alphabet=printable, min_size=0, max_size=200))
@settings(max_examples=200, deadline=None)
def test_reversibility_with_tag_shaped_input(prompt):
    """If the input itself contains '[[jabr:...' sequences, reversibility
    must still hold. The input characters are never modified; tags only
    exist for restoration entries we added."""
    ctx = RestorationContext(
        now=datetime(2026, 4, 25, tzinfo=timezone.utc),
        timezone="UTC",
    )
    result = restore(prompt, ctx)
    assert unrestore(result.output, result.trace) == prompt


# --- Determinism property ------------------------------------------------


@given(prompt=realistic_prompts(), context=restoration_contexts())
@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_determinism(prompt, context):
    """Same (prompt, context) → byte-identical output and trace."""
    r1 = restore(prompt, context)
    r2 = restore(prompt, context)
    assert r1.output == r2.output
    assert r1.trace.to_json() == r2.trace.to_json()


# --- Tag-only-insertion property -----------------------------------------


@given(prompt=ADVERSARIAL_TEXT, context=restoration_contexts())
@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_original_chars_recoverable(prompt, context):
    """Stripping all jabr tags from the output produces the original input."""
    import re
    result = restore(prompt, context)
    stripped = re.sub(r"\[\[jabr:[0-9a-f]+\]\]", "", result.output)
    assert stripped == prompt


# --- Trace mismatch raises -----------------------------------------------


@given(p1=realistic_prompts(), p2=realistic_prompts(), context=restoration_contexts())
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_trace_mismatch_raises(p1, p2, context):
    """If r1's trace has entries that don't appear in r2's output (or vice
    versa), unrestore must raise."""
    if p1 == p2:
        return  # Skip when prompts are identical
    r1 = restore(p1, context)
    r2 = restore(p2, context)
    ids1 = {e.entry_id for e in r1.trace.entries}
    ids2 = {e.entry_id for e in r2.trace.entries}
    if ids1 == ids2:
        return  # Skip when by chance the entry sets match
    # If we cross r1's output with r2's trace, integrity check should fail
    with pytest.raises(RestorationError):
        unrestore(r1.output, r2.trace)
