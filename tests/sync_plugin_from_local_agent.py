"""
Regenerates the plugins/ensdf-agent/ payload from the local ENSDF workspace
(default source: D:/X/ND/ENSDF/.github).

Run order, see main():
    1. bump_versions()     - bump manifests and return canonical version.
    2. sync_readme()       - copy repo README if changed.
    3. sync_agent_file()   - generate the single agent in
                                                     com.github.copilot/agents/ from source; retain
                                                     agent-scoped hooks and inject canonical version.
    4. sync_plugin_hooks() - generate the single hook config in
                                                     com.github.copilot/hooks/ from source definitions.
    5. sync()              - package prompts/ as Copilot commands and mirror
                                                     scripts/ and skills/ into supported paths.

plugin.json is plugin-owned. Agent and hook outputs are generated in the Agent
Plugins 1.0 Copilot namespace; legacy root copies are removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


# Managed source entries. Prompt-folder SKILL.md files are packaged as Copilot commands.
managed_entries = (
    "prompts",
    "scripts",
    "skills",
)
managed_plugin_entries = (
    "com.github.copilot/commands",
    "scripts",
    "skills",
)

# Any path containing one of these directory names, anywhere in its parts, is
# skipped entirely: never copied into the plugin, and any stale copy already
# in the plugin is removed.
excluded_segments = {
    "docs",
    "temp",
    "__pycache__",
}

# JSON files that carry the plugin version, updated by bump_versions(). The
# first entry is canonical: its "version" value is read as the old version
# before bumping, then the new version is written to every file in this list.
version_files = [
    Path("plugins/ensdf-agent/plugin.json"),  # canonical source
    Path(".claude-plugin/marketplace.json"),
    Path(".github/plugin/marketplace.json"),
]


def get_canonical_version(repo_root: Path) -> str:
    """Read current canonical version string from plugin.json."""
    canonical = repo_root / version_files[0]
    text = canonical.read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"', text)
    if not match:
        raise ValueError(f"Cannot find version field in {canonical}")
    return match.group(1)


def bump_versions(repo_root: Path, bump: str, dry_run: bool) -> str:
    """Bump the plugin version using single-digit patch rollover and return the new version."""
    canonical = repo_root / version_files[0]
    text = canonical.read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"', text)
    if not match:
        raise ValueError(f"Cannot find version field in {canonical}")
    old = match.group(1)
    major, minor, patch = (int(x) for x in old.split("."))

    if bump == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
        if patch >= 10:
            minor += 1
            patch = 0

    new = f"{major}.{minor}.{patch}"

    print(f"Version bump ({bump}): {old} → {new}")
    for rel in version_files:
        label = rel.as_posix()
        if dry_run:
            print(f"  WOULD UPDATE {label}")
        else:
            path = repo_root / rel
            updated = re.sub(r'"version"\s*:\s*"[^"]*"', f'"version": "{new}"', path.read_text(encoding="utf-8"))
            path.write_text(updated, encoding="utf-8")
            print(f"  UPDATED {label}")
    print()
    return new


def normalize_relative_path(path: Path | str) -> Path:
    return Path(path)


def plugin_relative_path(path: Path) -> Path:
    if path.parts and path.parts[0] == "prompts":
        if len(path.parts) == 3 and path.name == "SKILL.md":
            return Path(
                "com.github.copilot",
                "commands",
                f"{path.parts[1]}.prompt.md",
            )
        return Path("com.github.copilot", "commands", *path.parts[1:])
    return path


def is_excluded(relative_path: Path) -> bool:
    return any(part in excluded_segments for part in relative_path.parts)


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_managed_source_files(source_root: Path) -> list[Path]:
    files: list[Path] = []
    for entry in managed_entries:
        full_path = source_root / entry
        if not full_path.exists():
            continue

        if full_path.is_dir():
            for child in full_path.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(source_root)
                if not is_excluded(relative):
                    files.append(relative)
            continue

        relative_file = normalize_relative_path(entry)
        if not is_excluded(relative_file):
            files.append(relative_file)

    return sorted(set(files))


def iter_managed_target_files(plugin_root: Path) -> list[Path]:
    files: list[Path] = []
    for entry in managed_plugin_entries:
        full_path = plugin_root / entry
        if not full_path.exists():
            continue

        if full_path.is_dir():
            for child in full_path.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(plugin_root)
                if not is_excluded(relative):
                    files.append(relative)
            continue

        relative_file = normalize_relative_path(entry)
        if not is_excluded(relative_file):
            files.append(relative_file)

    return sorted(set(files))


def plugin_prompt_content(source_path: Path, source_relative: Path) -> str:
    text = source_path.read_text(encoding="utf-8")
    if source_relative.parts and source_relative.parts[0] == "prompts":
        command_name = source_relative.parts[1]
        text = re.sub(
            r"(?m)^name:\s*.*$",
            f"name: {command_name}",
            text,
            count=1,
        )
    return text


def remove_empty_directories(root: Path) -> None:
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        if any(directory.iterdir()):
            continue
        directory.rmdir()


def collect_excluded_directories(root: Path) -> list[Path]:
    directories = [
        path
        for path in root.rglob("*")
        if path.is_dir() and path.name in excluded_segments
    ]
    return sorted(set(directories), reverse=True)


def sync_readme(repo_root: Path, plugin_root: Path, dry_run: bool) -> None:
    """Copy repo-root README.md into the plugin payload directory."""
    source = repo_root / "README.md"
    target = plugin_root / "README.md"
    if not source.is_file():
        print("SKIP   README.md (source not found)")
        return
    if target.is_file() and sha256sum(source) == sha256sum(target):
        print("SKIP   README.md")
        return
    if dry_run:
        print("COPY   README.md")
    else:
        shutil.copy2(source, target)
        print("COPIED README.md")


def parse_frontmatter_scalar(value: str):
    """Parse the simple scalar values used by hook entries in agent frontmatter."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def rewrite_plugin_hook_path(command: str) -> str:
    """Make a source hook command valid after plugin installation.

    Source commands point into ``.github/hooks`` inside the workspace. Plugin
    hooks run from an external install directory, so bundled files must use
    ``${PLUGIN_ROOT}`` and be quoted for paths containing spaces.
    """
    command = command.replace("\\", "/")
    command = command.replace(".github/hooks/", "${PLUGIN_ROOT}/com.github.copilot/hooks/")
    return re.sub(
        r'(?<!["\'])\$\{PLUGIN_ROOT\}/com\.github\.copilot/hooks/[^\s"\']+',
        r'"\g<0>"',
        command,
    )


