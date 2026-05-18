"""The ``ManualSource`` descriptor — the single per-source seam.

Onboarding a new manual source is "write a parser + fill in one of these +
wire it into a twin". Everything else (storage, transactional apply, audit,
prune, preview UI, history page, CLI, home-page freshness) is shared and
parameterised by this descriptor plus the twin's categorical column name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from wp6_data.shared.manual_ingest.types import Reading, ValidationReport


@dataclass(frozen=True)
class ManualSource:
    """Everything source-specific about one manual-upload source.

    ``slug`` vs ``categorical_value``: the slug is the storage directory, the
    URL segment, and the ``manual_uploads.source`` audit value (always
    twin-agnostic). The categorical_value is what lands in the twin's
    categorical column on ``readings`` (red: ``source``, blue: ``project``).
    They are usually equal; they are kept distinct because the audit slug and
    the readings categorical taxonomy are different concepts (see the
    ``project_blue_project_vs_red_source`` memo).
    """

    slug: str
    categorical_value: str
    display_name: str  # human label in card title / page copy
    file_suffix: str  # ".xlsx" / ".csv" — drives stored filename + page copy
    accept: str  # the upload <input accept="..."> value
    row_noun: str  # "Excel rows" / "CSV rows" in the preview
    upload_hint: str  # the card's "Upload a … file" sentence
    parse: Callable[[bytes], list[Reading]]
    validate: Callable[[bytes], ValidationReport]
    parse_error: type[Exception]  # subclass of ManualParseError
