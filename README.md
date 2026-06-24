# ENSDF-Agent

Part of the AI/ML Technical Innovation at the FRIB Nuclear Data Group (nucleardata@frib.msu.edu).

## Overview

The first AI Agent designed for Evaluated Nuclear Structure Data File (ENSDF) workflows.
Developed and refined through daily evaluation tasks at the Nuclear Data Group at the Facility for Rare Isotope Beams (FRIB).

Built on the open-source platforms Microsoft Visual Studio Code and GitHub Copilot, ENSDF-Agent employs Harness Engineering and Semantic Structuring and integrates the power of rapidly advancing Large Language Models (LLMs) into the routine workflows of nuclear data evaluators.

## Development Timeline

- 2026-05-07: ENSDF-Agent was refined for improved token efficiency and robust, operational use in real-world ENSDF evaluation workflows. Input tokens are <30,000 in a model turn without datasets.
- 2026-03-25: ENSDF-Agent Version 0.0.1, with 3 Agent Hooks and 24 Agent Skills, was released as an Agent Plugin via the Microsoft VS Code Plugin Marketplace.
- 2026-03-04: ENSDF-Agent became available as an open-source repository at [github.com/FRIBND/ENSDF-Agent](https://github.com/FRIBND/ENSDF-Agent).
- 2026-02-23: Agent Skills were introduced as modular, portable capabilities that can be dynamically loaded into ENSDF-Agent to perform specific tasks within ENSDF workflows.
- 2025-11-14: The FRIBND Custom Agent Chat Mode was upgraded to ENSDF AI Agent.
- 2025-10-30: The FRIBND AI Agent was introduced at the 2025 U.S. Nuclear Data Program Meeting.
- 2025-08-14: The FRIBND AI Agent was first introduced at the 2025 Low Energy Community Meeting.
- 2025-08-06: The initial version of the FRIBND Custom Agent Chat Mode was posted within [github.com/sunlijie-msu/ENSDF](https://github.com/sunlijie-msu/ENSDF).


## Installation

1. Configure plugin marketplaces by clicking "Add Item" and entering `FRIBND/ENSDF-Agent` in the `setting(chat.plugins.marketplaces)` setting.
2. Open the Extensions view (`kb(workbench.view.extensions)`) and enter `@agentPlugins ENSDF-Agent` in the search field.
   - Alternatively, select the **More Actions** (three dots) icon in the Extensions sidebar and choose **Views** > **Agent Plugins**.
3. Click **Install** to install the ENSDF-Agent Plugin in your user profile.

## Hooks

Three hooks enforce safety and data integrity. All fire automatically — no configuration required after installation.

| Hook | Level | Event | What it blocks/checks |
|------|-------|-------|----------------------|
| `block-root-file-creation` | workspace | PreToolUse | Denies `create_file` targeting workspace root, mass-chain dirs (`A<N>/`), or `XUNDL/`; forces temp files to `.github/temp/` |
| `block-git-revert` | agent | PreToolUse | Denies `git restore`/`git checkout` on `.ens` files or non-temp paths; preserves VS Code diff viewer for human review |
| `validate_ens` | agent | PostToolUse | Two-pass validation after every `.ens` edit: **PASS 1** (always) — ASCII-only check, blocks non-ASCII chars; **PASS 2** (data records only) — 80-column ruler via `ensdf_1line_ruler.py`, skipped for comment-only edits |

## Caveats

- VS Code does not support installing Agent Plugins in a specific workspace.
- VS Code Agent Plugins do not support workspace-level `copilot-instructions.md` shipped with the plugin.
- VS Code Agent Plugins do not support agent-scoped hooks; plugin hooks fire for any active agent while the plugin is enabled.
- Agent Skills performance and reliability vary based on the underlying LLM capabilities and the complexity of the task.


- VS Code extension-contributed agents and skills will negatively impact the user experience of the ENSDF-Agent. Extensions register these agents via their package.json contribution points. When an extension is enabled, its agents and skills are automatically discovered and added to the chat menu.

Currently, there is no setting in VS Code to disable or hide these extension-contributed agents while still keeping the main extension enabled. One workaround is to execute Workspace-Level Disable:
Click the Gear icon (Manage) directly on the extension list item.
Select Disable (Workspace) from the dropdown menu.

## Disclaimer and Usage Notice

ENSDF-Agent is designed to assist in nuclear data evaluation, not a substitute for human evaluators. It does not possess true understanding or expertise in nuclear physics.

AI-generated content must be independently verified by human evaluators for scientific and technical accuracy.

The human evaluator remains the sole authority and is responsible for the validity of any datasets submitted to NNDC, IAEA, or other organizations.

ENSDF-Agent developers and affiliated institutions (FRIB/MSU) disclaim all responsibility for errors, data loss, or scientific inaccuracies.

Use of this software constitutes acceptance of these terms.

Contact: nucleardata@frib.msu.edu

## License

MIT


#### ENSDF-Agent Architecture
<img width="2752" height="1536" alt="Architecture" src="https://github.com/user-attachments/assets/63ee8a24-89d5-45df-b60e-237094add77f" />


