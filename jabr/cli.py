"""jabr CLI."""

from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Optional

from jabr.core import (
    restore, unrestore, RestorationContext, RestorationTrace,
)


def _load_context(path: Optional[str]) -> RestorationContext:
    if path is None:
        return RestorationContext()
    with open(path) as f:
        d = json.load(f)
    now_str = d.get("now")
    now: Optional[datetime] = None
    if now_str:
        now = datetime.fromisoformat(now_str)
    return RestorationContext(
        now=now,
        locale=d.get("locale", "en_US"),
        timezone=d.get("timezone", "UTC"),
        user_id=d.get("user_id"),
        user_aliases=d.get("user_aliases") or {},
        referents=d.get("referents") or {},
        defaults=d.get("defaults") or {},
    )


def cmd_restore(args: argparse.Namespace) -> int:
    if args.prompt is None:
        prompt = sys.stdin.read()
    else:
        prompt = args.prompt
    ctx = _load_context(args.context)

    if args.now == "system":
        ctx = RestorationContext(
            now=datetime.now(timezone.utc),
            locale=ctx.locale, timezone=ctx.timezone,
            user_id=ctx.user_id, user_aliases=ctx.user_aliases,
            referents=ctx.referents, defaults=ctx.defaults,
        )

    result = restore(prompt, ctx)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0

    print(result.output)
    if args.trace:
        sys.stderr.write("\n--- trace ---\n")
        sys.stderr.write(result.trace.to_json())
        sys.stderr.write("\n")
    return 0


def cmd_unrestore(args: argparse.Namespace) -> int:
    if args.output is None:
        output = sys.stdin.read()
    else:
        output = args.output

    trace: Optional[RestorationTrace] = None
    if args.trace_file:
        with open(args.trace_file) as f:
            trace = RestorationTrace.from_json(f.read())

    original = unrestore(output, trace)
    print(original)
    return 0


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """Verify reversibility by restoring then unrestoring and checking
    equality with the original."""
    if args.prompt is None:
        prompt = sys.stdin.read()
    else:
        prompt = args.prompt
    ctx = _load_context(args.context)
    if args.now == "system":
        ctx = RestorationContext(
            now=datetime.now(timezone.utc),
            locale=ctx.locale, timezone=ctx.timezone,
            user_id=ctx.user_id, user_aliases=ctx.user_aliases,
            referents=ctx.referents, defaults=ctx.defaults,
        )

    result = restore(prompt, ctx)
    recovered = unrestore(result.output, result.trace)
    if recovered == prompt:
        if args.verbose:
            print(f"Roundtrip OK ({len(result.trace.entries)} restorations).")
        return 0
    sys.stderr.write("Roundtrip FAILED.\n")
    sys.stderr.write(f"Input:    {prompt!r}\n")
    sys.stderr.write(f"Output:   {result.output!r}\n")
    sys.stderr.write(f"Recovered:{recovered!r}\n")
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="jabr",
        description="Reversible prompt-context restoration.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("restore", help="Restore an under-specified prompt.")
    pr.add_argument("--prompt", help="Prompt text (or stdin if omitted).")
    pr.add_argument("--context", help="JSON file with RestorationContext fields.")
    pr.add_argument("--now", default=None,
                    help="'system' to use system clock; else inherit from context.")
    pr.add_argument("--trace", action="store_true",
                    help="Emit trace to stderr.")
    pr.add_argument("--json", action="store_true",
                    help="Emit full result (input/output/trace) as JSON.")
    pr.set_defaults(func=cmd_restore)

    pu = sub.add_parser("unrestore",
                        help="Reverse a restored output back to original.")
    pu.add_argument("--output", help="Restored output text (or stdin).")
    pu.add_argument("--trace-file",
                    help="Optional trace JSON file for integrity verification.")
    pu.set_defaults(func=cmd_unrestore)

    pt = sub.add_parser("roundtrip",
                        help="Verify restore→unrestore returns the original.")
    pt.add_argument("--prompt", help="Prompt text (or stdin).")
    pt.add_argument("--context", help="JSON file with RestorationContext fields.")
    pt.add_argument("--now", default=None,
                    help="'system' to use system clock; else inherit from context.")
    pt.add_argument("-v", "--verbose", action="store_true")
    pt.set_defaults(func=cmd_roundtrip)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
