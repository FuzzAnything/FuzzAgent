"""Regression checks for the HarnessMinimizer adapter's API and output handling."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "src/tools/analysis/bin/harness_minimizer"
loader = importlib.machinery.SourceFileLoader("minimizer_adapter", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
adapter = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"project_utils": SimpleNamespace(
    ProjectUtils=SimpleNamespace(), CompileKind=SimpleNamespace(Sanitizer="sanitizer")
)}):
    loader.exec_module(adapter)


class HarnessMinimizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="minimizer test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fuzzer_dir = self.root / "fuzzer_000"
        self.fuzzer_dir.mkdir()
        self.harness = self.root / "harness_000.cpp"
        self.harness.write_text("original harness")
        (self.fuzzer_dir / "fuzzer").write_text("original binary")
        self.artifact = self.root / "crash-second"
        self.artifact.write_bytes(b"chosen input")
        self.work = self.root / "work"
        self.work.mkdir()

    def result(self):
        reduced = self.root / "reduced.cpp"
        reduced.write_text('#include "harness_values.h"\n')
        header = self.root / "harness_values.h"
        header.write_text("const unsigned char input[] = {1};\n")
        return dict(success=True, reduced_harness=str(reduced),
                    generated_headers=[str(header)], poc_runtime_args=["-rss_limit_mb=0"])

    def test_split_flags_preserves_quoted_arguments_and_library_order(self):
        compile_flags, link_flags = adapter.split_extra_flags(
            '-I "include with spaces" -D "LABEL=hello world" -std=c++17 '
            '-L "library path" -ltarget -Wl,--as-needed "other lib.a" -pthread'
        )
        self.assertEqual(compile_flags, ["-I", "include with spaces", "-D", "LABEL=hello world", "-std=c++17", "-pthread"])
        self.assertEqual(link_flags, ["-L", "library path", "-ltarget", "-Wl,--as-needed", "other lib.a", "-pthread"])

    def test_passes_exact_crash_and_current_api_options(self):
        build = self.root / "sanitizer"
        (build / "lib").mkdir(parents=True)
        library = build / "lib/libtarget.a"
        library.touch()
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "extra_flags.txt").write_text('-D "LABEL=two words" -lm')
        project = SimpleNamespace(
            get_harness_path_by_id=lambda _: str(self.harness),
            get_fuzzer_dir_by_id=lambda _: str(self.fuzzer_dir),
            get_build_work_dir=lambda _: str(build),
            get_cache_fuzzer_dir=lambda _: str(cache),
            get_project_header_include_dir=lambda: str(build / "include"),
            get_project_3rdparty_include_dir=lambda _: str(build / "3rdparty/include"),
            get_project_3rdparty_libs_from_dir=lambda _: [],
        )
        with patch.object(adapter, "ProjectUtils", project), \
             patch.object(adapter, "run_reduction", return_value=self.result()) as reduce, \
             patch.object(adapter, "export_poc") as export:
            adapter.minimizer(0, str(self.artifact))
        config = reduce.call_args.args[0]
        self.assertEqual(config["crash_input"], str(self.artifact))
        self.assertNotIn("extra_flags", config)
        self.assertNotIn("use_llm", config)
        flags = adapter.shlex.split(config["compile_flags"])
        self.assertIn(f"-I{build / 'include'}", flags)
        self.assertIn(f"-I{build / '3rdparty/include'}", flags)
        self.assertIn("LABEL=two words", flags)
        self.assertIn(str(library), adapter.shlex.split(config["link_flags"]))
        self.assertTrue(config["amortize_link"])
        export.assert_called_once()
        self.assertEqual(self.harness.read_text(), "original harness")
        self.assertEqual((self.fuzzer_dir / "fuzzer").read_text(), "original binary")

    def test_api_subprocess_uses_structured_result(self):
        package = self.root / "harnessminimizer"
        package.mkdir()
        (package / "__init__.py").write_text('''from dataclasses import dataclass
@dataclass
class ReductionConfig:
    harness_path: str
@dataclass
class ReductionResult:
    reduced_harness: str
    generated_headers: tuple = ()
    poc_runtime_args: tuple = ()
    success: bool = True
def reduce_with_config(config):
    return ReductionResult(config.harness_path, ("values.h",), ("-rss_limit_mb=0",))
''')
        with patch.dict(os.environ, {"HARNESSMINIMIZER_PYTHON": sys.executable, "PYTHONPATH": str(self.root)}):
            result = adapter.run_reduction({"harness_path": str(self.harness)}, self.work)
        self.assertTrue(result["success"])
        self.assertEqual(result["generated_headers"], ["values.h"])
        self.assertEqual(result["poc_runtime_args"], ["-rss_limit_mb=0"])

    def test_export_copies_headers_and_keeps_original_fuzzer(self):
        def run(command, **kwargs):
            if command[0] == "clang++":
                Path(command[command.index("-o") + 1]).write_text("reduced binary")
                self.assertIn(f"-fdebug-prefix-map={self.work / 'export'}={self.fuzzer_dir}", command)
                return subprocess.CompletedProcess(command, 0)
            self.assertEqual(command[1:], ["-rss_limit_mb=0", str(self.artifact)])
            return subprocess.CompletedProcess(command, 77, "ERROR: AddressSanitizer: heap-buffer-overflow")
        with patch.object(adapter.subprocess, "run", side_effect=run):
            adapter.export_poc(self.result(), self.fuzzer_dir, self.artifact, [], [], self.work)
        self.assertTrue((self.fuzzer_dir / "harness_values.h").is_file())
        self.assertEqual((self.fuzzer_dir / "poc").read_text(), "reduced binary")
        self.assertEqual((self.fuzzer_dir / "fuzzer").read_text(), "original binary")
        self.assertEqual(self.harness.read_text(), "original harness")

    def test_crash_report_archives_generated_header_with_poc(self):
        (self.fuzzer_dir / "poc.cpp").write_text('#include "harness_values.h"\n')
        (self.fuzzer_dir / "harness_values.h").write_text("const int value = 1;\n")
        reports = self.root / "reports"
        reports.mkdir()
        profile = SimpleNamespace(fuzzers={0: SimpleNamespace(state=None)})
        project = SimpleNamespace(
            get_fuzzer_binary_by_id=lambda _: str(self.fuzzer_dir / "fuzzer"),
            get_project_crash_report_dir=lambda: str(reports),
            get_harness_path_by_id=lambda _: str(self.harness),
            get_fuzzer_dir_by_id=lambda _: str(self.fuzzer_dir),
            get_fuzzer_profile=lambda: profile,
            save_fuzzer_profile=lambda _: None,
        )
        report_script = SCRIPT.with_name("generate_crash_report")
        report_loader = importlib.machinery.SourceFileLoader("crash_report_for_test", str(report_script))
        report_spec = importlib.util.spec_from_loader(report_loader.name, report_loader)
        report = importlib.util.module_from_spec(report_spec)
        with patch.dict(sys.modules, {"project_utils": SimpleNamespace(
            ProjectUtils=project,
            FuzzerExecutionState=SimpleNamespace(HARNESS_BUG="harness-bug", LIBRARY_BUG="library-bug"),
        )}):
            report_loader.exec_module(report)
        report.generate_crash_report(0, str(self.artifact), "harness-bug", "confirmed crash")
        archived = reports / "crash_000"
        self.assertEqual((archived / "poc.cpp").read_text(), '#include "harness_values.h"\n')
        self.assertEqual((archived / "harness_values.h").read_text(), "const int value = 1;\n")

    def test_failed_compile_does_not_publish_or_replace_existing_poc(self):
        (self.fuzzer_dir / "poc.cpp").write_text("previous PoC")
        with patch.object(adapter.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "clang++")):
            with self.assertRaises(subprocess.CalledProcessError):
                adapter.export_poc(self.result(), self.fuzzer_dir, self.artifact, [], [], self.work)
        self.assertEqual((self.fuzzer_dir / "poc.cpp").read_text(), "previous PoC")
        self.assertFalse((self.fuzzer_dir / "poc").exists())

    def test_non_crash_exit_is_rejected(self):
        with patch.object(adapter.subprocess, "run", side_effect=[
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 1, "error while loading shared libraries"),
        ]):
            with self.assertRaisesRegex(RuntimeError, "did not reproduce"):
                adapter.export_poc(self.result(), self.fuzzer_dir, self.artifact, [], [], self.work)
        self.assertFalse((self.fuzzer_dir / "poc.cpp").exists())

    def test_missing_or_slow_unit_artifact_never_starts_reduction(self):
        for name in ("missing-input", "slow-unit-test"):
            if name.startswith("slow-unit"):
                (self.root / name).touch()
            with patch.object(adapter, "run_reduction") as reduce:
                with self.assertRaises(ValueError):
                    adapter.minimizer(0, str(self.root / name))
                reduce.assert_not_called()


if __name__ == "__main__":
    unittest.main()
