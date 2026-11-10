---
name: ens2pdf
disable-model-invocation: true
description: >
  Run the ens2pdf.py Python wrapper to convert ENSDF .ens files to PDF using
  the McMaster-MSU Java NDS tool. Supports single files, element-level batches,
  and glob patterns. Optionally opens the result.
argument-hint: "File name, element symbol, or glob pattern (e.g. Si35_adopted, Si, Si35_*sig)"
---

> Warning: the current bundled ens2pdf.py uses hardcoded paths and selections and does not implement the argument-based examples below. Do not execute those examples; configure or update the source script first.


> Bundled relative paths are relative to this file. Plugin command paths use `<plugin-root>` as a placeholder, not an environment variable. Find the installed directory containing `plugin.json`, replace the placeholder with its absolute path, and quote/escape the full path for the shell in use before executing. The workspace remains the working directory for data files.


# ENSDF PDF export

ENSDF 80-column data record and field definitions, structural rules, column positions, and uncertainty notation: `../../com.github.copilot/agents/ENSDF-Agent.agent.md`. Spot-check policy: `../../com.github.copilot/agents/ENSDF-Agent.agent.md`.

## Usage

```bash
python "<plugin-root>/scripts/ens2pdf.py" Si35_adopted
python "<plugin-root>/scripts/ens2pdf.py" "finished/Si35/new/Si35_adopted.ens"
python "<plugin-root>/scripts/ens2pdf.py" Si
python "<plugin-root>/scripts/ens2pdf.py" "Si35_*sig"
python "<plugin-root>/scripts/ens2pdf.py" Si35_adopted --open
python "<plugin-root>/scripts/ens2pdf.py" Si35_adopted --open --system
```

## Options

- No flag: convert and save PDF without opening it.
- `--open`: open the result in VS Code after conversion.
- `--open --system`: open the result in the system default PDF viewer.

## Notes

- The script resolves partial names and glob patterns against the workspace tree.
- Multiple matches are converted sequentially.
- The Java tool must be present at `D:\X\ND\McMaster-MSU-Java-NDS\`.
