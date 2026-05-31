from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_SYNC = REPO_ROOT / "sync_plugin_from_local_agent.py"

# Files whose source content should be copied into the plugin on every sync.
MANAGED_FILES = {
    Path("copilot-instructions.md"): "source-instructions\n",
    Path("hooks/scripts/validate_ens.py"): "print('validate')\n",
    Path("prompts/example.prompt.md"): "prompt\n",
    Path("scripts/tool.py"): "print('tool')\n",
    Path("skills/example/SKILL.md"): "skill\n",
}

# A file that exists in the source tree but is in PRESERVED_PLUGIN_FILES in the
# real script — the plugin's copy must NOT be overwritten during sync.
PRESERVED_IN_SOURCE = Path("agents/ENSDF-Agent.agent.md")
PRESERVED_SOURCE_CONTENT = "source-agent-with-hooks\n"
PRESERVED_PLUGIN_CONTENT = "plugin-agent-no-hooks\n"

EXCLUDED_SOURCE_FILES = {
    Path("docs/guide.md"): "docs should never sync\n",
    Path("temp/scratch.txt"): "temp should never sync\n",
    Path("scripts/__pycache__/tool.cpython-311.pyc"): "cache should never sync\n",
}

EXCLUDED_TARGET_FILES = {
    Path("docs/leftover.md"): "leftover docs\n",
    Path("temp/leftover.txt"): "leftover temp\n",
    Path("scripts/__pycache__/leftover.pyc"): "leftover cache\n",
}


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class SyncScriptFixture:
    def __init__(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.source = self.root / "source" / ".github"
        self.plugin = self.root / "plugin"

    def close(self) -> None:
        self._temp_dir.cleanup()

    def populate(self) -> None:
        # Source: managed files + the preserved file + excluded dirs
        for relative, content in MANAGED_FILES.items():
            write_file(self.source / relative, content)
        write_file(self.source / PRESERVED_IN_SOURCE, PRESERVED_SOURCE_CONTENT)
        for relative, content in EXCLUDED_SOURCE_FILES.items():
            write_file(self.source / relative, content)

        # Plugin: stale versions of managed files
        for relative in MANAGED_FILES:
            write_file(self.plugin / relative, f"stale-{relative.as_posix()}\n")

        # Plugin: preserved file with plugin-specific content (must survive sync)
        write_file(self.plugin / PRESERVED_IN_SOURCE, PRESERVED_PLUGIN_CONTENT)

        # Plugin: stale file not in source (should be removed by sync)
        write_file(self.plugin / "scripts/stale_only.py", "remove me\n")

        # Plugin: excluded target dirs (should be cleaned up)
        for relative, content in EXCLUDED_TARGET_FILES.items():
            write_file(self.plugin / relative, content)


class SyncScriptTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.fixture = SyncScriptFixture()
        self.fixture.populate()

    def tearDown(self) -> None:
        self.fixture.close()

    def assert_synced_plugin_tree(self) -> None:
        # Managed files must have source content
        for relative, content in MANAGED_FILES.items():
            path = self.fixture.plugin / relative
            self.assertTrue(path.is_file(), f"missing: {relative.as_posix()}")
            self.assertEqual(path.read_text(encoding="utf-8"), content, relative.as_posix())

        # Preserved file must retain plugin content — NOT overwritten with source
        preserved = self.fixture.plugin / PRESERVED_IN_SOURCE
        self.assertTrue(preserved.is_file())
        self.assertEqual(preserved.read_text(encoding="utf-8"), PRESERVED_PLUGIN_CONTENT)

        # Stale target-only file must be removed
        self.assertFalse((self.fixture.plugin / "scripts/stale_only.py").exists())

        # Excluded source files must NOT appear in plugin
        for relative in EXCLUDED_SOURCE_FILES:
            self.assertFalse(
                (self.fixture.plugin / relative).exists(),
                f"excluded source file was synced: {relative.as_posix()}",
            )

        # Excluded target dirs must be cleaned up
        for relative in EXCLUDED_TARGET_FILES:
            self.assertFalse(
                (self.fixture.plugin / relative).exists(),
                f"excluded target file was not cleaned: {relative.as_posix()}",
            )
        self.assertFalse((self.fixture.plugin / "docs").exists())
        self.assertFalse((self.fixture.plugin / "temp").exists())

    def run_python_sync(self, dry_run: bool = False) -> subprocess.CompletedProcess[str]:
        command = [
            sys_executable(),
            str(PYTHON_SYNC),
            "--source-github-path", str(self.fixture.source),
            "--plugin-root", str(self.fixture.plugin),
            "--repo-root", str(self.fixture.root),  # no README there → sync_readme skips
            "--no-bump",
        ]
        if dry_run:
            command.append("--dry-run")
        return subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=True)

    def test_python_sync_dry_run_preserves_filesystem(self) -> None:
        result = self.run_python_sync(dry_run=True)
        # Managed files must show as pending copies
        self.assertIn("COPY   copilot-instructions.md", result.stdout)
        # Preserved file must be reported as skipped, not copied
        self.assertIn("SKIP   agents/ENSDF-Agent.agent.md (preserved/excluded)", result.stdout)
        # Stale target-only file must show as pending removal
        self.assertIn("REMOVE scripts/stale_only.py", result.stdout)
        # Dry-run must not touch the filesystem
        self.assertTrue((self.fixture.plugin / "scripts/stale_only.py").exists())
        self.assertTrue((self.fixture.plugin / "docs/leftover.md").exists())

    def test_python_sync_applies_expected_changes(self) -> None:
        self.run_python_sync(dry_run=False)
        self.assert_synced_plugin_tree()


def sys_executable() -> str:
    return os.environ.get("PYTHON", os.sys.executable)


if __name__ == "__main__":
    unittest.main()
