# jabr (الجبر) — Reversible Prompt-Context Restoration

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Tests: 31 passing](https://img.shields.io/badge/tests-31%20passing-green.svg)]()

Reversible. Audited. Deterministic. The Restore operation as a standalone primitive for AI agent pipelines.

---

## What it does

Takes an under-specified prompt and a context, returns the prompt with implicit terms made explicit, plus a full audit trail. The original prompt is **always recoverable** from the output.

```python
from datetime import datetime, timezone
from jabr import restore, unrestore, RestorationContext

ctx = RestorationContext(
    now=datetime(2026, 4, 25, 14, 30, tzinfo=timezone.utc),
    referents={"her": "Alice"},
    defaults={"channel": "#engineering"},
)

result = restore("tell her tomorrow to post in <channel>", ctx)

print(result.output)
# tell her[[jabr:abc123:pronoun:Alice]] tomorrow[[jabr:def456:date:2026-04-26]]
# to post in <channel>[[jabr:ghi789:default:#engineering]]

# Reversible
assert unrestore(result.output, result.trace) == "tell her tomorrow to post in <channel>"
```

## Design properties

The library guarantees four properties:

1. **Reversibility.** `unrestore(restore(p, ctx).output, trace) == p` for any `(p, ctx)`. Verified by 31 tests including round-trip property tests.

2. **Tag-only insertion.** Every added term is bracketed with `[[jabr:<id>:<kind>:<value>]]`. Original characters are never modified, only interspersed with tags.

3. **Trace integrity.** Every tag in the output has a corresponding entry in the trace. `unrestore()` with a wrong trace raises `RestorationError`.

4. **Determinism.** Given the same `(prompt, context, resolvers)`, the output is byte-identical across runs.

## Why this matters

In modern LLM agent pipelines, prompts are routinely rewritten, summarized, and "expanded" silently. The original cannot be recovered. Debugging is dream interpretation.

`jabr` makes that explicit. Every restoration is tagged, every tag is in the trace, every trace entry has provenance (source, confidence, original span). When the agent does something unexpected, you can replay the input through the same restoration and see exactly what was added.

## Built-in resolvers

| Resolver | What it handles | Confidence |
|---|---|---|
| `DateTimeResolver` | today, tomorrow, yesterday, this morning/afternoon/evening, next/last <weekday>, now | 0.85–1.0 |
| `PronounResolver` | he/she/it/they/etc., resolved against explicit `context.referents` | 1.0 |
| `DefaultResolver` | `<placeholder>` and `@PLACEHOLDER` resolved against `context.defaults` | 1.0 |
| `QuantityResolver` | a few, several, many, a couple, lots of → numeric ranges | 0.5–0.85 |

Add your own resolver by implementing the `Resolver` Protocol:

```python
from jabr import Resolver, RestorationEntry, RestorationContext

class MyResolver:
    name = "my_domain"
    def find(self, input: str, context: RestorationContext) -> list[RestorationEntry]:
        ...
```

## CLI

```bash
# Restore
jabr restore --prompt "tell her tomorrow" --context ctx.json

# Restore with system clock
jabr restore --prompt "ping me tomorrow" --now system

# Round-trip verify
jabr roundtrip --prompt "tomorrow morning" --now system

# Unrestore (recover original from output)
jabr unrestore --output "[output with tags]"
```

Where `ctx.json` looks like:

```json
{
  "now": "2026-04-25T14:30:00+00:00",
  "timezone": "UTC",
  "referents": {"her": "Alice"},
  "defaults": {"channel": "#engineering"}
}
```

## Install

```bash
pip install -e .
```

## Tests

```bash
pytest tests/ -v
```

31/31 pass on Python 3.10+. No runtime dependencies.

## What it is not

- Not an LLM-powered prompt rewriter. There is no model in `jabr`. All resolvers are deterministic regex/dict-based functions.
- Not a coreference-resolution library. Pronoun restoration only happens when an explicit referent map is supplied. There is no inference from prior conversation.
- Not a guesser. If a term cannot be resolved (e.g., "tomorrow" without a `now`), `jabr` does nothing. Silence is the correct behavior on missing context.

## Structure

```
jabr/
├── jabr/
│   ├── __init__.py       Public API
│   ├── core.py           restore() + unrestore() + dataclasses
│   ├── resolvers.py      4 built-in resolvers
│   └── cli.py            command-line interface
├── tests/
│   ├── test_core.py      core property tests
│   └── test_resolvers.py resolver-specific tests
├── pyproject.toml
├── README.md
├── LICENSE
└── FAILURES.md
```

## Failure modes

See `FAILURES.md` for the honest list of what this library does *not* handle.

## License

MIT.