def normalize_hook_event(event: str) -> str:
    return {
        "PreToolUse": "preToolUse",
        "PostToolUse": "postToolUse",
    }.get(event, event)


def rewrite_hook_entry(entry: dict, plugin_wide: bool = False) -> dict:
    rewritten = {}
    for key, value in entry.items():
        if key in {"command", "windows", "linux", "osx", "bash", "powershell"} and isinstance(value, str):
            output_key = key
            if plugin_wide and key == "windows":
                output_key = "powershell"
            elif plugin_wide and key in {"linux", "osx"}:
                output_key = "bash"
            rewritten[output_key] = rewrite_plugin_hook_path(value)
        elif key == "timeout":
            rewritten["timeoutSec"] = value
        else:
            rewritten[key] = value
    return rewritten


def append_hook_config(target: dict, source: dict, plugin_wide: bool = False) -> None:
    """Append hook entries while preserving order and removing duplicates."""
    source_hooks = source.get("hooks", {})
    if not isinstance(source_hooks, dict):
        raise ValueError("Hook configuration must contain a hooks object")

    for event, entries in source_hooks.items():
        if not isinstance(entries, list):
            raise ValueError(f"Hook event {event!r} must contain a list")
        event = normalize_hook_event(event)
        destination = target.setdefault(event, [])
        existing = {
            json.dumps(entry, sort_keys=True, separators=(",", ":"))
            for entry in destination
        }
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"Hook event {event!r} contains a non-object entry")
            rewritten = rewrite_hook_entry(entry, plugin_wide=plugin_wide)
            marker = json.dumps(rewritten, sort_keys=True, separators=(",", ":"))
            if marker in existing:
                continue
            destination.append(rewritten)
            existing.add(marker)


