"""Fingerprinting a trained model, so a stale one is refused rather than served.

A pickled model is only valid for the code and the configuration that produced
it. While models lived on ephemeral storage that was self-enforcing: every pod
restart refitted, so an artifact could not outlive the deploy that wrote it.
Persisting them removes that accident, and what it removes has to be replaced
deliberately.

A hand-maintained version constant is the usual answer and it is not enough on
its own, because it only catches the changes somebody remembered to declare.
The two that bite are the ones nobody thinks to declare:

- **A configuration change.** Widen a training window, add a horizon, add an
  exclusion — none of that touches the pickle's layout, so a version gate waves
  it through and the model keeps serving the window it was fitted on, with no
  signal anywhere that it is answering an older question.
- **A quiet code change.** Add a feature to the fit, rename a field, change what
  a column means. The pickle still loads; the numbers are now wrong.

So the fingerprint is computed *from* the things that must match — the config
that shaped the fit and the feature contract the code expects — rather than
from a number someone maintains. It is stored beside the model and checked on
load. A mismatch means "no usable artifact", which every caller already handles,
because that is the same answer they got when the file was simply absent.

The explicit version constant stays alongside it, for the deliberate break that
no fingerprint would notice: a change in what the *numbers mean* when the shape
of everything is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Enough hex to make a collision irrelevant while staying readable in a log line
# and on a status page.
FINGERPRINT_LENGTH = 16


def fingerprint(payload: Any) -> str:
    """A stable short hash of nested primitives.

    Stable across processes and releases, which ``hash()`` is not: Python
    randomises string hashing per interpreter, so a fingerprint built on it
    would differ every restart and refit the model every time.

    Ordering is normalised — dict keys sorted, and ``set``/``frozenset``
    rendered as sorted lists — so a payload that means the same thing hashes the
    same. Sequence order is *kept*, because for a feature list it is meaningful:
    the same names in a different order is a different contract (see
    ``red.climate.model.predict_target``, which refuses exactly that).
    """
    encoded = json.dumps(
        _normalise(payload), sort_keys=True, separators=(",", ":"), default=str
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return digest[:FINGERPRINT_LENGTH]


def _normalise(value: Any) -> Any:
    """Render sets deterministically and recurse; leave everything else to json."""
    if isinstance(value, set | frozenset):
        return sorted(_normalise(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    return value
