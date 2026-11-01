# ENSDF-Agent

Part of the Agent/ML Technical Development at the Nuclear Data Group at the Facility for Rare Isotope Beams (nucleardata@frib.msu.edu).

Supported by the U.S. Department of Energy, Office of Science, Office of Nuclear Physics under Award Number DE-SC0016948.

Open-source release: [github.com/FRIBND/ENSDF-Agent](https://github.com/FRIBND/ENSDF-Agent)

## Installation

Install from the Git repository:

1. Open the VS Code Command Palette (`kb(workbench.action.showCommands)`):
   - Windows/Linux: `Ctrl + Shift + P`
   - macOS: `Cmd + Shift + P`
2. Run **Chat: Install Plugin from Source**.
3. Enter `https://github.com/FRIBND/ENSDF-Agent` and press Enter.

Alternatively, open **Chat: Open Customizations**, select **Plugins**, and use the **+** button next to **User** (profile-wide) or **Workspace** (current workspace).

## Overview

The first Agent designed for Evaluated Nuclear Structure Data File (ENSDF) workflows.
Developed and refined through daily evaluation tasks at FRIB Nuclear Data Group.

Built on the open-source platforms Microsoft Visual Studio Code and GitHub Copilot, **ENSDF-Agent** employs Harness Engineering and Semantic Structuring to orchestrate an evaluator-in-the-loop agentic workflow.

## Development Timeline

- 2026-10-21: **ENSDF-Agent** was demonstrated at 26th Technical Meeting of the International Network of Nuclear Structure and Decay Data Evaluators (NSDD) at MSU.
- 2026-09-17: Guard-edit Hook was introduced to resolve AI-human concurrent editing conflicts.
- 2026-08-13: **ENSDF-Agent** Harness was introduced at the 2026 Low Energy Community Meeting at ANL.
- 2026-08-11: Migrated **ENSDF-Agent** Plugin to [Agent Plugins 1.0](https://agent-plugins.org/) open standard format.
- 2026-05-07: **ENSDF-Agent** Harness was refined for improved token efficiency, consuming <30K input tokens in one round.
- 2026-03-25: **ENSDF-Agent** Version 0.0.1, with 3 Agent Hooks and 24 Agent Skills, was released as an Agent Plugin via the Microsoft VS Code Plugin Marketplace.
- 2026-03-04: **ENSDF-Agent** became available as an open-source repository at [github.com/FRIBND/ENSDF-Agent](https://github.com/FRIBND/ENSDF-Agent).
- 2026-02-23: Agent Skills were introduced as modular, portable capabilities that can be dynamically loaded into **ENSDF-Agent** to perform specific tasks within ENSDF workflows.
- 2025-11-14: The FRIBND Custom Agent Chat Mode was upgraded to **ENSDF-Agent**.
- 2025-10-30: The FRIBND AI Agent was introduced at the 2025 U.S. Nuclear Data Program Meeting.
- 2025-08-14: The FRIBND AI Agent was first introduced at the 2025 Low Energy Community Meeting at TAMU.
- 2025-08-06: The initial version of the FRIBND Custom Agent Chat Mode was posted within [github.com/sunlijie-msu/ENSDF](https://github.com/sunlijie-msu/ENSDF).

## Prerequisites

- **Python 3** on PATH — hooks and ENSDF validation scripts require it.
- Windows users: Python must be invokable as `python` from terminal.


## Troubleshooting

See [VS Code's plugin troubleshooting guide](https://code.visualstudio.com/docs/agent-customization/agent-plugins#_troubleshooting).

## Hooks

Four hooks in `com.github.copilot/hooks/hooks.json` use the same base format as [workspace hooks](https://code.visualstudio.com/docs/agent-customization/hooks#_hook-configuration-format). All fire automatically for any active agent while the plugin is enabled.

| Hook | Event | Blocks | Allows |
|------|-------|--------|--------|
| `block-root-file-creation` | PreToolUse | File/directory creation, patch add-file, or terminal writes at workspace root, `A<N>/`, or `XUNDL/` | `.github/temp/`; non-write tools |
| `block-git-revert` | PreToolUse | `git restore`/`git checkout` on `.ens` or non-temp paths; bare `checkout` | temp-scoped restore/checkout; `git switch`; unrelated commands |
| `guard_ens_edit` | PreToolUse | Stale `.ens` edits, repeated/mismatched anchors, edits over 8 lines, `.ens` `apply_patch` | Fresh unique anchored edits of 8 lines or fewer; reads |
| `verify_ens_edit` | PostToolUse | Non-ASCII `.ens` content; data-record 80-column ruler failures | Comment-only edits; non-`.ens` files |


## Caveats
- VS Code supports profile-wide (**User**) and workspace-scoped (**Workspace**) plugin installation. If **ENSDF-Agent** does not appear, confirm plugins are enabled and the plugin is enabled for the intended harness and scope; then start a fresh chat.
- VS Code Agent Plugins do not support shipping a standalone `copilot-instructions.md` alongside an agent; the plugin's sync tooling merges its content into `com.github.copilot/agents/ENSDF-Agent.agent.md` instead.
- Agent Skills performance and reliability vary based on the underlying LLM capabilities and the complexity of the task.

- VS Code extension-contributed agents and skills will negatively impact the user experience of **ENSDF-Agent**. Extensions register these agents via their package.json contribution points. When an extension is enabled, its agents and skills are automatically discovered and added to the chat menu. Currently, there is no setting in VS Code to disable or hide these extension-contributed agents while still keeping the main extension enabled. One workaround is to execute Workspace-Level Disable: Click the Gear icon (Manage) directly on the extension list item. Select Disable (Workspace) from the dropdown menu.

## Disclaimer and Usage Notice

**ENSDF-Agent** is designed to assist in nuclear data evaluation, not a substitute for human evaluators. It does not possess true understanding or expertise in nuclear physics.

AI-generated content in data sets require review and judgment by human evaluators for scientific and technical accuracy.

The human evaluator remains the sole authority and is responsible for the validity of any datasets submitted to NNDC, IAEA, or other organizations.

**ENSDF-Agent** developers and affiliated institutions (FRIB/MSU) disclaim all responsibility for errors, data loss, or scientific inaccuracies.

Use of this software constitutes acceptance of these terms.

Contact: nucleardata@frib.msu.edu

## License

MIT


#### ENSDF-Agent Architecture
<img width="2752" height="1536" alt="Architecture" src="https://github.com/user-attachments/assets/63ee8a24-89d5-45df-b60e-237094add77f" />
