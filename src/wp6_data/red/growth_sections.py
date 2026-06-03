"""Growth-section config for the red prescriptive view.

Red-only: maps wire **heights** to named canopy **growth sections** (see
`CONTEXT.md` "Growth section" and red ADR 0002), in fixed top-to-bottom order,
identical for every wire. Kept out of ``shared/`` so the twin-agnostic metadata
model never carries red domain language — the shared ``MetadataRegistry`` simply
ignores the ``growth_sections`` key, and this module reads it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class GrowthSection(BaseModel):
    """One canopy zone, bound to a wire height."""

    height: int
    label: str


def load_growth_sections(yaml_path: Path) -> list[GrowthSection]:
    """Ordered top→root growth sections from a twin metadata YAML.

    Reads the red-only top-level ``growth_sections`` list; display order is the
    declared list order (H1 top → H5 root). Returns ``[]`` when the file or key
    is absent.
    """
    if not yaml_path.exists():
        return []
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    return [GrowthSection(**entry) for entry in raw.get("growth_sections", [])]
