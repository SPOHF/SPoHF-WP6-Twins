# Derived risk trendline columns (VPD / Fungal-risk / Height DLI)

**Status:** ready-for-agent

## Design source

Red ADR `src/wp6_data/red/docs/adr/0002-prescriptive-risk-rebuildable-episode-cache.md`
and the **VPD** / **Fungal-risk** / **Height DLI** terms in `src/wp6_data/red/CONTEXT.md`.

## What to build

Add the **derived columns** to the crop-climate table as **threshold-free trendlines**,
computed on read using the issue-014 metric functions over the selected day — no
dependency on the cache table:

- **Height DLI** sparkline (cumulative through the day).
- **VPD** sparkline drawn over a shaded **healthy band** (band from `metadata.yaml`).
- **Fungal-risk (wet-hours)** sparkline.

Per CONTEXT, these are descriptive curves — the grower reads the shape; **no verdict** is
rendered here (the discrete canopy-deficit/active-risk indicator is issue 017). Keep
height coloring consistent with the raw columns where meaningful.

## Acceptance criteria

- [ ] Three derived columns rendered per Growth section: Height DLI, VPD-over-band, Fungal-risk
- [ ] VPD column shows the configured healthy band as a shaded region behind the curve
- [ ] Computed on read from wire data for the selected day; no read of the cache table
- [ ] Coloring consistent with the raw measurement columns
- [ ] Missing data per section handled gracefully

## Deferred / out of scope

Any discrete verdict/judgment (issue 017); light-penetration interpretation of lower-section Height DLI.

## Blocked by

- `issues/013-crop-climate-readonly-table.md`
- `issues/014-risk-engine-cli.md`
