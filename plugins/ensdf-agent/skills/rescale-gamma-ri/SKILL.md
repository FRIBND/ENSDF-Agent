---
name: rescale-gamma-ri
description: Rescales G-record relative intensities (RI) and their uncertainties within a single adopted level block when the contributing datasets use different RI=100 normalization references.
---

> Bundled relative paths are relative to this file.


# Rescaling Relative Intensities (Adopted Dataset)

ENSDF record/field definitions, column positions, uncertainty notation: `../../com.github.copilot/agents/ENSDF-Agent.agent.md`. Rules and spot-check policy: `../../com.github.copilot/agents/ENSDF-Agent.agent.md`.

**Problem** — within a single level block, different datasets may place RI=100 on a different γ. Adopted RI are normalized per level, with the strongest γ set to RI=100. Therefore, every dataset cited in a `cG RI$` comment must be anchored to the same γ at RI=100.

**Scope** — G-records under one L-record in an adopted dataset (e.g., `ElementA_adopted.ens`) whose RI come from datasets with different RI=100 references. *Fill in:* the adopted RI standard, whose RI/DRI enters the fields verbatim = `[dataset]`; the datasets to rescale into `cG RI$other` = `[datasets]`.

1. Adopt the RI standard: its reference γ has RI=100. Copy its RI and DRI verbatim into the G-record fields.
2. Transcribe each dataset's reference RI/DRI from its source record or supplied source table; do not reuse an adopted value as a source value.
3. Compute k = RI_ref(adopted) / RI_ref(other) at the same physical reference γ, then multiply each other RI and uncertainty by k.
4. Round value and σ together per `../rounding/SKILL.md`; align decimal places and avoid over-rounding σ.
5. Add `cG RI$other: RI' {Iσ'} from REACTION.`; delete superseded average comments and continuations.
6. Never average RI values with different references; rescaling exposes the disagreement.

**Attribution check** - to identify which dataset an adopted RI came from, rescale each candidate source by its block factor k and compare value *and* uncertainty: DRI_adopted = k*DRI_src*10^(decimals_adopted-decimals_src). An exact value+DRI match identifies the source; a smaller adopted DRI means the field came from elsewhere (or the reference gamma's DRI was deliberately dropped).

**Safeguards** — verify level/gamma identity and source normalization before arithmetic. After editing, assert adopted fields are unchanged, rescaled comments match the calculation, and old average text is absent.

**Validation** — check RI/DRI columns 23-31 and exact changed-line scope; run `../../scripts/column_calibrate.py` and `../../scripts/check_gamma_ordering.py`. Follow `../../com.github.copilot/agents/ENSDF-Agent.agent.md` for full rules.
