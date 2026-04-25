"""Built-in resolvers for restore().

Each resolver is deterministic: same (input, context) → same output. Each
returns RestorationEntry objects with explicit confidence and source.

Adding a resolver: implement `find(input, context) -> list[RestorationEntry]`,
set `name`, and append to your resolver list. There is no global registry —
callers control which resolvers run.
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import Optional

from jabr.core import RestorationEntry, RestorationContext


def _make_entry(
    kind: str,
    span: tuple[int, int],
    original: str,
    value: str,
    source: str,
    confidence: float,
) -> RestorationEntry:
    # entry_id is computed at restore() time once overlaps are resolved.
    # Use a placeholder here; core.restore() rewrites it.
    return RestorationEntry(
        entry_id="",
        kind=kind,
        original_span=span,
        original_text=original,
        value=value,
        source=source,
        confidence=confidence,
    )


# --------------------------------------------------------------------------- #
# DateTimeResolver
# --------------------------------------------------------------------------- #


class DateTimeResolver:
    """Resolves relative date/time references (today, tomorrow, yesterday,
    now, this morning, etc.) when context.now is set.

    Supported terms (case-insensitive, word-bounded):
        today, tomorrow, yesterday
        this morning, this afternoon, this evening, tonight
        now, right now
        next monday..sunday
        last monday..sunday

    Confidence is 1.0 for unambiguous references (today, tomorrow, etc.);
    0.85 for time-of-day terms with conventional resolution; 0.95 for named
    weekdays.
    """

    name = "datetime"

    _DAYS = (
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    )

    _SIMPLE = {
        "today":     ("date",     0,  1.0),
        "tomorrow":  ("date",     1,  1.0),
        "yesterday": ("date",    -1,  1.0),
        "tonight":   ("datetime", 0,  0.85),  # special-cased below
    }

    _TIMES_OF_DAY = {
        "this morning":   ("morning",   "06:00–11:00", 0.85),
        "this afternoon": ("afternoon", "12:00–17:00", 0.85),
        "this evening":   ("evening",   "17:00–21:00", 0.85),
    }

    def find(
        self,
        input: str,
        context: RestorationContext,
    ) -> list[RestorationEntry]:
        if context.now is None:
            return []
        out: list[RestorationEntry] = []
        lowered = input.lower()

        # Simple single-word date references
        for word, (kind, offset, conf) in self._SIMPLE.items():
            for m in re.finditer(r"\b" + re.escape(word) + r"\b", lowered):
                target = context.now + timedelta(days=offset)
                if word == "tonight":
                    value = f"{target.date().isoformat()} 21:00–24:00 {context.timezone}"
                else:
                    value = target.date().isoformat()
                out.append(_make_entry(
                    kind=kind,
                    span=(m.start(), m.end()),
                    original=input[m.start():m.end()],
                    value=value,
                    source=self.name,
                    confidence=conf,
                ))

        # Time-of-day phrases
        for phrase, (label, range_str, conf) in self._TIMES_OF_DAY.items():
            for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", lowered):
                today = context.now.date().isoformat()
                value = f"{today} {range_str} {context.timezone}"
                out.append(_make_entry(
                    kind="datetime",
                    span=(m.start(), m.end()),
                    original=input[m.start():m.end()],
                    value=value,
                    source=self.name,
                    confidence=conf,
                ))

        # Named weekdays (next / last)
        for day_idx, day in enumerate(self._DAYS):
            for direction, qualifier in (("next", +1), ("last", -1)):
                pattern = r"\b" + re.escape(direction) + r"\s+" + re.escape(day) + r"\b"
                for m in re.finditer(pattern, lowered):
                    target = self._next_or_last_weekday(
                        context.now, day_idx, qualifier
                    )
                    out.append(_make_entry(
                        kind="date",
                        span=(m.start(), m.end()),
                        original=input[m.start():m.end()],
                        value=target.date().isoformat(),
                        source=self.name,
                        confidence=0.95,
                    ))

        # "now" / "right now"
        for phrase in ("right now", "now"):
            for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", lowered):
                # Avoid double-tagging "right now" + "now"
                if phrase == "now" and any(
                    e.original_span[0] <= m.start() < e.original_span[1]
                    for e in out
                ):
                    continue
                out.append(_make_entry(
                    kind="datetime",
                    span=(m.start(), m.end()),
                    original=input[m.start():m.end()],
                    value=context.now.isoformat(),
                    source=self.name,
                    confidence=1.0,
                ))

        return out

    @staticmethod
    def _next_or_last_weekday(
        now: datetime, target_day_idx: int, direction: int
    ) -> datetime:
        """Return the datetime of the next (direction=+1) or last (-1)
        occurrence of weekday target_day_idx (0=Monday, 6=Sunday) relative
        to now."""
        current_day_idx = now.weekday()
        if direction == +1:
            delta = (target_day_idx - current_day_idx) % 7
            if delta == 0:
                delta = 7
        else:
            delta = -((current_day_idx - target_day_idx) % 7)
            if delta == 0:
                delta = -7
        return now + timedelta(days=delta)


# --------------------------------------------------------------------------- #
# PronounResolver
# --------------------------------------------------------------------------- #


class PronounResolver:
    """Resolves pronouns/aliases against a referent dictionary in context.

    Only resolves pronouns that have an explicit entry in
    context.referents. We do NOT guess from prior turns or do coreference;
    that would violate determinism. Callers populate referents.
    """

    name = "pronoun"

    _PRONOUNS = ("he", "she", "it", "they", "him", "her", "them", "his", "hers", "their", "its")

    def find(
        self,
        input: str,
        context: RestorationContext,
    ) -> list[RestorationEntry]:
        if not context.referents:
            return []
        out: list[RestorationEntry] = []
        lowered = input.lower()
        for pronoun in self._PRONOUNS:
            if pronoun not in context.referents:
                continue
            referent = context.referents[pronoun]
            for m in re.finditer(r"\b" + re.escape(pronoun) + r"\b", lowered):
                out.append(_make_entry(
                    kind="pronoun",
                    span=(m.start(), m.end()),
                    original=input[m.start():m.end()],
                    value=referent,
                    source=self.name,
                    confidence=1.0,  # explicit referent map = certain
                ))
        return out


# --------------------------------------------------------------------------- #
# DefaultResolver
# --------------------------------------------------------------------------- #


class DefaultResolver:
    """Inserts named defaults into placeholders like '<channel>' or '@USER'.

    Inputs containing literal placeholder forms are mapped to context.defaults.
    Format: <name> or @NAME.
    """

    name = "default"

    _PLACEHOLDER = re.compile(r"<(\w+)>|@([A-Z_]+)")

    def find(
        self,
        input: str,
        context: RestorationContext,
    ) -> list[RestorationEntry]:
        if not context.defaults:
            return []
        out: list[RestorationEntry] = []
        for m in self._PLACEHOLDER.finditer(input):
            key = m.group(1) or m.group(2)
            if key is None:
                continue
            value = context.defaults.get(key)
            if value is None:
                # Try lowercase (defaults dict might be lowercase keys)
                value = context.defaults.get(key.lower())
            if value is None:
                continue
            out.append(_make_entry(
                kind="default",
                span=(m.start(), m.end()),
                original=input[m.start():m.end()],
                value=value,
                source=self.name,
                confidence=1.0,
            ))
        return out


# --------------------------------------------------------------------------- #
# QuantityResolver
# --------------------------------------------------------------------------- #


class QuantityResolver:
    """Resolves vague quantity terms (a few, several, many, some, a couple)
    to canonical numeric ranges.

    Confidence is moderate (0.6-0.7) because these are conventional, not
    universal. Callers can override via custom resolver if their domain has
    more precise semantics.
    """

    name = "quantity"

    _RANGES = {
        "a couple of":  ("2", 0.85),
        "a couple":     ("2", 0.85),
        "a few":        ("3-4", 0.7),
        "several":      ("3-7", 0.65),
        "some":         ("2-10", 0.55),
        "many":         ("10+", 0.6),
        "lots of":      ("10+", 0.6),
        "a bunch of":   ("5+", 0.6),
        "tons of":      ("many",  0.5),
    }

    def find(
        self,
        input: str,
        context: RestorationContext,
    ) -> list[RestorationEntry]:
        out: list[RestorationEntry] = []
        lowered = input.lower()
        # Sort longer phrases first to avoid "a few" matching "a"
        sorted_phrases = sorted(self._RANGES.items(), key=lambda kv: -len(kv[0]))
        for phrase, (range_str, conf) in sorted_phrases:
            for m in re.finditer(r"\b" + re.escape(phrase) + r"\b", lowered):
                # Avoid double-matching when shorter phrase is a substring of
                # a longer one already chosen
                if any(
                    e.original_span[0] <= m.start() < e.original_span[1] or
                    e.original_span[0] < m.end() <= e.original_span[1]
                    for e in out
                ):
                    continue
                out.append(_make_entry(
                    kind="quantity",
                    span=(m.start(), m.end()),
                    original=input[m.start():m.end()],
                    value=range_str,
                    source=self.name,
                    confidence=conf,
                ))
        return out


# Default ordering: dates, pronouns, defaults, quantities.
# Order matters when overlapping spans exist; earlier-listed wins on ties.
DEFAULT_RESOLVERS = [
    DateTimeResolver(),
    PronounResolver(),
    DefaultResolver(),
    QuantityResolver(),
]
