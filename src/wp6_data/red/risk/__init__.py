"""Red prescriptive-risk engine (issue 014, red ADR 0002).

Pure, side-effect-free risk evaluation over multi-height wire readings:
per-growth-section metrics (Height DLI, VPD, Fungal wet-hours, Canopy light
deficit) and discrete risk episodes. Driven on demand by the
``wp6-red-eval-risk`` CLI and (later) by the admin Update/Rebuild actions.
"""
