"""jabr — reversible prompt-context restoration.

The Restore operation: take an under-specified prompt and recover the
implicit terms (dates, references, defaults) explicitly, with a full audit
trail. Every term added is tagged. The original prompt is recoverable from
the output by stripping tagged spans.
"""

from jabr.core import (
    restore,
    unrestore,
    Restored,
    RestorationTrace,
    RestorationEntry,
    RestorationContext,
    RestorationError,
    Resolver,
)
from jabr.resolvers import (
    DateTimeResolver,
    PronounResolver,
    DefaultResolver,
    QuantityResolver,
    DEFAULT_RESOLVERS,
)

__version__ = "0.1.0"
__all__ = [
    "restore",
    "unrestore",
    "Restored",
    "RestorationTrace",
    "RestorationEntry",
    "RestorationContext",
    "RestorationError",
    "Resolver",
    "DateTimeResolver",
    "PronounResolver",
    "DefaultResolver",
    "QuantityResolver",
    "DEFAULT_RESOLVERS",
]
