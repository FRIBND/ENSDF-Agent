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
from unittest import mock
import os


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
        self.assertEqual(result, source)

    def test_hook_rewrite_preserves_other_variables_and_multiple_paths(self):
        command = "python .github/hooks/scripts/a.py --other '$OTHER' .github\\hooks\\scripts\\b.py"
        result = sync_plugin.rewrite_plugin_hook_path(command)
        self.assertEqual(
            result,
            'python "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/a.py" --other '
            '\'$OTHER\' "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/b.py"',
        )
        self.assertEqual(
            sync_plugin.rewrite_plugin_hook_path("python '.github/hooks/scripts/a.py'"),
            'python "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/a.py"',
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
        agent = (
            '---\nhooks:\n  preToolUse:\n'
            '    - type: command\n      command: "python .github/hooks/scripts/a.py"\n'
            '      cwd: .github/hooks/scripts\n'
            '      env:\n        SCRIPT: .github/hooks/scripts/a.py\n        KEEP: "$HOME"\n'
            '---\n'
        )
        output = sync_plugin.rewrite_agent_hook_block(agent)
        self.assertIn('cwd: "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts"', output)
        self.assertIn('SCRIPT: "${PLUGIN_ROOT}/com.github.copilot/hooks/scripts/a.py"', output)
        self.assertIn('KEEP: "$HOME"', output)

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
            self.assertEqual((plugin / "skills" / "active" / "SKILL.md").read_text(), "active\n")
            self.assertFalse((plugin / "skills-dormant" / "active").exists())
            self.assertFalse((plugin / "skills" / "example").exists())
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

    def test_only_workstation_pdf_path_changes_in_dormant_skill(self):
        source = "Java tool at `D:\\X\\ND\\McMaster-MSU-Java-NDS\\`.\n"
        result = sync_plugin.rewrite_markdown_paths(source, Path("skills-dormant/ens2pdf/SKILL.md"))
        self.assertEqual(result, "Java tool at `${ENSDF_NDS_JAR}`.\n")

    def test_agent_body_is_preserved(self):
        source = '---\nname: ENSDF-Agent\n---\n# Authored title\nRead `.github/skills/rounding/SKILL.md`.\n'
        output = sync_plugin.build_merged_agent_content(source, "")
        self.assertEqual(output, source)

    def test_workspace_dependency_warning_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "agents").mkdir()
            (root / "agents" / "ENSDF-Agent.agent.md").write_text(
                "Run `.github/scripts/example.py`.\n", encoding="utf-8"
            )
            skill = root / "skills" / "example" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "Read `.github\\skills\\example\\SKILL.md` and "
                "run `.github/scripts/example.py`; "
                "follow `.github/copilot-instructions.md`.\n",
                encoding="utf-8",
            )
            self.assertEqual(
                sync_plugin.workspace_dependencies(root),
                [
                    ".github/copilot-instructions.md",
                    ".github/scripts/example.py",
                    ".github/skills/example/SKILL.md",
                ],
            )

    def test_portability_guard_rejects_workstation_paths(self):
        for text in ('C:\\Users\\dev\\script.py', 'D:/data/example.ens', '/home/dev/input.txt',
                     '<plugin-root>/scripts/tool.py'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    sync_plugin.validate_portable_text(text, Path("scripts/example.py"))
        sync_plugin.validate_portable_text('https://example.test/ and "${PLUGIN_ROOT}/scripts/run.py"', Path("example.md"))

    def test_changed_pdf_main_stops_instead_of_discarding_changes(self):
        source = 'def main():\n    print("updated source")\n'
        with self.assertRaisesRegex(ValueError, "entry point changed"):
            sync_plugin.rewrite_bundled_script(source, Path("scripts/ens2pdf.py"))

    def test_pdf_conversion_from_relocated_plugin(self):
        script = ROOT / "plugins" / "ensdf-agent" / "scripts" / "ens2pdf.py"
        with tempfile.TemporaryDirectory(prefix="pdf test ") as directory:
            root = Path(directory)
            workspace = root / "workspace with spaces"
            source = workspace / "A35" / "Si35" / "new" / "Si35_adopted.ens"
            source.parent.mkdir(parents=True)
            source.write_text("test", encoding="utf-8")
            jar = root / "tools with spaces" / "nds.jar"
            jar.parent.mkdir()
            jar.write_bytes(b"jar")
            installed = root / "installed plugin" / "scripts" / "ens2pdf.py"
            installed.parent.mkdir(parents=True)
            shutil.copy2(script, installed)
            spec = importlib.util.spec_from_file_location("ens2pdf_test", installed)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            def fake_java(ens_path, jar_path, staging):
                self.assertEqual(ens_path, source)
                self.assertEqual(jar_path, str(jar))
                pdf = staging / (ens_path.stem + ".pdf")
                pdf.write_bytes(b"pdf")
                return pdf
            old_cwd = Path.cwd()
            try:
                os.chdir(workspace)
                with mock.patch.object(module, "run_java", side_effect=fake_java), \
                     mock.patch.object(module.shutil, "which", return_value="java"), \
                     mock.patch.object(sys, "argv", [str(installed), "Si35_adopted", "--jar", str(jar)]):
                    module.main()
            finally:
                os.chdir(old_cwd)
            self.assertEqual((source.parent.parent / "pdf" / "Si35_adopted.pdf").read_bytes(), b"pdf")

    def test_pdf_help_and_missing_jar(self):
        script = ROOT / "plugins" / "ensdf-agent" / "scripts" / "ens2pdf.py"
        result = subprocess.run([sys.executable, str(script), "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--jar", result.stdout)
        with tempfile.TemporaryDirectory(prefix="pdf missing ") as directory:
            result = subprocess.run(
                [sys.executable, str(script), "example.ens", "--jar", "missing.jar"],
                cwd=directory, text=True, capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JAR not found", result.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Windows executable integration test")
    def test_pdf_cli_executes_java_with_spaced_paths(self):
        plugin_source = ROOT / "plugins" / "ensdf-agent" / "scripts" / "ens2pdf.py"
        with tempfile.TemporaryDirectory(prefix="pdf executable test ") as directory:
            root = Path(directory)
            installed = root / "installed plugin" / "scripts" / "ens2pdf.py"
            installed.parent.mkdir(parents=True)
            shutil.copy2(plugin_source, installed)
            workspace = root / "workspace with spaces"
            data = workspace / "A35" / "Si35" / "new" / "Si35_adopted.ens"
            data.parent.mkdir(parents=True)
            data.write_text("test", encoding="utf-8")
            jar = root / "tools with spaces" / "nds.jar"
            jar.parent.mkdir()
            jar.write_bytes(b"jar")
            fake_java = root / "fake java" / "java.exe"
            fake_java.parent.mkdir()
            csharp = 'public class Program { public static void Main(string[] a) { System.IO.File.WriteAllText(a[3], "pdf"); } }'
            escaped = str(fake_java).replace("'", "''")
            build = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"Add-Type -TypeDefinition '{csharp}' -OutputAssembly '{escaped}' -OutputType ConsoleApplication"],
                text=True, capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            env = os.environ.copy()
            env["PATH"] = str(fake_java.parent) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [sys.executable, str(installed), "Si35_adopted", "--jar", str(jar)],
                text=True, capture_output=True, cwd=workspace, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            pdf = data.parent.parent / "pdf" / "Si35_adopted.pdf"
            self.assertEqual(pdf.read_text(), "pdf")
            pdf.unlink()
            env["ENSDF_NDS_JAR"] = str(jar)
            result = subprocess.run(
                [sys.executable, str(installed), str(data)],
                text=True, capture_output=True, cwd=workspace, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(pdf.is_file())
            other = data.parent / "Si35_other_sig.ens"
            other.write_text("test", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(installed), "Si35_*sig"],
                text=True, capture_output=True, cwd=workspace, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((pdf.parent / "Si35_other_sig.pdf").is_file())

    def test_formatcheck_uses_configured_jar_and_output(self):
        script = ROOT / "plugins" / "ensdf-agent" / "scripts" / "Java_FormatCheck.py"
        with tempfile.TemporaryDirectory(prefix="format test ") as directory:
            root = Path(directory)
            source = root / "workspace with spaces" / "input.ens"
            source.parent.mkdir()
            source.write_text("test", encoding="utf-8")
            jar = root / "tools with spaces" / "FormatCheck.jar"
            jar.parent.mkdir()
            jar.write_bytes(b"jar")
            output = root / "reports with spaces"
            spec = importlib.util.spec_from_file_location("formatcheck_test", script)
            assert spec and spec.loader
            with mock.patch.dict(os.environ, {
                "ENSDF_FORMATCHECK_JAR": str(jar),
                "ENSDF_FORMATCHECK_OUTPUT_DIR": str(output),
            }):
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                def fake_run(command):
                    self.assertEqual(command, ["java", "-jar", str(jar), str(source)])
                    (source.parent / "formatcheck.fmt").write_text("report", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0)
                with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
                    self.assertEqual(module.run_formatcheck(str(source)), 0)
            self.assertEqual((output / "formatcheck.fmt").read_text(encoding="utf-8"), "report")

    def test_compare_files_with_spaces(self):
        script = ROOT / "plugins" / "ensdf-agent" / "scripts" / "compare_line_metrics.py"
        with tempfile.TemporaryDirectory(prefix="comparison test ") as directory:
            root = Path(directory)
            old = root / "old file.txt"
            new = root / "new file.txt"
            old.write_text("a\nb\n", encoding="utf-8")
            new.write_text("a\nc\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script), str(old), str(new)],
                text=True, capture_output=True, cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1", result.stdout)

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
            git_event = {
                "toolName": "powershell",
                "toolArgs": {"command": "git restore example.ens"},
                "cwd": str(workspace),
            }
            result = subprocess.run(
                [sys.executable, str(hooks / "block-git-revert.py")],
                input=json.dumps(git_event), text=True, capture_output=True, cwd=workspace, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")
            edit_event = {
                "toolName": "apply_patch",
                "toolArgs": {"input": "*** Begin Patch\n*** Update File: example.ens\n*** End Patch"},
                "cwd": str(workspace),
            }
            result = subprocess.run(
                [sys.executable, str(hooks / "guard_ens_edit.py")],
                input=json.dumps(edit_event), text=True, capture_output=True, cwd=workspace, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")
            invalid = workspace / "invalid.ens"
            invalid.write_text("\u00e9\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(hooks / "verify_ens_edit.py")],
                input=json.dumps({"toolName": "create_file", "toolArgs": {"filePath": str(invalid),
                                  "content": "short"}, "cwd": str(workspace)}),
                text=True, capture_output=True, cwd=workspace, check=True,
            )
            self.assertIn("ASCII validation failed", json.loads(result.stdout)["additionalContext"])
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
