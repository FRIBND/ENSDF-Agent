---
name: nsr-update
disable-model-invocation: true
description: >
  Update NSR key numbers consistently across ENS content, filenames, and
  tracking docs while preserving exact case conventions and validating the
  final replacements.
argument-hint: "oldUpper newUpper oldMixed newMixed citation"
---

> Bundled relative paths are relative to this file.


# NSR update consistency

ENSDF 80-column data record and field definitions, structural rules, column positions, and uncertainty notation: `../../com.github.copilot/agents/ENSDF-Agent.agent.md`. Spot-check policy: `../../com.github.copilot/agents/ENSDF-Agent.agent.md`.

## Task

Apply exact, case-sensitive replacements for NSR keys across:
1. target ENS content,
2. ENS filenames,
3. tracking markdown files.

## Rules

- Use `oldUpper -> newUpper` and `oldMixed -> newMixed` only.
- Do not cross-replace keys.
- Keep only the canonical new filename if both old and new filenames exist.
- Validate with targeted searches for stale keys in edited ENS files.

## Validation

- Search for stale NSR keys in the affected files.
- Confirm the final filenames and references match the requested update.
- Report a concise checklist: files changed, replacements applied, validation results.