def extract_agent_frontmatter(agent_text: str) -> list[str]:
    lines = agent_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index]
    return []


def parse_agent_hook_config(agent_text: str) -> dict:
    """Read flat command hooks from the agent YAML frontmatter.

    The project hook entries use a small, stable YAML subset. Keeping this
    parser local avoids adding a PyYAML dependency to a maintenance script.
    """
    frontmatter = extract_agent_frontmatter(agent_text)
    events: dict[str, list[dict]] = {}
    in_hooks = False
    current_event = None
    current_entry = None

    def finish_entry() -> None:
        nonlocal current_entry
        if current_event is not None and current_entry is not None:
            events.setdefault(current_event, []).append(current_entry)
        current_entry = None

    for line in frontmatter:
        if not in_hooks:
            if line.strip() == "hooks:":
                in_hooks = True
            continue

        if line and not line[0].isspace():
            break

        event_match = re.match(r"^  ([A-Za-z][A-Za-z0-9_-]*):\s*$", line)
        if event_match:
            finish_entry()
            current_event = event_match.group(1)
            continue

        entry_match = re.match(r"^    -\s+type:\s*(.+?)\s*$", line)
        if entry_match:
            finish_entry()
            current_entry = {"type": parse_frontmatter_scalar(entry_match.group(1))}
            continue

        field_match = re.match(r"^      ([A-Za-z][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if field_match and current_entry is not None:
            current_entry[field_match.group(1)] = parse_frontmatter_scalar(field_match.group(2))

    finish_entry()
    return {"hooks": events}


def canonical_agent_hook_config(agent_text: str, plugin_hooks: dict) -> dict:
    """Keep agent-scoped hooks in the agent and remove plugin-wide duplicates."""
    plugin_entries = {}
    for event, entries in plugin_hooks.get("hooks", {}).items():
        plugin_entries[normalize_hook_event(event)] = {
            json.dumps(entry, sort_keys=True, separators=(",", ":"))
            for entry in entries
        }

    hooks = {}
    source_hooks = parse_agent_hook_config(agent_text).get("hooks", {})
    for event, entries in source_hooks.items():
        event = normalize_hook_event(event)
        for entry in entries:
            rewritten = rewrite_hook_entry(entry)
            marker = json.dumps(
                rewrite_hook_entry(entry, plugin_wide=True),
                sort_keys=True,
                separators=(",", ":"),
            )
            if marker in plugin_entries.get(event, set()):
                continue
            hooks.setdefault(event, []).append(rewritten)
    return {"hooks": hooks}


def render_agent_hook_block(hooks: dict) -> list[str]:
    lines = ["hooks:\n"]
    for event, entries in hooks.get("hooks", {}).items():
        lines.append(f"  {event}:\n")
        for entry in entries:
            lines.append("    - type: command\n")
            for key, value in entry.items():
                if key == "type":
                    continue
                lines.append(f"      {key}: {json.dumps(value)}\n")
    return lines


def rewrite_agent_hook_block(agent_text: str, plugin_hooks: dict) -> str:
    """Rewrite plugin paths in agent-scoped hooks and retain their scope."""
    lines = agent_text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return agent_text

    end_idx = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end_idx is None:
        return agent_text

    start_idx = next(
        (i for i in range(1, end_idx) if lines[i].rstrip("\r\n") == "hooks:"),
        None,
    )
    if start_idx is None:
        return agent_text

    block_end = start_idx + 1
    while block_end < end_idx:
        line = lines[block_end]
        if line.strip() and not line[0].isspace():
            break
        block_end += 1

    rendered = render_agent_hook_block(canonical_agent_hook_config(agent_text, plugin_hooks))
    frontmatter = lines[1:start_idx] + rendered + lines[block_end:end_idx]
    return "".join([lines[0], *frontmatter, *lines[end_idx:]])


def build_plugin_hook_config(source_root: Path) -> dict:
    """Build plugin-wide hooks from workspace hook configuration."""
    merged: dict[str, list[dict]] = {}
    workspace_config = source_root / "hooks" / "block-root-file-creation.json"
    if workspace_config.is_file():
        with workspace_config.open(encoding="utf-8") as handle:
            append_hook_config(merged, json.load(handle), plugin_wide=True)

    if not merged:
        raise FileNotFoundError(f"No source hook definitions found under {source_root}")
    return {"version": 1, "hooks": merged}


def sync_plugin_hooks(source_root: Path, plugin_root: Path, dry_run: bool) -> None:
    """Generate the single Agent Plugins 1.0 hook file and remove legacy root copy."""
    target = plugin_root / "com.github.copilot" / "hooks" / "hooks.json"
    legacy_target = plugin_root / "hooks.json"
    config = build_plugin_hook_config(source_root)
    generated = json.dumps(config, indent=2) + "\n"

    rel_label = target.relative_to(plugin_root).as_posix()
    existing = target.read_text(encoding="utf-8") if target.is_file() else None
    if existing == generated:
        print(f"SKIP   {rel_label} (unchanged)")
    elif dry_run:
        print(f"COPY   {rel_label} (generated from source hooks)")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated, encoding="utf-8")
        print(f"COPIED {rel_label} (generated from source hooks)")

    if legacy_target.is_file():
        if dry_run:
            print("REMOVE hooks.json (legacy duplicate; Agent Plugins 1.0 uses com.github.copilot/hooks/)")
        else:
            legacy_target.unlink()
            print("REMOVED hooks.json (legacy duplicate)")


