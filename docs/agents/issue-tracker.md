# Issue tracker: Local Markdown

Issues and PRDs for this repo live as markdown files in `issues/`.

## Conventions

- Implementation issues are `issues/<NNN>-<slug>.md`, zero-padded and numbered
  from `001` (e.g. `001-add-red-timescaledb-instance.md`).
- PRDs are `issues/prd.md`, or `issues/prd-<twin>-<feature>.md` for scoped PRDs
  (e.g. `issues/prd-blue-insect-upload.md`).
- Each issue links its parent PRD under a `## Parent PRD` heading.
- Triage state is recorded as a `**Status:**` line near the top of each issue
  file, using one of the role strings in `triage-labels.md`. Completed issues
  may instead carry a prose status (e.g. `✅ Completed and verified <date>`).
- Comments and conversation history append to the bottom under a `## Comments`
  heading.

## When a skill says "publish to the issue tracker"

Create a new file under `issues/`: a PRD as `issues/prd-<slug>.md`, or an
implementation issue as `issues/<NNN>-<slug>.md` using the next free number.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or
the issue number directly.
