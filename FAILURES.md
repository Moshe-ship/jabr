# FAILURES.md

> Inspired by Abū Bakr al-Rāzī, who wrote a separate book listing his own
> medical failures. Every project ships with one.

This document tracks **known limitations and incorrect outputs** of the `jabr` library.

---

## Things this library deliberately does NOT do

These are not bugs — they are explicit design choices:

- **No coreference resolution.** Pronoun restoration only fires when an explicit referent map is supplied in `context.referents`. The library does not attempt to infer `she` from prior conversation turns. Silence is the correct behavior.

- **No locale-specific date parsing.** `tomorrow` resolves; `mañana` does not. Locales are stored in context but not yet used by built-in resolvers. Domain users should add a locale-aware resolver.

- **No timezone arithmetic on relative times.** "Tomorrow" resolves to `now + 1 day` in the timezone of `now`. If the user is in another timezone, they should pass the correct `now`.

- **No fuzzy matching.** The DateTimeResolver matches "tomorrow" but not "tmrw" or "tmrw morning". Fuzzy variants would compromise determinism.

- **No spell correction.** Typos go unresolved. Pre-process with a spell-corrector if needed.

---

## Known limitations and gaps

### v0.1.0

- **Hijri/Islamic calendar dates not supported.** Terms like "after Eid", "during Ramadan", "the first of Muharram" are not resolved. A `HijriDateTimeResolver` is the obvious extension but is not yet implemented.

- **Time-of-day ranges are conventional, not user-specific.** "This morning" → 06:00–11:00, regardless of whether the user typically wakes at 5am or 11am. Override by adding a personalized resolver.

- **Quantity resolutions are anglocentric.** "A few" → 3-4 reflects English-language convention. In other linguistic communities the convention may differ.

- **Time-of-day overlap with named days not handled.** "Tomorrow morning" produces two separate restorations (tomorrow → date; this morning → date+time). Combining them into a single canonical "tomorrow morning at 6am-11am" would be a richer resolver.

- **No relative time arithmetic.** "In 3 days", "next week", "two weeks ago" are not handled by the built-in `DateTimeResolver`. A regex-based extension is straightforward.

- **`PronounResolver` overlaps with longer pronoun forms.** "Their" might be matched alongside "the". This is mitigated by word-boundary regex but warrants a careful review for Arabic-pronoun cases.

- **No structured-document handling.** Tags appear inline in the output text. If the prompt is JSON or markdown, tags will appear inside the structure. A future `structure_aware` mode would emit a sidecar trace instead of inline tags.

---

## Errors discovered post-release

*(empty — first release)*

---

## How to report a wrong restoration

If `jabr` produces a restoration you consider incorrect:

1. Open a GitHub issue with the exact prompt, context, and the unwanted output.
2. State what restoration you expected (or that no restoration should have happened).
3. Mark `bug:wrong-restoration` label.

The fix is usually one of:

- A resolver matched too eagerly → tighten the regex
- A resolver matched too narrowly → broaden the regex
- The context was incomplete → document the missing field
- The behavior is by design → close the issue with reference to this file
