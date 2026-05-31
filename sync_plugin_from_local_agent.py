from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path


MANAGED_ENTRIES = (
    "agents",
    "copilot-instructions.md",
    "hooks",
    "prompts",
    "scripts",
    "skills",
)

EXCLUDED_SEGMENTS = {
    "docs",
    "temp",
    "__pycache__",
}

PRESERVED_PLUGIN_FILES = {
    Path(".claude-plugin/plugin.json"),
    Path("hooks/hooks.json"),
    Path("agents/ENSDF-Agent.agent.md"),
}

# Files in the source .github tree that are workspace-only and must not be copied to the plugin
SOURCE_EXCLUDED_FILES = {
    Path("hooks/block-root-file-creation.json"),
}

# JSON files that carry the plugin version — updated by bump_versions()
VERSION_FILES = [
    Path("plugins/ensdf-agent/.claude-plugin/plugin.json"),  # canonical source
    Path(".claude-plugin/marketplace.json"),
    Path(".github/plugin/marketplace.json"),
]


def bump_versions(repo_root: Path, bump: str, dry_run: bool) -> None:
    """Bump the semantic version across all VERSION_FILES using the first file as canonical."""
    canonical = repo_root / VERSION_FILES[0]
    text = canonical.read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"', text)
    if not match:
        raise ValueError(f"Cannot find version field in {canonical}")
    old = match.group(1)
    major, minor, patch = (int(x) for x in old.split("."))
    if bump == "major":
        major, minor, patch = major + 1, 0, 0
    elif bump == "minor":
        major, minor, patch = major, minor + 1, 0
    else:
        patch += 1
    new = f"{major}.{minor}.{patch}"

    print(f"Version bump ({bump}): {old} → {new}")
    for rel in VERSION_FILES:
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
    return any(part in EXCLUDED_SEGMENTS for part in relative_path.parts)


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_managed_source_files(source_root: Path) -> list[Path]:
    files: list[Path] = []
    for entry in MANAGED_ENTRIES:
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
    for entry in MANAGED_ENTRIES:
        full_path = plugin_root / entry
        if not full_path.exists():
            continue

        if full_path.is_dir():
            for child in full_path.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(plugin_root)
                if not is_excluded(relative) and relative not in PRESERVED_PLUGIN_FILES:
                    files.append(relative)
            continue

        relative_file = normalize_relative_path(entry)
        if not is_excluded(relative_file) and relative_file not in PRESERVED_PLUGIN_FILES:
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
        if path.is_dir() and path.name in EXCLUDED_SEGMENTS
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


def sync(source_root: Path, plugin_root: Path, dry_run: bool) -> int:
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

    for relative in source_files:
        if relative in PRESERVED_PLUGIN_FILES or relative in SOURCE_EXCLUDED_FILES:
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
        help="Path to the local agent .github directory.",
    )
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parent / "plugins" / "ensdf-agent"),
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
        default=str(Path(__file__).resolve().parent),
        help="Repository root used for README sync and version bumping (default: script directory).",
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
    return sync(source_root, plugin_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())