def inject_agent_version(agent_text: str, version: str) -> str:
    """Inject canonical version into agent frontmatter (description, argument-hint) and title."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Invalid semantic version: {version!r}")

    lines = agent_text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return agent_text

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return agent_text

    frontmatter = lines[1:end_idx]
    remainder = "".join(lines[end_idx:])

    new_frontmatter = []
    for line in frontmatter:
        stripped = line.strip()
        if stripped.startswith("description:"):
            indent = line[: len(line) - len(line.lstrip())]
            old_desc = re.sub(r"^description:\s*", "", stripped).strip().strip('"\'')
            clean_desc = re.sub(r"^\[v\d+\.\d+\.\d+\]\s*", "", old_desc)
            escaped_desc = clean_desc.replace('\\"', '"').replace('"', '\\"')
            new_frontmatter.append(f'{indent}description: "[v{version}] {escaped_desc}"\n')
        elif stripped.startswith("argument-hint:"):
            indent = line[: len(line) - len(line.lstrip())]
            old_hint = re.sub(r"^argument-hint:\s*", "", stripped).strip().strip('"\'')
            clean_hint = re.sub(r"\s*\(v\d+\.\d+\.\d+\)", "", old_hint).rstrip("!")
            escaped_hint = clean_hint.replace('\\"', '"').replace('"', '\\"')
            new_frontmatter.append(f'{indent}argument-hint: "{escaped_hint} (v{version})"\n')
        else:
            new_frontmatter.append(line)

    remainder = re.sub(
        r"^(# ENSDF Nuclear Data Agent)(?:\s*\(v\d+\.\d+\.\d+\))?$",
        rf"\1 (v{version})",
        remainder,
        count=1,
        flags=re.MULTILINE,
    )

    return "".join(["---\n", *new_frontmatter, remainder])


def build_merged_agent_content(
    agent_text: str,
    instructions_text: str,
    version: str | None = None,
    plugin_hooks: dict | None = None,
) -> str:
    """Build the full plugin agent-file content from current source content.

    This is a full rebuild, not an incremental merge: every call recomputes
    the entire output from the two inputs currently on disk, so any edit,
    addition, or removal in either source file is reflected on the very next
    sync run. Nothing from a previous plugin copy is reused or preserved.

    Three things happen to agent_text before it's used:
      1. Agent-scoped hooks are retained, normalized, and rewritten to use the
         plugin root. Hooks duplicated by plugin-wide configuration are omitted.
      2. If ``version`` is supplied, it is injected into frontmatter
         (description, argument-hint) and title via inject_agent_version().
      3. instructions_text (copilot-instructions.md) is appended as a
         clearly labeled section, since VS Code Agent Plugins do not support
         shipping that file standalone alongside an agent.
    If instructions_text is empty (e.g. the source file was deleted), the
    appended section is simply omitted.
    """
    rewritten_agent = (
        rewrite_agent_hook_block(agent_text, plugin_hooks or {"hooks": {}})
        if plugin_hooks
        else agent_text
    )
    rewritten_agent = rewritten_agent.rstrip("\n")
    if version:
        rewritten_agent = inject_agent_version(rewritten_agent, version).rstrip("\n")
    instructions_body = instructions_text.strip("\n")

    sections = [rewritten_agent]
    if instructions_body:
        sections.append(
            "\n---\n\n"
            "*(Concatenated from `copilot-instructions.md`.)*\n\n"
            + instructions_body
        )
    return "\n".join(sections) + "\n"


def sync_agent_file(
    source_root: Path,
    plugin_root: Path,
    version: str | None = None,
    dry_run: bool = False,
) -> None:
    """Generate the single Copilot agent and remove its legacy duplicate.

    Reads source agents/ENSDF-Agent.agent.md + copilot-instructions.md fresh
    every run and rebuilds the merged output via build_merged_agent_content(),
    which rewrites and retains agent-scoped hooks, injects the canonical
    version, and appends the instructions file as a labeled section. The result is compared
    verbatim (full-text equality) against existing plugin files to decide
    COPIED/SKIP; there is no partial/section-level patch.

    Also deletes any stale standalone copilot-instructions.md left in the
    plugin payload, since that file must never ship on its own.
    """
    source_agent = source_root / "agents" / "ENSDF-Agent.agent.md"
    source_instructions = source_root / "copilot-instructions.md"
    target_agent = plugin_root / "com.github.copilot" / "agents" / "ENSDF-Agent.agent.md"
    legacy_agent = plugin_root / "agents" / "ENSDF-Agent.agent.md"
    target_instructions = [
        plugin_root / "copilot-instructions.md",
        plugin_root / "com.github.copilot" / "copilot-instructions.md",
    ]

    if not source_agent.is_file():
        print("SKIP   agents/ENSDF-Agent.agent.md (source not found)")
        return

    agent_text = source_agent.read_text(encoding="utf-8")
    instructions_text = (
        source_instructions.read_text(encoding="utf-8")
        if source_instructions.is_file()
        else ""
    )
    plugin_hooks = build_plugin_hook_config(source_root)
    merged = build_merged_agent_content(
        agent_text,
        instructions_text,
        version,
        plugin_hooks,
    )

    rel_label = target_agent.relative_to(plugin_root).as_posix()
    existing = target_agent.read_text(encoding="utf-8") if target_agent.is_file() else None
    if existing == merged:
        print(f"SKIP   {rel_label} (merged, unchanged)")
    elif dry_run:
        print(f"COPY   {rel_label} (merged with copilot-instructions.md)")
    else:
        target_agent.parent.mkdir(parents=True, exist_ok=True)
        target_agent.write_text(merged, encoding="utf-8")
        print(f"COPIED {rel_label} (merged with copilot-instructions.md)")

    if legacy_agent.is_file():
        if dry_run:
            print("REMOVE agents/ENSDF-Agent.agent.md (duplicate; Agent Plugins 1.0 path is com.github.copilot/agents/)")
        else:
            legacy_agent.unlink()
            print("REMOVED agents/ENSDF-Agent.agent.md (duplicate)")

    # copilot-instructions.md must not ship standalone — VS Code Agent Plugins
    # ignore it; remove any stale copy left in the plugin payload.
    for target_inst in target_instructions:
        if target_inst.is_file():
            rel_label = target_inst.relative_to(plugin_root).as_posix()
            if dry_run:
                print(f"REMOVE {rel_label} (merged into agents)")
            else:
                target_inst.unlink()
                print(f"REMOVED {rel_label} (merged into agents)")


def sync(source_root: Path, plugin_root: Path, dry_run: bool) -> int:
    """Package prompt-folder workflows as commands, plus scripts and skills.

    Copies new or changed files, removes stale managed files, and skips
    unchanged files plus excluded directories. Rare workflows stored in the
    source prompts/ directory remain explicitly invoked Copilot commands;
    portable skills remain under the plugin root's skills/ directory.
    """
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source .github path not found: {source_root}")
    if not plugin_root.is_dir():
        raise FileNotFoundError(f"Plugin root not found: {plugin_root}")

    source_files = iter_managed_source_files(source_root)
    target_files = iter_managed_target_files(plugin_root)
    source_targets = {
        relative: plugin_relative_path(relative)
        for relative in source_files
    }
    if len(set(source_targets.values())) != len(source_targets):
        raise ValueError("Managed source entries map to duplicate plugin paths")
    source_set = set(source_targets.values())

    copied = 0
    removed = 0
    skipped = 0

    # Pass 1: copy every source file that's missing or changed in the plugin.
    for relative in source_files:
        source_path = source_root / relative
        target_relative = source_targets[relative]
        target_path = plugin_root / target_relative
        target_path.parent.mkdir(parents=True, exist_ok=True)

        copy_needed = True
        if target_path.is_file():
            if relative.parts and relative.parts[0] == "prompts":
                copy_needed = plugin_prompt_content(source_path, relative) != target_path.read_text(encoding="utf-8")
            else:
                copy_needed = sha256sum(source_path) != sha256sum(target_path)

        if not copy_needed:
            print(f"SKIP   {target_relative.as_posix()}")
            skipped += 1
            continue

        if dry_run:
            print(f"COPY   {target_relative.as_posix()}")
        else:
            if relative.parts and relative.parts[0] == "prompts":
                target_path.write_text(
                    plugin_prompt_content(source_path, relative),
                    encoding="utf-8",
                )
            else:
                shutil.copy2(source_path, target_path)
            print(f"COPIED {target_relative.as_posix()}")
        copied += 1

    # Pass 2: remove any plugin file whose source no longer exists.
    for relative in target_files:
        if relative in source_set:
            continue

        target_path = plugin_root / relative
        if dry_run:
            print(f"REMOVE {relative.as_posix()}")
        else:
            target_path.unlink()
            print(f"REMOVED {relative.as_posix()}")
        removed += 1

    for directory in collect_excluded_directories(plugin_root):
        relative = directory.relative_to(plugin_root)
        if dry_run:
            print(f"REMOVE {relative.as_posix()}")
        else:
            shutil.rmtree(directory)
            print(f"REMOVED {relative.as_posix()}")

    if not dry_run:
        remove_empty_directories(plugin_root)

    print()
    print("Sync Summary")
    print(f"  Source:  {source_root}")
    print(f"  Target:  {plugin_root}")
    print(f"  Copied:  {copied}")
    print(f"  Removed: {removed}")
    print(f"  Skipped: {skipped}")
    if dry_run:
        print("  Mode:    dry-run")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync ENSDF-Agent plugin from local ENSDF .github workspace."
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Preview actions without modifying files.",
    )
    parser.add_argument(
        "--no-bump",
        action="store_true",
        help="Skip version bumping.",
    )
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
        help="Version bump level (default: patch).",
    )
    args = parser.parse_args()
    if args.no_bump and "--bump" in sys.argv:
        parser.error("Cannot combine --bump with --no-bump.")
    return args


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    plugin_root = repo_root / "plugins" / "ensdf-agent"
    source_root = Path(r"D:\X\ND\ENSDF\.github")

    if not args.no_bump:
        version = bump_versions(repo_root, args.bump, args.dry_run)
    else:
        version = get_canonical_version(repo_root)
    sync_readme(repo_root, plugin_root, args.dry_run)
    sync_agent_file(source_root, plugin_root, version, args.dry_run)
    sync_plugin_hooks(source_root, plugin_root, args.dry_run)
    return sync(source_root, plugin_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
