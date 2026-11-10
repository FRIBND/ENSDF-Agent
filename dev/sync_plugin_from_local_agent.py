"""
Regenerates the plugins/ensdf-agent/ payload from the local ENSDF workspace
(default source: D:/X/ND/ENSDF/.github).

Run from the repository root with: python dev/sync_plugin_from_local_agent.py

Run order, see main():
    1. bump_versions()     - bump manifests and return canonical version.
    2. sync_readme()       - copy repo README if changed.
    3. sync_agent_file()   - generate the single agent in
                             com.github.copilot/agents/ from source; retain
                             agent-scoped hooks and inject canonical version.
    4. sync()              - package skills-dormant/ as explicit Copilot
                             commands and mirror scripts/, hooks/scripts/,
                             and skills/ into supported paths.

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


# Dormant SKILL.md files become explicit slash commands so they are not added
# to the plugin's automatically discovered skill catalog.
managed_entries = (
    "scripts",
    "skills",
    "skills-dormant",
    "hooks/scripts",
)
managed_plugin_entries = (
    "com.github.copilot/commands",
    "scripts",
    "skills",
    "com.github.copilot/hooks/scripts",
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
    if path.parts and path.parts[0] == "skills-dormant":
        if len(path.parts) == 3 and path.name == "SKILL.md":
            return Path(
                "com.github.copilot",
                "commands",
                f"{path.parts[1]}.prompt.md",
            )
        raise ValueError(
            "Dormant skills must contain one SKILL.md at "
            f"<skill-name>/SKILL.md; unsupported source path: {path}"
        )
    if path.parts[:2] == ("hooks", "scripts"):
        return Path("com.github.copilot", "hooks", *path.parts[1:])
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


def plugin_command_content(source_path: Path, source_relative: Path) -> str:
    text = source_path.read_text(encoding="utf-8")
    if source_relative.parts and source_relative.parts[0] == "skills-dormant":
        command_name = source_relative.parts[1]
        text = re.sub(
            r"(?m)^name:\s*.*$",
            f"name: {command_name}",
            text,
            count=1,
        )
        text = re.sub(
            r"(?m)^[ \t]*disable-model-invocation:[^\r\n]*(?:\r?\n|$)",
            "",
            text,
            count=1,
        )
    return text


def is_command_source(source_relative: Path) -> bool:
    return bool(source_relative.parts and source_relative.parts[0] == "skills-dormant")


def validate_source_layout(source_root: Path) -> None:
    """Fail before syncing if a managed source directory is absent or malformed."""
    source_agent = source_root / "agents" / "ENSDF-Agent.agent.md"
    if not source_agent.is_file():
        raise FileNotFoundError(f"Source agent not found: {source_agent}")

    for entry in managed_entries:
        path = source_root / entry
        if not path.is_dir():
            raise FileNotFoundError(f"Managed source directory not found: {path}")
        if not any(child.is_file() for child in path.rglob("*")):
            raise ValueError(f"Managed source directory is empty: {path}")

    dormant_root = source_root / "skills-dormant"
    for skill_dir in dormant_root.iterdir():
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
            raise ValueError(
                "Each dormant skill must be a folder containing SKILL.md: "
                f"{skill_dir}"
            )
    unsupported_files = [
        path
        for path in dormant_root.rglob("*")
        if path.is_file() and path.name != "SKILL.md"
    ]
    if unsupported_files:
        raise ValueError(
            "Dormant skills can only be packaged as command files; "
            "unsupported resources: "
            + ", ".join(str(path) for path in unsupported_files)
        )


def _agent_hook_record_count(agent_text: str) -> int:
    """Count hook entries in agent frontmatter for rewrite preservation checks."""
    lines = agent_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return 0
    frontmatter_end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if frontmatter_end is None:
        return 0
    hooks_start = next(
        (
            index
            for index in range(1, frontmatter_end)
            if re.fullmatch(r"hooks:[ \t]*(?:#.*)?", lines[index])
        ),
        None,
    )
    if hooks_start is None:
        return 0
    hooks_end = next(
        (
            index
            for index in range(hooks_start + 1, frontmatter_end)
            if lines[index].strip() and not lines[index][0].isspace()
        ),
        frontmatter_end,
    )
    return sum(
        1
        for line in lines[hooks_start + 1:hooks_end]
        if re.match(r"^[ \t]*-[ \t]+type[ \t]*:", line)
    )


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


def rewrite_plugin_hook_path(command: str) -> str:
    """Rewrite bundled script paths in a shell command, preserving its arguments."""
    source_path = re.compile(
        r"(?P<quoted>['\"])(?P<quoted_path>(?:\./)?\.github[\\/]+hooks[\\/]+.*?)(?P=quoted)"
        r"|(?P<bare>(?:\./)?\.github[\\/]+hooks[\\/]+[^\s\"';&|<>]+)"
    )

    def replace(match: re.Match[str]) -> str:
        path = match.group("quoted_path") or match.group("bare")
        path = path.replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        rewritten = "${PLUGIN_ROOT}/com.github.copilot/hooks/" + path[len(".github/hooks/"):]
        quote = match.group("quoted")
        return f"{quote}{rewritten}{quote}" if quote else f'"{rewritten}"'

    return source_path.sub(replace, command, count=1)


def rewrite_plugin_hook_executable(executable: str) -> str:
    """Rewrite a direct hook executable path without adding shell quoting."""
    source_path = re.fullmatch(
        r"(?:\./)?\.github[\\/]+hooks[\\/]+(.+)",
        executable,
    )
    if not source_path:
        return executable
    relative_path = source_path.group(1).replace("\\", "/")
    return "${PLUGIN_ROOT}/com.github.copilot/hooks/" + relative_path


def _decode_hook_string_scalar(value: str) -> tuple[str, str] | None:
    """Decode a simple YAML string scalar and return its trailing comment/space."""
    stripped = value.strip()
    if stripped in {"|", "|-", "|+", ">", ">-", ">+"}:
        return None

    trailing = value[len(value.rstrip()):]
    if stripped.startswith('"'):
        try:
            decoded, end = json.JSONDecoder().raw_decode(stripped)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid quoted hook command scalar: {value!r}") from error
        suffix = stripped[end:]
        if suffix and not (suffix.lstrip().startswith("#")):
            raise ValueError(f"Unexpected text after hook command scalar: {suffix!r}")
        return decoded, suffix + trailing

    if stripped.startswith("'"):
        end = 1
        decoded_chars = []
        while end < len(stripped):
            char = stripped[end]
            if char == "'":
                if end + 1 < len(stripped) and stripped[end + 1] == "'":
                    decoded_chars.append("'")
                    end += 2
                    continue
                break
            decoded_chars.append(char)
            end += 1
        if end == len(stripped):
            raise ValueError(f"Unterminated quoted hook command scalar: {value!r}")
        suffix = stripped[end + 1:]
        if suffix and not suffix.lstrip().startswith("#"):
            raise ValueError(f"Unexpected text after hook command scalar: {suffix!r}")
        return "".join(decoded_chars), suffix + trailing

    comment_at = next(
        (
            index
            for index, char in enumerate(stripped)
            if char == "#" and (index == 0 or stripped[index - 1].isspace())
        ),
        None,
    )
    if comment_at is None:
        return stripped, trailing
    return stripped[:comment_at].rstrip(), stripped[comment_at:] + trailing


def _rewrite_hook_command_line(line: str, field_indent: int) -> tuple[str, bool]:
    """Rewrite one hook executable field; report whether it starts a block scalar."""
    match = re.match(
        r"^(?P<indent>[ \t]*)(?P<key>command|exec|bash|powershell|windows|linux|osx):"
        r"(?P<spacing>[ \t]*)(?P<value>.*?)(?P<newline>\r?\n)?$",
        line,
    )
    if not match or len(match.group("indent")) != field_indent:
        return line, False

    key = match.group("key")
    raw_value = match.group("value")
    if raw_value.strip() in {"|", "|-", "|+", ">", ">-", ">+"}:
        return line, True

    if ".github" not in raw_value or "hooks" not in raw_value:
        return line, False
    decoded = _decode_hook_string_scalar(raw_value)
    if decoded is None:
        return line, True
    value, suffix = decoded
    if key == "exec":
        rewritten = rewrite_plugin_hook_executable(value)
    else:
        rewritten = rewrite_plugin_hook_path(value)
    if rewritten == value:
        return line, False

    return (
        f"{match.group('indent')}{key}:{match.group('spacing')}"
        f"{json.dumps(rewritten)}{suffix}{match.group('newline') or ''}",
        False,
    )


def rewrite_agent_hook_block(agent_text: str) -> str:
    """Rewrite bundled paths in an agent's hooks without moving or reformatting them."""
    lines = agent_text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return agent_text

    frontmatter_end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if frontmatter_end is None:
        return agent_text

    hooks_start = next(
        (
            index
            for index in range(1, frontmatter_end)
            if re.fullmatch(r"hooks:[ \t]*(?:#.*)?(?:\r?\n)?", lines[index])
        ),
        None,
    )
    if hooks_start is None:
        return agent_text

    hooks_end = next(
        (
            index
            for index in range(hooks_start + 1, frontmatter_end)
            if lines[index].strip() and not lines[index][0].isspace()
        ),
        frontmatter_end,
    )
    current_field_indent = None
    index = hooks_start + 1
    while index < hooks_end:
        item_match = re.match(r"^(?P<indent>[ \t]*)-\s+type:", lines[index])
        if item_match:
            current_field_indent = len(item_match.group("indent")) + 2

        if current_field_indent is not None:
            rewritten, is_block = _rewrite_hook_command_line(
                lines[index],
                current_field_indent,
            )
            lines[index] = rewritten
            if is_block:
                block_indent = current_field_indent
                field_match = re.match(
                    r"^[ \t]*(?P<key>command|exec):",
                    lines[index],
                )
                field_key = field_match.group("key") if field_match else "command"
                block_index = index + 1
                while block_index < hooks_end:
                    block_line = lines[block_index]
                    if block_line.strip() and len(block_line) - len(block_line.lstrip()) <= block_indent:
                        break
                    newline = "\r\n" if block_line.endswith("\r\n") else "\n" if block_line.endswith("\n") else ""
                    content = block_line[:len(block_line) - len(block_line.lstrip())]
                    command = block_line[len(content):].removesuffix(newline)
                    if field_key == "exec":
                        rewritten_command = rewrite_plugin_hook_executable(command)
                    else:
                        rewritten_command = rewrite_plugin_hook_path(command)
                    if rewritten_command != command:
                        lines[block_index] = content + rewritten_command + newline
                    block_index += 1
                index = block_index
                continue
        index += 1

    return "".join(lines)


