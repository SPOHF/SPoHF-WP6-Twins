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
import pickle
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wp6_data.shared.blob import BlobStore

# Enough hex to make a collision irrelevant while staying readable in a log line
# and on a status page.
FINGERPRINT_LENGTH = 16


async def write_pickled(store: BlobStore, key: str, payload: dict) -> None:
    """Store ``payload`` as a pickled artifact at ``key``.

    The store's write is atomic, so a reader sees either the previous artifact or
    this one — never a torn pickle. That is stronger than the ``open(path, 'wb')``
    this replaced, where a pod killed mid-write left a truncated file that only
    :func:`read_pickled`'s broad ``except`` made survivable.
    """
    await store.put(key, pickle.dumps(payload), content_type="application/octet-stream")


async def read_pickled(
    store: BlobStore,
    key: str,
    *,
    version: int | None = None,
    expect_fingerprint: str | None = None,
) -> dict | None:
    """The pickled artifact at ``key``, or ``None`` when it cannot be used.

    Three gates, each answering a different way an artifact goes stale, and all
    three degrade to the same "no usable artifact" that every caller already
    handles — because that is what they got when the file was simply absent.

    **Readability.** Pickle stores classes by module path, so moving or renaming
    one makes every older artifact unreadable: the load fails before the version
    inside it can be consulted. Deliberately broad, because anything a pickle
    from another era can raise — a moved class, a removed attribute, a different
    library version — means the same thing to a caller that can refit.

    **Version**, for a deliberate break: the shape is fine but the numbers mean
    something different now.

    **Fingerprint**, for the change nobody declares: a widened training window, a
    new horizon, a swapped sensor. The layout is untouched, so the version gate
    waves it through, and what has moved is the question the model was fitted to
    answer.

    An unreachable store is *not* swallowed here. Absence and outage are
    different things, and only the caller knows whether it is on a path that can
    degrade (a status page) or one that should fail loudly (a deliberate refit).
    """
    raw = await store.try_get(key)
    if raw is None:
        return None
    try:
        data = pickle.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if version is not None and data.get("version", 0) != version:
        return None
    if expect_fingerprint is not None and data.get("fingerprint") != expect_fingerprint:
        return None
    return data


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
