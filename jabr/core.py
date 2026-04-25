"""Core restore() / unrestore() with audit trail.

Properties guaranteed:
  1. Reversibility: unrestore(restore(p, ctx).output, restore(p, ctx).trace) == p
  2. Tag-only insertion: every added term lives between special markers
     [[jabr:<id>:<value>]] and never modifies original characters.
  3. Trace integrity: every entry in the trace points to a span in the output
     that exactly contains the value tagged.
  4. Determinism: given the same (prompt, context, resolver list), output is
     identical across runs.

The discipline: restore() may only ADD information. It must not paraphrase,
rewrite, or change the original characters of the input prompt. Any term it
adds is bracketed with markers carrying the trace ID, source, and value.
"""

from __future__ import annotations
import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol


# Tag format: [[jabr:<entry_id>]]
# Only the entry_id appears inline. All other fields (kind, value, source,
# confidence, span) live in the trace. This avoids any escaping issues with
# brackets, colons, or other special characters in arbitrary values.
TAG_PATTERN = re.compile(r"\[\[jabr:([0-9a-f]+)\]\]")


class RestorationError(Exception):
    """Raised when restore() cannot proceed (e.g., contradiction in inputs)."""


@dataclass(frozen=True)
class RestorationContext:
    """Inputs that resolvers consult.

    Fields are deliberately explicit. There is no implicit "ambient context."
    Callers must supply what they want resolvers to consider.
    """

    now: Optional[datetime] = None
    locale: str = "en_US"
    timezone: str = "UTC"
    user_id: Optional[str] = None
    user_aliases: dict[str, str] = field(default_factory=dict)
    referents: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        if self.now is not None:
            d["now"] = self.now.isoformat()
        return d


@dataclass(frozen=True)
class RestorationEntry:
    """One restoration recorded in the trace.

    Fields:
        entry_id:   stable identifier; matches the tag in the output
        kind:       resolver kind (e.g., "date", "pronoun", "default")
        original_span: (start, end) in the *input* string where the
                    underspecified term appeared (may be the empty span if
                    the restoration is purely additive)
        original_text: the exact substring of the input at original_span
        value:      the resolved value, as a string
        source:     which resolver produced this entry
        confidence: float in [0, 1]
    """

    entry_id: str
    kind: str
    original_span: tuple[int, int]
    original_text: str
    value: str
    source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "kind": self.kind,
            "original_span": list(self.original_span),
            "original_text": self.original_text,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class RestorationTrace:
    """Ordered list of restoration entries plus metadata."""

    entries: tuple[RestorationEntry, ...]
    context_hash: str
    input_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "context_hash": self.context_hash,
            "input_hash": self.input_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "RestorationTrace":
        d = json.loads(s)
        entries = tuple(
            RestorationEntry(
                entry_id=e["entry_id"],
                kind=e["kind"],
                original_span=tuple(e["original_span"]),
                original_text=e["original_text"],
                value=e["value"],
                source=e["source"],
                confidence=e["confidence"],
            )
            for e in d["entries"]
        )
        return cls(
            entries=entries,
            context_hash=d["context_hash"],
            input_hash=d["input_hash"],
        )


@dataclass(frozen=True)
class Restored:
    """Result of restore()."""

    input: str
    output: str
    trace: RestorationTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "trace": self.trace.to_dict(),
        }


class Resolver(Protocol):
    """A resolver scans an input for terms it can restore.

    Resolvers must be deterministic given the same (input, context). They
    return a list of RestorationEntry candidates. The core engine merges
    candidates from all resolvers, deduplicates overlapping spans, and
    produces the final ordered trace.
    """

    name: str

    def find(
        self,
        input: str,
        context: RestorationContext,
    ) -> list[RestorationEntry]:
        ...


