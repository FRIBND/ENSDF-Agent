---
name: ensdf-header-setup
disable-model-invocation: true
description: "Use when setting up or updating ENSDF headers for a new mass-chain evaluation cycle: sorting .ens/.old/.xundl sources into new/ and old/, stamping the IDENTIFICATION record cols 66-80, and inserting the new History (H) record. Triggers: header update, mass chain setup, ENSDF 202709, H record, unconverted XUNDL file."
argument-hint: [mass number | element symbol | file path]
---

> Bundled relative paths are relative to this file. Plugin command paths use `<plugin-root>` as a placeholder, not an environment variable. Find the installed directory containing `plugin.json`, replace the placeholder with its absolute path, and quote/escape the full path for the shell in use before executing. The workspace remains the working directory for data files.


# ENSDF Header Setup

1. Copy every `.old` and `.xundl` to `old/`; copy every `.ens` to `new/`, and each `.xundl` to `new/` renamed to `.ens`. Keep the `_xundl-N` suffix in the filename, since each XUNDL-N is an independently compiled dataset even when the reaction/decay prefix repeats.
2. Header: IDENTIFICATION record cols 66-80 → `ENSDF    YYYYMM`; insert the new `H` record directly after the IDENTIFICATION record.
3. Run `python "<plugin-root>/scripts/update_headers.py" <chain|isotope|file> [--check]`.
4. Validate with `"<plugin-root>/scripts/ensdf_1line_ruler.py" --file <f> --show-only-wrong` and `"<plugin-root>/scripts/column_calibrate.py" <f>`, then confirm via `git diff` that only header lines changed. Validator defects on data or comment lines are legacy issues: report them, do not fix them here.
5. Never edit `old/` files; only INSERT the new `H` record, keeping legacy `H` records unchanged; every record exactly 80 characters.