def remove_plugin_wide_hook_config(plugin_root: Path, dry_run: bool) -> None:
    """Remove obsolete hook configuration files so hooks remain agent-scoped."""
    targets = (
        plugin_root / "com.github.copilot" / "hooks" / "hooks.json",
        plugin_root / "hooks.json",
    )
    for target in targets:
        if not target.is_file():
            continue
        label = target.relative_to(plugin_root).as_posix()
        if dry_run:
            print(f"REMOVE {label} (hooks now live in agent frontmatter)")
        else:
            target.unlink()
            print(f"REMOVED {label} (hooks now live in agent frontmatter)")


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
) -> str:
    """Build the full plugin agent-file content from current source content.

    This is a full rebuild, not an incremental merge: every call recomputes
    the entire output from the two inputs currently on disk, so any edit,
    addition, or removal in either source file is reflected on the very next
    sync run. Nothing from a previous plugin copy is reused or preserved.

    Three things happen to agent_text before it's used:
      1. Agent-scoped hooks are retained in place; only bundled hook script
         paths are rewritten to use the plugin root.
      2. If ``version`` is supplied, it is injected into frontmatter
         (description, argument-hint) and title via inject_agent_version().
      3. instructions_text (copilot-instructions.md) is appended as a
         clearly labeled section, since VS Code Agent Plugins do not support
         shipping that file standalone alongside an agent.
    If instructions_text is empty (e.g. the source file was deleted), the
    appended section is simply omitted.
    """
    rewritten_agent = rewrite_agent_hook_block(agent_text)
    if _agent_hook_record_count(agent_text) != _agent_hook_record_count(rewritten_agent):
        raise ValueError("Rewriting hook paths changed the agent's hook entry count")
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

    Obsolete plugin-wide hook configurations are removed; hooks stay in the
    agent's frontmatter.

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
    merged = build_merged_agent_content(
        agent_text,
        instructions_text,
        version,
    )

    remove_plugin_wide_hook_config(plugin_root, dry_run)

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
    """Package dormant skills as commands, plus scripts, hooks, and active skills.

    Copies new or changed files, removes stale managed files, and skips
    unchanged files plus excluded directories. SKILL.md files under the source
    skills-dormant/ directory become explicit Copilot commands, while active
    skills remain under the plugin root's skills/ directory.
    """
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source .github path not found: {source_root}")
    if not plugin_root.is_dir():
        raise FileNotFoundError(f"Plugin root not found: {plugin_root}")

    validate_source_layout(source_root)
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
        if not dry_run:
            target_path.parent.mkdir(parents=True, exist_ok=True)

        copy_needed = True
        if target_path.is_file():
            if is_command_source(relative):
                copy_needed = plugin_command_content(source_path, relative) != target_path.read_text(encoding="utf-8")
            else:
                copy_needed = sha256sum(source_path) != sha256sum(target_path)

        if not copy_needed:
            print(f"SKIP   {target_relative.as_posix()}")
            skipped += 1
            continue

        if dry_run:
            print(f"COPY   {target_relative.as_posix()}")
        else:
            if is_command_source(relative):
                target_path.write_text(
                    plugin_command_content(source_path, relative),
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

    validate_source_layout(source_root)
    if not args.no_bump:
        version = bump_versions(repo_root, args.bump, args.dry_run)
    else:
        version = get_canonical_version(repo_root)
    sync_readme(repo_root, plugin_root, args.dry_run)
    sync_agent_file(source_root, plugin_root, version, args.dry_run)
    return sync(source_root, plugin_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