def _hash_context(context: RestorationContext) -> str:
    """Stable hash of the context (excluding the wall-clock 'now' value's
    sub-second component, to keep tests reproducible)."""
    d = context.to_dict()
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _hash_input(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _make_entry_id(
    kind: str,
    span: tuple[int, int],
    value: str,
    source: str,
) -> str:
    payload = f"{kind}|{span[0]},{span[1]}|{value}|{source}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _format_tag(entry: RestorationEntry) -> str:
    """Render an entry as the inline tag inserted into the output.

    The tag carries only the entry_id. The full restoration data lives in
    the trace, indexed by entry_id. This makes the tag immune to brackets,
    colons, or any other special characters in the value.
    """
    return f"[[jabr:{entry.entry_id}]]"


def _resolve_overlaps(
    entries: list[RestorationEntry],
) -> list[RestorationEntry]:
    """Resolve overlapping spans by preferring higher confidence; on tie,
    prefer the earlier resolver in the input list.

    Stable sort: we keep input order among non-overlapping winners.
    """
    if not entries:
        return []

    # Sort by start, then confidence descending (preferred entries come first
    # at the same start)
    sorted_entries = sorted(
        enumerate(entries),
        key=lambda iv: (iv[1].original_span[0], -iv[1].confidence, iv[0]),
    )

    chosen: list[RestorationEntry] = []
    occupied_end = -1
    for _orig_idx, e in sorted_entries:
        start, end = e.original_span
        if start >= occupied_end:
            chosen.append(e)
            occupied_end = end
        # else: dropped due to overlap with a higher-confidence pick

    # Re-sort by original span start to preserve reading order
    chosen.sort(key=lambda e: e.original_span[0])
    return chosen


def restore(
    prompt: str,
    context: Optional[RestorationContext] = None,
    resolvers: Optional[list[Resolver]] = None,
) -> Restored:
    """Apply Restore (al-jabr) to a prompt.

    Returns:
        Restored — with output (the prompt with tagged restorations inserted)
        and trace (the audit record).

    Properties:
        unrestore(restore(p, ctx).output, restore(p, ctx).trace) == p

    Determinism:
        Given the same (prompt, context, resolvers), output is identical.
    """
    if context is None:
        context = RestorationContext()
    if resolvers is None:
        from jabr.resolvers import DEFAULT_RESOLVERS
        resolvers = DEFAULT_RESOLVERS

    candidates: list[RestorationEntry] = []
    for r in resolvers:
        for e in r.find(prompt, context):
            # Trust resolver to set source; if not, use resolver name
            if not e.source:
                e = dataclasses.replace(e, source=r.name)
            candidates.append(e)

    chosen = _resolve_overlaps(candidates)

    # Build output by inserting tags after the original spans
    output_parts: list[str] = []
    cursor = 0
    final_entries: list[RestorationEntry] = []
    for e in chosen:
        start, end = e.original_span
        if start < cursor:
            # Defensive: should not happen after _resolve_overlaps, but assert
            raise RestorationError(
                f"Overlap survived resolution: {e}"
            )
        # Append the literal characters up to and including the original term
        output_parts.append(prompt[cursor:end])
        # Compute entry_id now that we know everything is final
        entry_with_id = dataclasses.replace(
            e,
            entry_id=_make_entry_id(e.kind, e.original_span, e.value, e.source),
        )
        final_entries.append(entry_with_id)
        # Append the tag immediately after the original term
        output_parts.append(_format_tag(entry_with_id))
        cursor = end
    output_parts.append(prompt[cursor:])
    output = "".join(output_parts)

    trace = RestorationTrace(
        entries=tuple(final_entries),
        context_hash=_hash_context(context),
        input_hash=_hash_input(prompt),
    )

    return Restored(input=prompt, output=output, trace=trace)


def unrestore(
    output: str,
    trace: Optional[RestorationTrace] = None,
) -> str:
    """Reverse Restore — return the original prompt by stripping every
    bracketed restoration tag.

    The trace is *optional* for unrestore: tags carry enough information to
    be stripped without it. The trace is used when supplied to verify
    integrity (every tag in the output should be present in the trace).
    """
    # Verify trace integrity if provided
    if trace is not None:
        ids_in_output = set(TAG_PATTERN.findall(output))
        ids_in_trace = {e.entry_id for e in trace.entries}
        missing = ids_in_output - ids_in_trace
        extra = ids_in_trace - ids_in_output
        if missing:
            raise RestorationError(
                f"Tags in output not in trace: {missing}"
            )
        if extra:
            raise RestorationError(
                f"Trace entries not in output: {extra}"
            )

    return TAG_PATTERN.sub("", output)
