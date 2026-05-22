# Device metadata supports wildcard keys

`MetadataRegistry` enriches devices from a hand-maintained per-twin YAML, but
the `long_data` source mints ~1000 data-driven devices (one per treatment×plant)
that cannot be hand-listed. Rather than generating the YAML or deriving labels
in code, device keys may be **glob patterns** (e.g. `"Org1 / plant *"` →
`position: Org1`): the registry resolves a device by exact match first, then by
the **most specific** (longest) matching pattern. One pattern per treatment
enriches every plant device in that plot — including future years — with zero
per-device edits, keeping the YAML the small hand-written SSOT.

## Considered Options

- **Generate the devices block** (~1000 entries) — rejected: turns the YAML
  into a noisy generated artifact and conflicts with hand-maintained SSOT.
- **Derive position from device_name in code** — rejected: pushes a labelling
  rule into code, away from the metadata that owns labels.

## Consequences

The feature is generic (lives in shared `MetadataRegistry`), so it is available
to every twin, not just blue. `long_data` device names are deliberately
pattern-friendly (`"{treatment} / plant {nr}"`) so one `"{treatment} / plant *"`
key per treatment suffices, and reuse the automated sensors' `position` codes so
manual and automated readings of a plot group together.
