"""
Regenerates the plugins/ensdf-agent/ payload from the local ENSDF workspace
(default source: D:/X/ND/ENSDF/.github).

Run from the repository root with: python dev/sync_plugin_from_local_agent.py

Run order, see main():
    1. bump_versions()     - bump manifests and return canonical version.
    2. sync_readme()       - copy repo README if changed.
    3. sync_agent_file()   - generate the single agent in
                             com.github.copilot/agents/ from source; retain
                             agent-scoped hooks.
    4. sync()              - mirror skills/, skills-dormant/, scripts/, and
                             hooks/scripts/, adapting bundled references.

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


managed_entries = (
    "scripts",
    "skills",
    "skills-dormant",
    "hooks/scripts",
)
managed_plugin_entries = (
    "scripts",
    "skills",
    "skills-dormant",
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
    Path(".github/plugin/marketplace.json"),
]

PDF_SOURCE_MAIN_SHA256 = "36c91c8c52106757652314a51e98aa937ad7cbbcae092a980a3ae77fe887678b"
PORTABLE_PDF_MAIN = '''
def main():
    import argparse
    import fnmatch
    import tempfile

    parser = argparse.ArgumentParser(description="Convert workspace ENSDF files to PDF.")
    parser.add_argument("input", help="ENSDF file, dataset name, element, or glob")
    parser.add_argument("--jar", default=os.environ.get("ENSDF_NDS_JAR"),
                        help="McMaster-MSU Java NDS JAR (or set ENSDF_NDS_JAR)")
    parser.add_argument("--open", action="store_true", help="Open generated PDFs")
    parser.add_argument("--system", action="store_true", help="Use the system PDF viewer")
    args = parser.parse_args()
    workspace = Path.cwd()
    if args.jar:
        jar = Path(args.jar).expanduser().resolve()
        if not jar.is_file():
            parser.error(f"Java NDS JAR not found: {jar}")
    else:
        jars = sorted(workspace.rglob("McMaster_MSU_JAVA_NDS_v*.jar"))
        if len(jars) != 1:
            parser.error("Provide the Java NDS JAR using --jar or ENSDF_NDS_JAR.")
        jar = jars[0].resolve()
    if not shutil.which("java"):
        parser.error("Java executable not found on PATH.")
    supplied = Path(args.input).expanduser()
    if supplied.is_file():
        files = [supplied.resolve()]
    else:
        pattern = args.input.replace("\\\\", "/")
        if not pattern.lower().endswith(".ens"):
            pattern += "*.ens" if pattern.isalpha() else ".ens"
        files = sorted(
            path.resolve() for path in workspace.rglob("*.ens")
            if fnmatch.fnmatch(path.name.casefold(), pattern.casefold())
            or fnmatch.fnmatch(path.relative_to(workspace).as_posix().casefold(), pattern.casefold())
        )
    if not files:
        parser.error(f"No ENSDF files match: {args.input}")
    destinations = []
    for path in files:
        parent = path.parent.parent if path.parent.name.lower() == "new" else path.parent
        destinations.append(parent / "pdf" / (path.stem + ".pdf"))
    if len(set(destinations)) != len(destinations):
        parser.error("Selected files would produce duplicate PDF paths.")
    existing = [path for path in destinations if path.exists()]
    if existing:
        parser.error(f"PDF already exists; refusing to overwrite: {existing[0]}")
    with tempfile.TemporaryDirectory(prefix="ensdf-pdf-") as temp:
        generated = []
        for index, (source, destination) in enumerate(zip(files, destinations)):
            staging = Path(temp) / str(index)
            staging.mkdir()
            pdf = run_java(source, str(jar), staging)
            if pdf is None:
                raise SystemExit(f"PDF conversion failed: {source}")
            generated.append((pdf, destination))
        for pdf, destination in generated:
            destination.parent.mkdir(parents=True, exist_ok=True)
            move_all_pdfs([(pdf, destination)], destination.parent)
            if not destination.is_file():
                raise SystemExit(f"Could not move generated PDF to {destination}")
            if args.open:
                if not args.system and shutil.which("code"):
                    subprocess.run(["code", str(destination)], check=True)
                elif os.name == "nt":
                    os.startfile(str(destination))
                else:
                    import sys
                    subprocess.run(["open" if sys.platform == "darwin" else "xdg-open",
                                    str(destination)], check=True)


if __name__ == "__main__":
    main()
'''


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

    updates = {}
    for rel in version_files:
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(r'"version"\s*:\s*"[^"]*"', f'"version": "{new}"', text)
        if not count:
            raise ValueError(f"Cannot find version field in {path}")
        updates[rel] = updated

    print(f"Version bump ({bump}): {old} → {new}")
    for rel in version_files:
        label = rel.as_posix()
        if dry_run:
            print(f"  WOULD UPDATE {label}")
        else:
            (repo_root / rel).write_text(updates[rel], encoding="utf-8")
            print(f"  UPDATED {label}")
    print()
    return new


def normalize_relative_path(path: Path | str) -> Path:
    return Path(path)


def plugin_relative_path(path: Path) -> Path:
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


def rewrite_markdown_paths(text: str, target_relative: Path) -> str:
    """Preserve authored markdown, except a workstation-specific tool path."""
    if target_relative == Path("skills-dormant/ens2pdf/SKILL.md"):
        text = text.replace("D:\\X\\ND\\McMaster-MSU-Java-NDS\\", "${ENSDF_NDS_JAR}")
    return text


def rewrite_hook_script(text: str, relative: Path) -> str:
    """Bind workspace state to the hook event, not the installed script path."""
    name = relative.name
    if relative.parts[:2] != ("hooks", "scripts") or name not in {
        "block-root-file-creation.py", "guard_ens_edit.py", "verify_ens_edit.py"
    }:
        return text

    old = (
        'def workspace_root():\n'
        '    return os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))'
    )
    new = 'def workspace_root(cwd):\n    return os.path.realpath(os.path.abspath(cwd))'
    if text.count(old) != 1:
        raise ValueError(f"Cannot adapt workspace root in {relative}: source changed")
    text = text.replace(old, new)
    if name == "block-root-file-creation.py":
        old = "    root = workspace_root()\n    cwd = working_directory(hook_input)"
        new = "    cwd = working_directory(hook_input)\n    root = workspace_root(cwd)"
    elif name == "guard_ens_edit.py":
        old = 'state_path = os.path.join(workspace_root(), ".github", "temp", "ens_guard", "state.json")'
        new = 'state_path = os.path.join(workspace_root(root), ".github", "temp", "ens_guard", "state.json")'
    else:
        old = 'state_path = os.path.join(workspace_root(), ".github", "temp", "ens_guard", "state.json")'
        new = 'state_path = os.path.join(workspace_root(cwd), ".github", "temp", "ens_guard", "state.json")'
    if text.count(old) != 1:
        raise ValueError(f"Cannot adapt workspace state in {relative}: source changed")
    text = text.replace(old, new)
    if name == "verify_ens_edit.py":
        old = '''    plugin_root = os.environ.get("PLUGIN_ROOT", "")
    if plugin_root:
        candidate = os.path.join(plugin_root, "scripts", "ensdf_1line_ruler.py")
        if os.path.isfile(candidate):
            return candidate
    candidate = os.path.join(workspace_root(), ".github", "scripts", "ensdf_1line_ruler.py")'''
        new = '''    plugin_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    candidate = os.path.join(plugin_root, "scripts", "ensdf_1line_ruler.py")
    if os.path.isfile(candidate):
        return candidate
    candidate = os.path.join(workspace_root(payload.get("cwd") or os.getcwd()), ".github", "scripts", "ensdf_1line_ruler.py")'''
        if text.count(old) != 1:
            raise ValueError(f"Cannot adapt bundled ruler lookup in {relative}: source changed")
        text = text.replace(old, new)
        old = """            '  3. Re-run: python .github/scripts/ensdf_1line_ruler.py --line "<fixed line>"\\n'"""
        new = '''            f"  3. Re-run the ENSDF ruler at {ruler_script} on the fixed line, using a shell-quoted path.\\n"'''
        if text.count(old) != 1:
            raise ValueError(f"Cannot adapt ruler guidance in {relative}: source changed")
        text = text.replace(old, new)
    return text


def rewrite_bundled_script(text: str, relative: Path) -> str:
    if relative == Path("scripts/ens2pdf.py"):
        start = text.find("def main():\n")
        if start < 0:
            raise ValueError(f"Cannot adapt PDF conversion entry point in {relative}")
        source_main = text[start:]
        # Reject changes to the source entry point rather than silently discarding them.
        if hashlib.sha256(source_main.encode("utf-8")).hexdigest() != PDF_SOURCE_MAIN_SHA256:
            raise ValueError(f"PDF conversion entry point changed; update the portable adapter for {relative}")
        text = text[:start]
        text = re.sub(r"\(D:/X/ND/Files\)", "(the staging directory)", text)
        text = text.replace("FILES = None", "FILES: list[str] | None = None", 1)
        text, count = re.subn(
            r'(?m)^ENSDF_ROOT = .*$|^OUTPUT_DIR = .*$|^JAR_GLOB\s+= .*$',
            lambda match: {
                "ENSDF_ROOT": 'ENSDF_ROOT = str(Path.cwd())',
                "OUTPUT_DIR": 'OUTPUT_DIR = str(Path.cwd())',
                "JAR_GLOB": 'JAR_GLOB = os.environ.get("ENSDF_NDS_JAR", "**/McMaster_MSU_JAVA_NDS_v*.jar")',
            }[match.group().split("=")[0].strip()],
            text,
        )
        if count != 3:
            raise ValueError(f"Cannot adapt PDF tool paths in {relative}")
        text += PORTABLE_PDF_MAIN
    elif relative == Path("scripts/compare_line_metrics.py"):
        text, count = re.subn(r"(?m)^DEFAULT_(?:OLD|NEW)_FILE = .*?$", "", text)
        if count != 2:
            raise ValueError(f"Cannot adapt comparison defaults in {relative}")
        text, count = re.subn(
            r'        nargs="\?",\n        default=DEFAULT_(?:OLD|NEW)_FILE,\n'
            r'        help="Path to (old/original|new/edited) file \(optional; defaults to DEFAULT_(?:OLD|NEW)_FILE in this script\)",',
            lambda match: f'        help="Path to {match.group(1)} file",',
            text,
        )
        if count != 2:
            raise ValueError(f"Cannot adapt comparison arguments in {relative}")
        old = 'def compare_object_counts(old_path: Path, new_path: Path) -> tuple[int, int, int, str]:\n'
        new = old + (
            '    import shutil\n'
            '    if not shutil.which("powershell"):\n'
            '        total, removed, added = powershell_style_counts(read_lines(old_path), read_lines(new_path))\n'
            '        return total, removed, added, "CounterFallback (PowerShell unavailable)"\n'
        )
        if text.count(old) != 1:
            raise ValueError(f"Cannot adapt comparison execution in {relative}")
        text = text.replace(old, new)
    elif relative == Path("scripts/Java_FormatCheck.py"):
        text, count = re.subn(
            r'    candidates = glob\.glob\(r"[^"\n]+"\)',
            '    configured = os.environ.get("ENSDF_FORMATCHECK_JAR")\n'
            '    candidates = [configured] if configured else glob.glob("**/FormatCheck_*.jar", recursive=True)',
            text, count=1,
        )
        if count != 1:
            raise ValueError(f"Cannot adapt FormatCheck JAR discovery in {relative}")
        text, count = re.subn(
            r'(?m)^FILES_DIR = .*$',
            'FILES_DIR = os.environ.get("ENSDF_FORMATCHECK_OUTPUT_DIR", str(Path.cwd() / ".github" / "temp" / "formatcheck"))',
            text,
        )
        if count != 1:
            raise ValueError(f"Cannot adapt FormatCheck output in {relative}")
        text = re.sub(r"(?m)^    Generates .*formatcheck\.fmt$", "    Generates a formatcheck.fmt report in FILES_DIR.", text)
        text = re.sub(r'(?m)^        print\("Error: Could not find FormatCheck jar\..*$', '        print("Error: Set ENSDF_FORMATCHECK_JAR to an existing FormatCheck JAR, or place it in the workspace.")', text)
        text = re.sub(r'(?m)^        print\("  - Output is written to .*$', '        print(f"  - Output is written to {OUTPUT_FILE}")', text)
        text = text.replace("python .github/Java_FormatCheck.py", "python Java_FormatCheck.py")
    elif relative == Path("scripts/column_calibrate.py"):
        text = text.replace(
            'print("  Run: python .github/fix_ri_positioning.py \\"filename.ens\\"")',
            'print("  Run the bundled fix_ri_m_columns.py on the affected file.")',
        )
    elif relative == Path("scripts/check_gamma_ordering.py"):
        text = text.replace(".github/check_gamma_ordering.py", "check_gamma_ordering.py")
    elif relative == Path("scripts/scan_editorial_review.py"):
        text = text.replace(".github/scripts/scan_editorial_review.py", "scan_editorial_review.py")
    return text


def validate_portable_text(text: str, relative: Path) -> None:
    """Reject machine-specific paths instead of publishing broken commands."""
    for line_number, line in enumerate(text.splitlines(), 1):
        if re.search(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/(?:home|Users)/)", line):
            raise ValueError(f"Machine-specific path in {relative}:{line_number}: {line.strip()}")
        if "<plugin-root>" in line:
            raise ValueError(f"Unresolved plugin-root placeholder in {relative}:{line_number}")


def workspace_dependencies(source_root: Path) -> list[str]:
    """Find workspace-relative references in authored instructions."""
    references: set[str] = set()
    pattern = re.compile(
        r"\.github[\\/](?:(?:scripts|agents|skills|skills-dormant)[\\/][\w./\\-]+"
        r"|copilot-instructions\.md)"
    )
    files = [
        source_root / "agents" / "ENSDF-Agent.agent.md",
        source_root / "copilot-instructions.md",
    ]
    files.extend(
        source_root / relative
        for relative in iter_managed_source_files(source_root)
        if relative.parts[0] in {"skills", "skills-dormant"} and relative.suffix.lower() == ".md"
    )
    for path in files:
        if path.is_file():
            references.update(
                match.group(0).replace("\\", "/").rstrip(".")
                for match in pattern.finditer(path.read_text(encoding="utf-8"))
            )
    return sorted(references)


def build_managed_content(source_root: Path, relative: Path) -> str | None:
    source_path = source_root / relative
    target_relative = plugin_relative_path(relative)
    if relative.suffix.lower() == ".md":
        original = source_path.read_text(encoding="utf-8")
        text = rewrite_markdown_paths(original, target_relative)
        validate_portable_text(text, relative)
        if text == original:
            return None
    elif relative.parts[:2] == ("hooks", "scripts") and relative.suffix == ".py":
        text = rewrite_hook_script(source_path.read_text(encoding="utf-8"), relative)
    elif relative.suffix == ".py" and relative.parts[0] == "scripts":
        text = rewrite_bundled_script(source_path.read_text(encoding="utf-8"), relative)
    elif relative.suffix.lower() in {".py", ".sh", ".ps1", ".js", ".cjs", ".mjs", ".json", ".yaml", ".yml", ".toml"}:
        text = source_path.read_text(encoding="utf-8")
    else:
        return None
    validate_portable_text(text, relative)
    return text


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
        return f'"{rewritten}"'

    return source_path.sub(replace, command)


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
        r"^(?P<indent>[ \t]*)(?P<key>command|exec|cwd|bash|powershell|windows|linux|osx):"
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
    if key in {"exec", "cwd"}:
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
    args_indent = None
    env_indent = None
    index = hooks_start + 1
    while index < hooks_end:
        line = lines[index]
        indent = len(line) - len(line.lstrip())
        if args_indent is not None and line.strip() and indent <= args_indent:
            args_indent = None
        if env_indent is not None and line.strip() and indent <= env_indent:
            env_indent = None
        item_match = re.match(r"^(?P<indent>[ \t]*)-\s+type:", lines[index])
        if item_match:
            current_field_indent = len(item_match.group("indent")) + 2

        if current_field_indent is not None:
            env_match = re.match(r"^(?P<indent>[ \t]*)env:[ \t]*(?:#.*)?(?:\r?\n)?$", line)
            if env_match and len(env_match.group("indent")) == current_field_indent:
                env_indent = current_field_indent
                index += 1
                continue
            env_value = re.match(
                r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z_][A-Za-z0-9_]*):"
                r"(?P<spacing>[ \t]*)(?P<value>.*?)(?P<newline>\r?\n)?$",
                line,
            )
            if env_indent is not None and env_value and len(env_value.group("indent")) > env_indent:
                raw = env_value.group("value")
                if ".github" in raw and "hooks" in raw:
                    decoded = _decode_hook_string_scalar(raw)
                    if decoded is None:
                        raise ValueError(f"Unsupported block scalar in hook environment: {line!r}")
                    value, suffix = decoded
                    rewritten = rewrite_plugin_hook_executable(value)
                    if rewritten != value:
                        lines[index] = (
                            f"{env_value.group('indent')}{env_value.group('key')}:"
                            f"{env_value.group('spacing')}{json.dumps(rewritten)}"
                            f"{suffix}{env_value.group('newline') or ''}"
                        )
                index += 1
                continue
            args_match = re.match(
                r"^(?P<indent>[ \t]*)args:[ \t]*(?P<value>.*?)(?P<newline>\r?\n)?$",
                line,
            )
            if args_match and len(args_match.group("indent")) == current_field_indent:
                raw = args_match.group("value")
                if not raw.strip() or raw.lstrip().startswith("#"):
                    args_indent = current_field_indent
                elif ".github" in raw:
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"Unsupported hook args containing a bundled path: {raw!r}") from error
                    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                        raise ValueError(f"Hook args must be strings: {raw!r}")
                    rewritten_args = [rewrite_plugin_hook_executable(arg) for arg in args]
                    lines[index] = (
                        f"{args_match.group('indent')}args: {json.dumps(rewritten_args)}"
                        f"{args_match.group('newline') or ''}"
                    )
                index += 1
                continue
            arg_match = re.match(
                r"^(?P<indent>[ \t]*)-[ \t]+(?P<value>.*?)(?P<newline>\r?\n)?$",
                line,
            )
            if args_indent is not None and arg_match and len(arg_match.group("indent")) > args_indent:
                decoded = _decode_hook_string_scalar(arg_match.group("value"))
                if decoded is None:
                    raise ValueError(f"Unsupported block scalar in hook args: {line!r}")
                value, suffix = decoded
                rewritten = rewrite_plugin_hook_executable(value)
                if rewritten != value:
                    lines[index] = (
                        f"{arg_match.group('indent')}- {json.dumps(rewritten)}"
                        f"{suffix}{arg_match.group('newline') or ''}"
                    )
                index += 1
                continue
            rewritten, is_block = _rewrite_hook_command_line(
                lines[index],
                current_field_indent,
            )
            lines[index] = rewritten
            if is_block:
                block_indent = current_field_indent
                field_match = re.match(
                    r"^[ \t]*(?P<key>command|exec|cwd|bash|powershell|windows|linux|osx):",
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
                    if field_key in {"exec", "cwd"}:
                        rewritten_command = rewrite_plugin_hook_executable(command)
                    else:
                        rewritten_command = rewrite_plugin_hook_path(command)
                    if rewritten_command != command:
                        lines[block_index] = content + rewritten_command + newline
                    block_index += 1
                index = block_index
                continue
        index += 1

    rewritten_text = "".join(lines)
    remaining = "".join(lines[hooks_start:hooks_end])
    if re.search(r"\.github[\\/]+hooks[\\/]", remaining):
        raise ValueError("Unsupported source hook path remains in agent frontmatter")
    return rewritten_text


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
) -> str:
    """Build the full plugin agent-file content from current source content.

    This is a full rebuild, not an incremental merge: every call recomputes
    the entire output from the two inputs currently on disk, so any edit,
    addition, or removal in either source file is reflected on the very next
    sync run. Nothing from a previous plugin copy is reused or preserved.

    Three things happen to agent_text before it's used:
      1. Agent-scoped hooks are retained in place; only bundled hook script
         paths are rewritten to use the plugin root.
      2. instructions_text (copilot-instructions.md) is appended as a
         clearly labeled section, since VS Code Agent Plugins do not support
         shipping that file standalone alongside an agent.
    If instructions_text is empty (e.g. the source file was deleted), the
    appended section is simply omitted.
    """
    rewritten_agent = rewrite_agent_hook_block(agent_text)
    if _agent_hook_record_count(agent_text) != _agent_hook_record_count(rewritten_agent):
        raise ValueError("Rewriting hook paths changed the agent's hook entry count")
    rewritten_agent = rewritten_agent.rstrip("\n")
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
    dry_run: bool = False,
) -> None:
    """Generate the single Copilot agent and remove its legacy duplicate.

    Reads source agents/ENSDF-Agent.agent.md + copilot-instructions.md fresh
    every run and rebuilds the merged output via build_merged_agent_content(),
    which rewrites and retains agent-scoped hooks and appends the instructions
    file as a labeled section. The result is compared
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
    """Mirror managed files, adapting plugin-specific references."""
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
    generated: dict[Path, str] = {}
    for relative in source_files:
        content = build_managed_content(source_root, relative)
        if content is not None:
            generated[relative] = content

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
            if relative in generated:
                copy_needed = generated[relative] != target_path.read_text(encoding="utf-8")
            else:
                copy_needed = sha256sum(source_path) != sha256sum(target_path)

        if not copy_needed:
            print(f"SKIP   {target_relative.as_posix()}")
            skipped += 1
            continue

        if dry_run:
            print(f"COPY   {target_relative.as_posix()}")
        else:
            if relative in generated:
                target_path.write_text(
                    generated[relative],
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

    # Remove only legacy command files corresponding to current dormant skills.
    for skill in (source_root / "skills-dormant").iterdir():
        legacy = plugin_root / "com.github.copilot" / "commands" / f"{skill.name}.prompt.md"
        if not skill.is_dir() or not legacy.is_file():
            continue
        label = legacy.relative_to(plugin_root).as_posix()
        source_text = (skill / "SKILL.md").read_text(encoding="utf-8")
        previous = re.sub(r"(?m)^name:\s*.*$", f"name: {skill.name}", source_text, count=1)
        previous = re.sub(
            r"(?m)^[ \t]*disable-model-invocation:[^\r\n]*(?:\r?\n|$)", "", previous, count=1
        )
        if legacy.read_text(encoding="utf-8") != previous:
            print(f"KEEP   {label} (not an exact legacy conversion; inspect manually)")
            continue
        if dry_run:
            print(f"REMOVE {label} (legacy dormant-skill conversion)")
        else:
            legacy.unlink()
            print(f"REMOVED {label} (legacy dormant-skill conversion)")
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
    # Validate transformations before version or payload files are modified.
    for relative in iter_managed_source_files(source_root):
        build_managed_content(source_root, relative)
    agent_content = build_merged_agent_content(
        (source_root / "agents" / "ENSDF-Agent.agent.md").read_text(encoding="utf-8"),
        (source_root / "copilot-instructions.md").read_text(encoding="utf-8")
        if (source_root / "copilot-instructions.md").is_file() else "",
    )
    validate_portable_text(agent_content, Path("com.github.copilot/agents/ENSDF-Agent.agent.md"))
    dependencies = workspace_dependencies(source_root)
    if dependencies:
        print(
            "WARNING: Authored agent/skill instructions reference workspace files; "
            "plugin installation does not create these paths:"
        )
        for dependency in dependencies:
            print(f"  {dependency}")
        print()
    if not args.no_bump:
        bump_versions(repo_root, args.bump, args.dry_run)
    else:
        get_canonical_version(repo_root)
    sync_readme(repo_root, plugin_root, args.dry_run)
    sync_agent_file(source_root, plugin_root, args.dry_run)
    return sync(source_root, plugin_root, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
