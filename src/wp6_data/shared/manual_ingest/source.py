"""The ``ManualSource`` descriptor — the single per-source seam.

Onboarding a new manual source is "write a parser/decoder + fill in one of
these + wire it into a twin". Everything else (storage, transactional apply,
audit, prune, preview UI, history page, CLI, home-page freshness) is shared
and parameterised by this descriptor alone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from wp6_data.shared.manual_ingest.types import Reading, ValidationReport


@dataclass(frozen=True)
class ManualSource:
    """Everything source-specific about one manual-upload source.

    ``slug`` vs ``categorical_value``: the slug is the storage directory, the
    URL segment, and the ``manual_uploads.source`` audit value. The
    categorical_value is what lands in the readings ``source`` column. They
    are usually equal; they are kept distinct so the audit identity and the
    readings categorical taxonomy can diverge without code changes.
    """

    slug: str
    categorical_value: str
    display_name: str  # human label in card title / page copy
    file_suffix: str  # e.g. ".xlsx" / ".csv" — stored filename + page copy
    accept: str  # the upload <input accept="..."> value
    row_noun: str  # e.g. "Excel rows" / "CSV rows" in the preview
    upload_hint: str  # the card's "Upload a … file" sentence
    parse: Callable[[bytes], list[Reading]]
    validate: Callable[[bytes], ValidationReport]
    parse_error: type[Exception]  # subclass of ManualParseError
