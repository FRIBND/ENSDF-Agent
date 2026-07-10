"""
Regenerates the plugins/ensdf-agent/ payload from the local ENSDF workspace
(default source: D:/X/ND/ENSDF/.github).

Run order, see main():
  1. bump_versions()   - bump the version string in every file in version_files.
  2. sync_readme()     - copy repo-root README.md into the plugin if it changed.
  3. sync_agent_file() - rebuild agents/ENSDF-Agent.agent.md from two source
                         files: agents/ENSDF-Agent.agent.md (its `hooks:`
                         frontmatter is stripped, since VS Code Agent Plugins
                         don't support agent-scoped hooks - see hooks/hooks.json
                         instead) and copilot-instructions.md, appended as a
                         labeled section (it can't ship on its own). The output
                         is fully rebuilt every run from whatever is currently
                         on disk, so any edit to either source file is picked
                         up on the next sync. See build_merged_agent_content().
  4. sync()            - mirror-copy the rest of managed_entries (hooks/,
                         prompts/, scripts/, skills/): copy new/changed files,
                         remove files whose source no longer exists, skip
                         unchanged/preserved/excluded files (see below).

Two file sets are never copied or removed by sync()'s generic loop:
  - preserved_plugin_files: plugin-only files with no source equivalent
    (e.g. .claude-plugin/plugin.json, hooks/hooks.json) - edited by hand
    directly in the plugin.
  - source_excluded_files: source files that exist upstream but must not be
    copied as-is, either because they're workspace-only
    (hooks/block-root-file-creation.json) or because a dedicated step handles
    them instead (agents/ENSDF-Agent.agent.md, via sync_agent_file()).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path


# Top-level entries under the source .github/ dir (and, mirrored, under the
# plugin root) that sync() plain-copies 1:1. Anything not listed here is
# ignored by the sync loop (e.g. docs/, temp/ at the source root).
managed_entries = (
    "agents",
    "hooks",
    "prompts",
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

# Plugin-only files with no source-repo equivalent. sync() never copies over
# or deletes these; they're maintained by hand in the plugin payload.
preserved_plugin_files = {
    Path(".claude-plugin/plugin.json"),
    Path("hooks/hooks.json"),
}

# Source files that live under managed_entries but are skipped by the generic
# copy loop in sync(): block-root-file-creation.json is workspace-only, and
# agents/ENSDF-Agent.agent.md is handled instead by sync_agent_file() (see
# module docstring above).
source_excluded_files = {
    Path("hooks/block-root-file-creation.json"),
    Path("agents/ENSDF-Agent.agent.md"),
}

# JSON files that carry the plugin version, updated by bump_versions(). The
# first entry is canonical: its "version" value is read as the old version
# before bumping, then the new version is written to every file in this list.
version_files = [
    Path("plugins/ensdf-agent/.claude-plugin/plugin.json"),  # canonical source
    Path(".claude-plugin/marketplace.json"),
    Path(".github/plugin/marketplace.json"),
]


def bump_versions(repo_root: Path, bump: str, dry_run: bool) -> None:
    """Bump the plugin version using single-digit patch rollover."""
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


def normalize_relative_path(path: Path | str) -> Path:
    return Path(path)


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
    for entry in managed_entries:
        full_path = plugin_root / entry
        if not full_path.exists():
            continue

        if full_path.is_dir():
            for child in full_path.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(plugin_root)
                if not is_excluded(relative) and relative not in preserved_plugin_files:
                    files.append(relative)
            continue

        relative_file = normalize_relative_path(entry)
        if not is_excluded(relative_file) and relative_file not in preserved_plugin_files:
            files.append(relative_file)

    return sorted(set(files))


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


def strip_agent_hooks_block(agent_text: str) -> str:
    """Remove the agent-scoped ``hooks:`` frontmatter block from an agent file.

    VS Code Agent Plugins do not support agent-scoped hooks — plugin hooks fire
    for any active agent via hooks/hooks.json instead. The workspace-only
    source agent file carries a ``hooks:`` key in its YAML frontmatter; this
    strips that key (and its nested mapping) while leaving every other
    frontmatter key and the document body untouched.

    Implementation note: this does a line-based scan, not real YAML parsing.
    It finds the line ``hooks:`` at column 0 inside the frontmatter, then skips
    every following line that is blank or indented (i.e. part of the nested
    mapping), stopping at the first unindented line (a new top-level key) or
    the closing ``---`` fence — whichever comes first.
    """
    lines = agent_text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return agent_text  # no frontmatter fence at all — nothing to strip

    # Locate the closing '---' fence that ends the frontmatter block.
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return agent_text  # malformed/no closing fence — leave text as-is

    frontmatter = lines[1:end_idx]
    remainder = lines[end_idx:]  # closing '---' line onward (unchanged)

    filtered: list[str] = []
    skipping = False
    for line in frontmatter:
        if not skipping:
            if line.rstrip("\n") == "hooks:":
                skipping = True  # start of the block to drop
                continue
            filtered.append(line)
        else:
            # Still inside the hooks: mapping while lines are blank or indented.
            if line.strip() == "" or line[:1] in (" ", "\t"):
                continue
            skipping = False  # hit a new unindented key — block is over
            filtered.append(line)

    return "".join(["---\n", *filtered, *remainder])


def build_merged_agent_content(agent_text: str, instructions_text: str) -> str:
    """Build the full plugin agent-file content from current source content.

    This is a full rebuild, not an incremental merge: every call recomputes
    the entire output from the two inputs currently on disk, so any edit,
    addition, or removal in either source file is reflected on the very next
    sync run. Nothing from a previous plugin copy is reused or preserved.

    Two things happen to agent_text before it's used:
      1. Its agent-scoped ``hooks:`` frontmatter block is stripped via
         strip_agent_hooks_block() — VS Code Agent Plugins don't support
         agent-scoped hooks, so that block would be dead weight in the
         plugin; equivalent hooks live in hooks/hooks.json instead.
      2. instructions_text (copilot-instructions.md) is appended as a
         clearly labeled section, since VS Code Agent Plugins do not support
         shipping that file standalone alongside an agent.
    If instructions_text is empty (e.g. the source file was deleted), the
    appended section is simply omitted.
    """
    stripped_agent = strip_agent_hooks_block(agent_text).rstrip("\n")
    instructions_body = instructions_text.strip("\n")

    sections = [stripped_agent]
    if instructions_body:
        sections.append(
            "\n---\n\n"
            "## Workspace Copilot Instructions\n\n"
            "*(Concatenated from `copilot-instructions.md`.)*\n\n"
            + instructions_body
        )
    return "\n".join(sections) + "\n"


def sync_agent_file(source_root: Path, plugin_root: Path, dry_run: bool) -> None:
    """Regenerate the plugin's agent file from the current source files.

    Reads source agents/ENSDF-Agent.agent.md + copilot-instructions.md fresh
    every run and rebuilds the merged output via build_merged_agent_content(),
    which also strips the source agent's agent-scoped `hooks:` frontmatter
    block (see strip_agent_hooks_block()) and appends the instructions file as
    a labeled section. The result is compared verbatim (full-text equality)
    against the existing plugin file to decide COPIED/SKIP; there is no
    partial/section-level patch.

    Also deletes any stale standalone copilot-instructions.md left in the
    plugin payload, since that file must never ship on its own.
    """
    source_agent = source_root / "agents" / "ENSDF-Agent.agent.md"
    source_instructions = source_root / "copilot-instructions.md"
    target_agent = plugin_root / "agents" / "ENSDF-Agent.agent.md"
    target_instructions = plugin_root / "copilot-instructions.md"

    if not source_agent.is_file():
        print("SKIP   agents/ENSDF-Agent.agent.md (source not found)")
        return

    agent_text = source_agent.read_text(encoding="utf-8")
    instructions_text = (
        source_instructions.read_text(encoding="utf-8")
        if source_instructions.is_file()
        else ""
    )
    merged = build_merged_agent_content(agent_text, instructions_text)

    existing = target_agent.read_text(encoding="utf-8") if target_agent.is_file() else None
    if existing == merged:
        print("SKIP   agents/ENSDF-Agent.agent.md (merged, unchanged)")
    elif dry_run:
        print("COPY   agents/ENSDF-Agent.agent.md (merged with copilot-instructions.md)")
    else:
        target_agent.parent.mkdir(parents=True, exist_ok=True)
        target_agent.write_text(merged, encoding="utf-8")
        print("COPIED agents/ENSDF-Agent.agent.md (merged with copilot-instructions.md)")

    # copilot-instructions.md must not ship standalone — VS Code Agent Plugins
    # ignore it; remove any stale copy left in the plugin payload.
    if target_instructions.is_file():
        if dry_run:
            print("REMOVE copilot-instructions.md (merged into agents/ENSDF-Agent.agent.md)")
        else:
            target_instructions.unlink()
            print("REMOVED copilot-instructions.md (merged into agents/ENSDF-Agent.agent.md)")


def sync(source_root: Path, plugin_root: Path, dry_run: bool) -> int:
    """Mirror-copy managed_entries (except agents/ENSDF-Agent.agent.md, handled
    separately by sync_agent_file) from source_root into plugin_root:
      - copy any source file that's new or changed (sha256 mismatch)
      - skip source files that are identical, preserved, or excluded
      - remove any plugin file under managed_entries that no longer exists
        in source (unless it's a preserved_plugin_files entry)
      - remove any leftover excluded_segments directories in the plugin
    """
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source .github path not found: {source_root}")
    if not plugin_root.is_dir():
        raise FileNotFoundError(f"Plugin root not found: {plugin_root}")

    source_files = iter_managed_source_files(source_root)
    target_files = iter_managed_target_files(plugin_root)
    source_set = set(source_files)

    copied = 0
    removed = 0
    skipped = 0

    # Pass 1: copy every source file that's missing or changed in the plugin.
    for relative in source_files:
        if relative in preserved_plugin_files or relative in source_excluded_files:
            print(f"SKIP   {relative.as_posix()} (preserved/excluded)")
            skipped += 1
            continue
        source_path = source_root / relative
        target_path = plugin_root / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)

        copy_needed = True
        if target_path.is_file() and sha256sum(source_path) == sha256sum(target_path):
            copy_needed = False

        if not copy_needed:
            print(f"SKIP   {relative.as_posix()}")
            skipped += 1
            continue

        if dry_run:
            print(f"COPY   {relative.as_posix()}")
        else:
            shutil.copy2(source_path, target_path)
            print(f"COPIED {relative.as_posix()}")
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
        description=(
            "Sync the publishable ENSDF-Agent plugin payload from a local ENSDF .github directory, "
            "excluding docs/temp/cache content and preserving plugin-specific packaging files."
        )
    )
    parser.add_argument(
        "--source-github-path",
        default=r"D:\X\ND\ENSDF\.github",
        help="Path to the local ENSDF .github directory used as the sync source.",
    )
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parents[1] / "plugins" / "ensdf-agent"),
        help="Path to the plugin payload root.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview copy/remove actions without changing files.",
    )
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
        metavar="LEVEL",
        help="Version bump level applied before syncing: patch (default), minor, or major.",
    )
    parser.add_argument(
        "--no-bump",
        action="store_true",
        help="Skip version bumping.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root used for README sync and version bumping (default: repo root).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = Path(args.source_github_path).resolve()
    plugin_root = Path(args.plugin_root).resolve()
    repo_root = Path(args.repo_root).resolve()
    if not args.no_bump:
        bump_versions(repo_root, args.bump, args.dry_run)
    sync_readme(repo_root, plugin_root, args.dry_run)
    sync_agent_file(source_root, plugin_root, args.dry_run)
    return sync(source_root, plugin_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
