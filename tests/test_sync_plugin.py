import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sync_plugin", ROOT / "dev" / "sync_plugin_from_local_agent.py"
)
assert SPEC and SPEC.loader
sync_plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_plugin)


class SyncTests(unittest.TestCase):
    def test_markdown_references_and_commands(self):
        source = (
            "---\nname: example\n---\n"
            "Read `.github/agents/ENSDF-Agent.agent.md` and "
            "`.github\\skills\\rounding\\SKILL.md`.\n"
            'Run `python .github\\scripts\\column_calibrate.py "data file.ens"`.\n'
            "```bash\npython .github/scripts/ensdf_1line_ruler.py --file 'a b.ens'\n```\n"
        )
        result = sync_plugin.rewrite_markdown_paths(source, Path("skills/example/SKILL.md"))
        self.assertIn("`../../com.github.copilot/agents/ENSDF-Agent.agent.md`", result)
        self.assertIn("`../rounding/SKILL.md`", result)
        self.assertIn('python "../../scripts/column_calibrate.py" "data file.ens"', result)
        self.assertIn('python "../../scripts/ensdf_1line_ruler.py" --file', result)
        self.assertIn("Resolve bundled paths relative to this skill file", result)
        self.assertNotIn("<plugin-root>", result)
        self.assertTrue(result.startswith("---\nname: example\n---\n"))

    def test_hook_rewrite_preserves_other_variables_and_multiple_paths(self):
        command = "python .github/hooks/scripts/a.py --other '$OTHER' .github\\hooks\\scripts\\b.py"
        result = sync_plugin.rewrite_plugin_hook_path(command)
        self.assertEqual(
            result,
            'python "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/a.py" --other '
            '\'$OTHER\' "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/b.py"',
        )
        agent = '---\nhooks:\n  preToolUse:\n    - type: command\n      command: ' + json.dumps(command) + '\n---\n'
        output = sync_plugin.rewrite_agent_hook_block(agent)
        scalar = output.split("      command: ", 1)[1].splitlines()[0]
        self.assertEqual(json.loads(scalar), result)
        self.assertEqual(sync_plugin._agent_hook_record_count(agent), sync_plugin._agent_hook_record_count(output))
        agent = (
            '---\nhooks:\n  preToolUse:\n'
            '    - type: command\n      exec: python\n'
            '      args:\n        - .github/hooks/scripts/a.py\n        - "$OTHER"\n'
            '    - type: command\n      exec: python\n'
            '      args: [".github/hooks/scripts/b.py", "$OTHER"]\n---\n'
        )
        output = sync_plugin.rewrite_agent_hook_block(agent)
        self.assertIn('- "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/a.py"', output)
        self.assertIn('args: ["${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/b.py", "$OTHER"]', output)
        self.assertIn('- "$OTHER"', output)

    def test_sync_mirrors_dormant_resources_and_preserves_unrelated_commands(self):
        with tempfile.TemporaryDirectory(prefix="sync test ") as directory:
            root = Path(directory)
            source = root / "source"
            plugin = root / "plugin"
            for entry in sync_plugin.managed_entries:
                (source / entry).mkdir(parents=True, exist_ok=True)
            (source / "agents").mkdir()
            (source / "agents" / "ENSDF-Agent.agent.md").write_text("---\n---\n", encoding="utf-8")
            (source / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
            (source / "hooks" / "scripts" / "hook.py").write_text("print(1)\n", encoding="utf-8")
            (source / "skills" / "active").mkdir()
            (source / "skills" / "active" / "SKILL.md").write_text("active\n", encoding="utf-8")
            dormant = source / "skills-dormant" / "example"
            (dormant / "assets").mkdir(parents=True)
            (dormant / "SKILL.md").write_text(
                "---\nname: example\ndisable-model-invocation: true\n---\n", encoding="utf-8"
            )
            (dormant / "assets" / "data.bin").write_bytes(b"\x00\x01")
            commands = plugin / "com.github.copilot" / "commands"
            commands.mkdir(parents=True)
            (commands / "example.prompt.md").write_text(
                "---\nname: example\n---\n", encoding="utf-8"
            )
            (commands / "unrelated.prompt.md").write_text("keep", encoding="utf-8")
            stale = plugin / "skills-dormant" / "old" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sync_plugin.sync(source, plugin, False), 0)
                self.assertEqual(sync_plugin.sync(source, plugin, False), 0)
            self.assertIn("disable-model-invocation: true", (plugin / "skills-dormant" / "example" / "SKILL.md").read_text())
            self.assertEqual((plugin / "skills-dormant" / "example" / "assets" / "data.bin").read_bytes(), b"\x00\x01")
            self.assertFalse((commands / "example.prompt.md").exists())
            self.assertTrue((commands / "unrelated.prompt.md").is_file())
            self.assertFalse(stale.exists())

    def test_version_bump_preflights_all_manifests(self):
        with tempfile.TemporaryDirectory(prefix="version test ") as directory:
            root = Path(directory)
            canonical = root / sync_plugin.version_files[0]
            canonical.parent.mkdir(parents=True)
            canonical.write_text('{"version": "0.6.3"}', encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                sync_plugin.bump_versions(root, "patch", False)
            self.assertEqual(json.loads(canonical.read_text())["version"], "0.6.3")

    def test_group_skill_renamed_only_when_old_target_is_missing(self):
        with tempfile.TemporaryDirectory(prefix="skill test ") as directory:
            root = Path(directory)
            merge = root / "skills" / "merge-adopted-levels" / "SKILL.md"
            merge.parent.mkdir(parents=True)
            merge.write_text("merge", encoding="utf-8")
            text = "`.github/skills/group-adopted-levels/SKILL.md`"
            result = sync_plugin.rewrite_markdown_paths(text, Path("skills/example/SKILL.md"), root)
            self.assertIn("../merge-adopted-levels/SKILL.md", result)
            group = root / "skills" / "group-adopted-levels" / "SKILL.md"
            group.parent.mkdir(parents=True)
            group.write_text("group", encoding="utf-8")
            result = sync_plugin.rewrite_markdown_paths(text, Path("skills/example/SKILL.md"), root)
            self.assertIn("../group-adopted-levels/SKILL.md", result)

    def test_incompatible_pdf_script_rejects_arguments(self):
        script = ROOT / "plugins" / "ensdf-agent" / "scripts" / "ens2pdf.py"
        result = subprocess.run(
            [sys.executable, str(script), "example.ens"], text=True, capture_output=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not accept command-line arguments", result.stderr)

    def test_generated_hooks_use_workspace_and_bundled_ruler(self):
        plugin_source = ROOT / "plugins" / "ensdf-agent"
        with tempfile.TemporaryDirectory(prefix="plugin test ") as directory:
            root = Path(directory)
            plugin = root / "installed plugin"
            workspace = root / "workspace with spaces"
            workspace.mkdir()
            shutil.copytree(plugin_source / "com.github.copilot" / "hooks", plugin / "com.github.copilot" / "hooks")
            (plugin / "scripts").mkdir()
            shutil.copy2(plugin_source / "scripts" / "ensdf_1line_ruler.py", plugin / "scripts")
            hooks = plugin / "com.github.copilot" / "hooks" / "scripts"
            ens = workspace / "example.ens"
            ens.write_text(" " * 80 + "\n", encoding="ascii")
            event = {"tool_name": "read_file", "tool_input": {"filePath": str(ens)}, "cwd": str(workspace)}
            result = subprocess.run(
                [sys.executable, str(hooks / "guard_ens_edit.py")],
                input=json.dumps(event), text=True, capture_output=True, cwd=workspace, check=True,
            )
            self.assertFalse(result.stderr)
            self.assertTrue((workspace / ".github" / "temp" / "ens_guard" / "state.json").is_file())
            self.assertFalse((plugin / ".github" / "temp" / "ens_guard" / "state.json").exists())
            spec = importlib.util.spec_from_file_location("verify_hook_test", hooks / "verify_ens_edit.py")
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(Path(module.find_ruler_script({"cwd": str(workspace)})), plugin / "scripts" / "ensdf_1line_ruler.py")
            block_event = {"tool_name": "create_file", "tool_input": {"filePath": str(workspace / "blocked.txt")}, "cwd": str(workspace)}
            result = subprocess.run(
                [sys.executable, str(hooks / "block-root-file-creation.py")],
                input=json.dumps(block_event), text=True, capture_output=True, cwd=workspace, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")
            if sys.platform == "win32":
                command = sync_plugin.rewrite_plugin_hook_path(
                    "python .github/hooks/scripts/block-root-file-creation.py"
                ).replace("${PLUGIN_ROOT}", str(plugin))
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                    input=json.dumps(block_event), text=True, capture_output=True, cwd=workspace, check=True,
                )
                self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
