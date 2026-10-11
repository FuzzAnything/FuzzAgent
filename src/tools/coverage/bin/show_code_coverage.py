#!/usr/bin/env python3
"""
Coverage Data Display Tool for FuzzAgent

"""
import os
import shutil
import subprocess
import sys
import json
import re

from dataclasses import dataclass, field
from typing import List, Optional
#sys.path.append("/tmp")

from project_utils import CompileKind, FuzzerExecutionState, ProjectUtils, FUZZAGENT_DEBUG, print_debug, check_subprocess_output, get_fuzzing_engine, FuzzingEngine
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing


PROFRAW_DIR_NAME = "profraw"
PROFDATA_FILE_NAME = "llvm_cov.profdata"
LLVM_COV_SUMMARY_FILE_NAME = "llvm_cov_summary.json"
LLVM_COV_JSON_FILE_NAME = "llvm_cov.json"
COVERAGE_SUCCESS_FILE_NAME = "success"
SOURCE_COVERAGE_DIR_NAME = "source_coverage"
INTROSPECTOR_DIR_NAME = "introspector"
COVERAGE_OVER_TIME_FILE_NAME = "coverage_over_time.json"

def print_dubug(message: str):
    if FUZZAGENT_DEBUG:
        print(f"[DEBUG] {message}")


@dataclass
class CoverageOverTimeRecord:
    """Persistent record of coverage-over-time data points."""

    fuzzer_ids: list[int] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    finished_times: list[float] = field(default_factory=list)

    @staticmethod
    def load(path: str) -> Optional["CoverageOverTimeRecord"]:
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return CoverageOverTimeRecord(
                fuzzer_ids=list(raw.get("fuzzer_ids", [])),
                coverage=[dict(c) for c in raw.get("coverage", [])],
                finished_times=[float(t) for t in raw.get("finished_times", [])],
            )
        except (TypeError, ValueError):
            return None

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(
                {
                    "fuzzer_ids": self.fuzzer_ids,
                    "coverage": self.coverage,
                    "finished_times": self.finished_times,
                },
                f,
            )

    def contains_fuzzer_id(self, fuzzer_id: int) -> bool:
        return fuzzer_id in self.fuzzer_ids


class CoverageUtils:

    @staticmethod
    def check_fuzzer_coverage_status(fuzzer_id: int):
        fuzzer_profile = ProjectUtils.get_fuzzer_profile()
        fuzzer_info = fuzzer_profile.fuzzers.get(fuzzer_id)
        if fuzzer_info is None:
            raise Exception(f"[!] ERROR: Please run the fuzzer {fuzzer_id} first before showing coverage")


    @staticmethod
    def should_skip_coverage_collection(fuzzer_id: int, replay_mode: bool = False) -> bool:
        coverage_dir = ProjectUtils.get_fuzzer_coverage_dir(fuzzer_id)
        if not os.path.exists(coverage_dir):
            os.makedirs(coverage_dir, exist_ok=True)
            return False
        success_file = os.path.join(coverage_dir, COVERAGE_SUCCESS_FILE_NAME)
        if not os.path.exists(success_file):
            shutil.rmtree(coverage_dir, ignore_errors=True)
            os.makedirs(coverage_dir, exist_ok=True)
            return False
        llvm_cov_file = os.path.join(coverage_dir, LLVM_COV_JSON_FILE_NAME)
        if not os.path.exists(llvm_cov_file):
            shutil.rmtree(coverage_dir, ignore_errors=True)
            os.makedirs(coverage_dir, exist_ok=True)
            return False
        if replay_mode:
            shutil.rmtree(coverage_dir, ignore_errors=True)
            os.makedirs(coverage_dir, exist_ok=True)
            return False
        return True

    @staticmethod
    def mark_coverage_collection_success(coverage_dir: str):
        success_file = os.path.join(coverage_dir, COVERAGE_SUCCESS_FILE_NAME)
        with open(success_file, "w") as f:
            f.write("success")
        coverage_dir = ProjectUtils.get_project_coverage_dir()
        success_file = os.path.join(coverage_dir, COVERAGE_SUCCESS_FILE_NAME)
        if os.path.exists(success_file):
            try:
                os.remove(success_file)
            except OSError:
                pass

    @staticmethod
    def execute_coverage_collection_pipeline(fuzzer_id: int, replay_mode: bool = False):
        print(f"[+] Collecting coverage for fuzzer {fuzzer_id:03d}...")
        CoverageUtils.check_fuzzer_coverage_status(fuzzer_id)
        if CoverageUtils.should_skip_coverage_collection(fuzzer_id, replay_mode=replay_mode):
            return
        CoverageUtils.execute_fuzzer_cov_on_target(fuzzer_id, replay_mode)
        fuzz_target = ProjectUtils.get_fuzzer_coverage_binary_by_id(fuzzer_id)
        coverage_dir = ProjectUtils.get_fuzzer_coverage_dir(fuzzer_id)

        profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)
        if os.path.exists(profdata):
            CoverageUtils.export_llvm_cov_to_json(coverage_dir)
            CoverageUtils._export_llvm_cov_summary_to_json(coverage_dir)
            CoverageUtils.generate_html(fuzz_target, coverage_dir)
        else:
            print(f"[!] WARNING: {profdata} does not exist! Skip generating coverage for this fuzzer!")
        CoverageUtils.mark_coverage_collection_success(coverage_dir)
        

    @staticmethod
    def gather_whole_project_coverage_pipeline(replay_mode: bool = False):
        fuzzer_ids = CoverageUtils.get_available_fuzzers()
        if len(fuzzer_ids) == 0:
            raise Exception(f"[!] Error: No fuzzer is available! So no coverage can be gathered! Please **Exit** and report this issue!")
        fuzzer_profdata = []
        for fuzzer_id in fuzzer_ids:
            CoverageUtils.execute_coverage_collection_pipeline(fuzzer_id, replay_mode=replay_mode)
            profdata_file = os.path.join(ProjectUtils.get_fuzzer_coverage_dir(fuzzer_id), PROFDATA_FILE_NAME)
            if not os.path.exists(profdata_file):
                print(f"[!] WARNING: {profdata_file} does not exist! Skip this fuzzer's profdata file in whole project coverage merge!")
                continue
            fuzzer_profdata.append(profdata_file)
        if len(fuzzer_profdata) == 0:
            raise Exception(f"[!] Error: No profdata file found! Please check the fuzzer coverage collection pipeline!")

        if CoverageUtils.should_skip_whole_project_coverage(fuzzer_ids, force_regenerate=replay_mode):
            return
        coverage_dir = ProjectUtils.get_project_coverage_dir()
        shared_lib = ProjectUtils.get_project_build_shared_lib(ProjectUtils.get_build_work_dir(CompileKind.Coverage))

        # Fuzzers missing finish_time sort to the end.
        finish_times = CoverageUtils._load_fuzzer_finish_times()

        def _finish_key(fid: int) -> float:
            t = finish_times.get(fid)
            return t if t is not None else float("inf")

        fuzzer_ids_sorted = sorted(fuzzer_ids, key=_finish_key)

        # Load the persistent record of curve points we've already computed.
        record_path = os.path.join(coverage_dir, COVERAGE_OVER_TIME_FILE_NAME)
        record: CoverageOverTimeRecord | None = None
        if not replay_mode:
            record = CoverageOverTimeRecord.load(record_path)
        if record is None:
            record = CoverageOverTimeRecord()

        final_profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)

        for fuzzer_id in fuzzer_ids_sorted:
            if record.contains_fuzzer_id(fuzzer_id):
                print_debug(f"[+] Skip fuzzer {fuzzer_id:03d} in whole project coverage merge since it's already included in the curve!")
                continue
            fuzzer_profdata_path = os.path.join(
                ProjectUtils.get_fuzzer_coverage_dir(fuzzer_id), PROFDATA_FILE_NAME
            )
            if not os.path.exists(fuzzer_profdata_path):
                print(f"[!] WARNING: {fuzzer_profdata_path} does not exist! Skip this fuzzer's profdata file in whole project coverage merge!")
                continue
            # empty, copy file directly
            if not record.fuzzer_ids:
                shutil.copy2(fuzzer_profdata_path, final_profdata)
            else:
                inputs = [final_profdata, fuzzer_profdata_path]
                cmd = ["llvm-profdata", "merge", "-sparse", *inputs, "-o", final_profdata]
                output = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=coverage_dir)
                check_subprocess_output(output)

            summary = CoverageUtils._export_llvm_cov_summary_to_json(coverage_dir)
            finish_millis = finish_times.get(fuzzer_id, None)
            record.fuzzer_ids.append(fuzzer_id)
            record.coverage.append(summary)
            record.finished_times.append(finish_millis)

        # Whole-project full export (existing behavior — HTML + llvm_cov.json).
        CoverageUtils.export_llvm_cov_to_json(coverage_dir)
        CoverageUtils.generate_html(shared_lib, coverage_dir)
        CoverageUtils.copy_harness_coverage_files_to_whole(fuzzer_ids, coverage_dir)
        CoverageUtils.mark_whole_project_coverage_success(fuzzer_ids)
        record.save(record_path)

    @staticmethod
    def _load_fuzzer_finish_times() -> dict[int, float]:
        from datetime import datetime
        stat_path = ProjectUtils.get_fuzzer_stat_file()
        if not os.path.exists(stat_path):
            return {}
        try:
            with open(stat_path) as f:
                stat = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        fuzzers = stat.get("fuzzers", {})
        result: dict[int, float] = {}
        for fid_str, info in fuzzers.items():
            ft_str = info.get("finish_time")
            if not isinstance(ft_str, str):
                continue
            try:
                fid = int(fid_str)
            except ValueError:
                continue
            try:
                ndt = datetime.strptime(ft_str, "%Y-%m-%d %H:%M:%S,%f")
            except ValueError:
                try:
                    ndt = datetime.strptime(ft_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
            result[fid] = ndt.timestamp() * 1000.0
        return result


    @staticmethod
    def copy_harness_coverage_files_to_whole(fuzzer_ids: list[int], coverage_dir: str):
        source_coverage = os.path.join(coverage_dir, SOURCE_COVERAGE_DIR_NAME)
        os.makedirs(source_coverage, exist_ok=True)
        for fuzzer_id in fuzzer_ids:
            fuzzer_coverage_dir = ProjectUtils.get_fuzzer_coverage_dir(fuzzer_id)
            fuzzer_source_coverage_dir = os.path.join(fuzzer_coverage_dir, SOURCE_COVERAGE_DIR_NAME)
            if not os.path.exists(fuzzer_source_coverage_dir):
                continue
            for file in os.listdir(fuzzer_source_coverage_dir):
                if file.startswith("harness_"):
                    shutil.copyfile(os.path.join(fuzzer_source_coverage_dir, file), os.path.join(source_coverage, file))

    @staticmethod
    def get_and_copy_afl_fuzzer_queue_corpus(fuzzer_id: int) -> str | None:
        afl_queue_dirs = ProjectUtils.get_afl_cache_fuzzer_queue_dirs(fuzzer_id)
        if len(afl_queue_dirs) == 0:
            return None
        if len(afl_queue_dirs) == 1:
            return afl_queue_dirs[0]
        dest_dir = os.path.join("/tmp", f"afl_queue_fuzzer_{fuzzer_id}")
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        os.makedirs(dest_dir, exist_ok=True)
        for queue_dir in afl_queue_dirs:
            for file in os.listdir(queue_dir):
                if os.path.isfile(os.path.join(queue_dir, file)):
                    shutil.copy2(os.path.join(queue_dir, file), os.path.join(dest_dir, file))
        return dest_dir

    @staticmethod
    def execute_fuzzer_cov_on_target(fuzzer_id: int, replay_mode: bool = False):
        fuzzing_corpus_dir = ProjectUtils.get_fuzzer_fuzzing_corpus_dir(fuzzer_id)
        if get_fuzzing_engine() == FuzzingEngine.AFLpp and replay_mode:
            afl_queue_dir = CoverageUtils.get_and_copy_afl_fuzzer_queue_corpus(fuzzer_id)
            if afl_queue_dir is not None:
                fuzzing_corpus_dir = afl_queue_dir
                print_debug(f"[+] Using AFL++ queue directory {afl_queue_dir} as fuzzing corpus for fuzzer {fuzzer_id:03d} coverage collection in replay mode.")
        if not os.path.exists(fuzzing_corpus_dir):
            raise Exception(f"[!] Error: The fuzzing corpus directory {fuzzing_corpus_dir} for fuzzer {fuzzer_id} does not exist!")
        if len(os.listdir(fuzzing_corpus_dir)) == 0:
            raise Exception(f"[!] Error: The fuzzing corpus directory {fuzzing_corpus_dir} for fuzzer {fuzzer_id:03d} is empty! Please report this error to the ManagerAgent and make sure the fuzzer {fuzzer_id:03d} has executed at least once by the tool `run_fuzz_target`.")
        fuzzer_coverage_dir = ProjectUtils.get_fuzzer_coverage_dir(fuzzer_id)
        profraw_dir = os.path.join(fuzzer_coverage_dir, PROFRAW_DIR_NAME)
        if not os.path.exists(profraw_dir):
            os.makedirs(profraw_dir, exist_ok=True)
        corpus_files = []
        for file in os.listdir(fuzzing_corpus_dir):
            corpus_files.append(os.path.join(fuzzing_corpus_dir, file))

        with ThreadPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
            tmp_dir = os.path.join("/tmp", f"fuzzer_cov_tmp_{fuzzer_id}")
            os.makedirs(tmp_dir, exist_ok=True)
            futures = [executor.submit(CoverageUtils.execute_fuzzer_cov_on_one_corpus_file, fuzzer_id, id, file_path, profraw_dir, tmp_dir) for id, file_path in enumerate(corpus_files)]
            for future in as_completed(futures):
                future.result(timeout=10)
            shutil.rmtree(tmp_dir, ignore_errors=True)

        print_debug(f"[+] Merging profdata files for fuzzer {fuzzer_id}...")
        profdata_file = os.path.join(fuzzer_coverage_dir, PROFDATA_FILE_NAME)
        CoverageUtils.safety_merge_llvm_cov_profdata(profraw_dir, profdata_file)
    

    @staticmethod
    def should_skip_whole_project_coverage(fuzzer_ids: list[int], force_regenerate: bool = False) -> bool:
        coverage_dir = ProjectUtils.get_project_coverage_dir()
        success_file = os.path.join(coverage_dir, COVERAGE_SUCCESS_FILE_NAME)
        if not os.path.exists(success_file):
            return False
        with open(success_file, "r") as f:
            old_fuzzer_ids = json.load(f)
            if len(old_fuzzer_ids) != len(fuzzer_ids):
                return False
        if force_regenerate:
            return False
        return True

    @staticmethod
    def mark_whole_project_coverage_success(fuzzer_ids: list[int]):
        coverage_dir = ProjectUtils.get_project_coverage_dir()
        success_file = os.path.join(coverage_dir, COVERAGE_SUCCESS_FILE_NAME)
        with open(success_file, "w") as f:
            f.write(json.dumps(fuzzer_ids))

    @staticmethod
    def execute_fuzzer_cov_on_one_corpus_file(fuzzer_id: int, id: int, corpus_file: str, profraw_dir: str, tmp_dir: str):
        corpus_dir = os.path.dirname(corpus_file)
        fuzzer_cov = ProjectUtils.get_fuzzer_coverage_binary_by_id(fuzzer_id)
        base_name = os.path.basename(corpus_file)
        profile_file = os.path.join(profraw_dir, f"{base_name}-.profraw")
        thrid_party_lib_path = ProjectUtils.get_project_3rdparty_lib_dir(ProjectUtils.get_build_work_dir(CompileKind.Coverage))
        cov_lib_path = os.path.dirname(ProjectUtils.get_project_build_shared_lib(ProjectUtils.get_build_work_dir(CompileKind.Coverage)))
        existing_ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
        ld_library_path = f"{cov_lib_path}:{thrid_party_lib_path}:{existing_ld_library_path}"

        sandbox_cmd = [
            "bwrap",
            "--ro-bind", "/", "/",       # 1. mount root directory as read-only (Read-Only)
            "--dev", "/dev",             # 2. mount /dev (program usually needs /dev/null, /dev/random)
            "--proc", "/proc",           # 3. mount /proc (if program needs to check process information)
            "--unshare-net",
            "--tmpfs", "/tmp",           # Provide an isolated in-memory /tmp for mkstemp             
            "--bind", tmp_dir, tmp_dir, # 4. mount output_dir as read-write (Read-Write)
            "--bind", profraw_dir, profraw_dir, # 5. mount profraw_dir as read-write (Read-Write)
            "--ro-bind", corpus_dir, corpus_dir, # 6. mount corpus directory as read-only (Read-Only)
            "--die-with-parent",         # 7. parent process dies, child process dies too
            "--new-session",           # 8. create new process session
            "--setenv", "LLVM_PROFILE_FILE", profile_file,
            "--setenv", "LD_LIBRARY_PATH", ld_library_path,]
        cmd = sandbox_cmd + [
            fuzzer_cov, corpus_file, "-timeout=10", "-ignore_timeouts=1", "-ignore_crashes=1", "-ignore_ooms=1", "-runs=0"
        ]

        print_debug(f"Executing command on {id}-th corpus file: {" ".join(cmd)}")
        try:
            output = subprocess.run(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=tmp_dir, timeout=120
            )
        except subprocess.TimeoutExpired:
            print_debug(f"[+] Timeout expired for fuzzer {fuzzer_id} on corpus file {corpus_file}! Skip this corpus file!")
            return
        if output.returncode != 0:
            err_msg = output.stderr.decode("utf-8", errors="ignore")
            print_debug(f"[!] WARNING: Failed to execute coverage collection command for fuzzer {fuzzer_id} on corpus file {corpus_file} due to unknown reason!\n{err_msg}")
        #check_subprocess_output(output)

    @staticmethod
    def safety_merge_llvm_cov_profdata(profraw_dir: str, profdata_file: str):
        if len(os.listdir(profraw_dir)) == 0:
            print(f"[!] WARNING: No profraw files found in {profraw_dir}! Skip this fuzzer!")
            return
        cmd = ["llvm-profdata", "merge", "-sparse", profraw_dir, "-o", profdata_file]
        print_debug(f"Executing command: {cmd}")
        output = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=profraw_dir
        )
        #check_subprocess_output(output)
        if output.returncode != 0:
            err_msg = output.stderr.decode("utf-8")
            corrupted_warning_pattern = r"warning:\s+(?P<path>.*?):\s+"
            match = re.search(corrupted_warning_pattern, err_msg)
            if match:
                corrupted_file = match.group('path')
                print_debug(f"[+] Found corrupted file: {corrupted_file}, removing it...")
                os.remove(os.path.join(profraw_dir, corrupted_file))
                return CoverageUtils.safety_merge_llvm_cov_profdata(profraw_dir, profdata_file)
            else:
                raise Exception(f"[!] WARNING: Failed to merge profdata files due to unknown reason!\n{err_msg}")


    @staticmethod
    def export_llvm_cov_to_json(coverage_dir: str):
        profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)
        if not os.path.exists(profdata):
            print(f"[!] ERROR: {profdata} does not exist! Skip this fuzzer!")
            return
        shared_lib = ProjectUtils.get_project_build_shared_lib(ProjectUtils.get_build_work_dir(CompileKind.Coverage))
        cmd = [
            "llvm-cov",
            "export",
            "-format=text",
            f"-instr-profile={profdata}",
            f"-object={shared_lib}",
        ]
        print_debug(f"Executing text report generation command: {cmd}")
        output = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=coverage_dir
        )
        check_subprocess_output(output)
        with open(os.path.join(coverage_dir, LLVM_COV_JSON_FILE_NAME), "w") as f:
            f.write(output.stdout.decode("utf-8"))

    @staticmethod
    def _export_llvm_cov_summary_to_json(coverage_dir: str) -> dict:
        profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)
        if not os.path.exists(profdata):
            print(f"[!] ERROR: {profdata} does not exist! Skip this fuzzer!")
            return
        shared_lib = ProjectUtils.get_project_build_shared_lib(ProjectUtils.get_build_work_dir(CompileKind.Coverage))
        cmd = [
            "llvm-cov",
            "export",
            "-summary-only",
            "-format=text",
            f"-instr-profile={profdata}",
            shared_lib,
        ]
        print_debug(f"Executing text report generation command: {cmd}")
        output = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=coverage_dir
        )
        check_subprocess_output(output)
        with open(os.path.join(coverage_dir, LLVM_COV_SUMMARY_FILE_NAME), "w") as f:
            f.write(output.stdout.decode("utf-8"))
        return json.loads(output.stdout.decode("utf-8"))

    @staticmethod
    def export_llvm_cov_raw_text(fuzz_target: str, coverage_dir: str):
        profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)
        cmd = [
            "llvm-cov",
            "show",
            "-format=text",
            f"-output-dir={coverage_dir}",
            "-Xdemangler",
            "c++filt",
            f"-instr-profile={profdata}",
            fuzz_target,
        ]
        print_debug(f"Executing text report generation command: {cmd}")
        output = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=coverage_dir
        )
        check_subprocess_output(output)

    @staticmethod
    def export_llvm_cov_html(fuzz_target: str, coverage_dir: str):
        profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)
        cmd = [
            "llvm-cov",
            "show",
            "-format=html",
            f"-output-dir={coverage_dir}",
            "-Xdemangler",
            "c++filt",
            f"-instr-profile={profdata}",
            fuzz_target,
        ]
        print_debug(f"Executing HTML report generation command: {cmd}")
        output = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=coverage_dir
        )
        check_subprocess_output(output)
    
    @staticmethod
    def export_llvm_cov_summary(fuzz_target: str, coverage_dir: str, summary_file: str):
        profdata = os.path.join(coverage_dir, PROFDATA_FILE_NAME)
        cmd = [
            "llvm-cov",
            "export",
            "-summary-only",
            f"-instr-profile={profdata}",
            fuzz_target,
        ]
        print_debug(f"Executing summary report generation command: {cmd}")
        output = subprocess.run(
            cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=coverage_dir
        )
        check_subprocess_output(output)
        with open(summary_file, "w") as f:
            f.write(output.stdout.decode("utf-8"))


    @staticmethod
    def generate_html(fuzz_target: str, coverage_dir: str):
        print_debug(f"Generating HTML report for fuzzer {fuzz_target}...")
        platform = "linux"
        platform_path = os.path.join(coverage_dir, platform)
        os.makedirs(platform_path, exist_ok=True)
        CoverageUtils.export_llvm_cov_html(fuzz_target, coverage_dir)

        CoverageUtils.export_llvm_cov_raw_text(fuzz_target, coverage_dir)

        summary_file = os.path.join(platform_path, "summary.json")
        CoverageUtils.export_llvm_cov_summary(fuzz_target, coverage_dir, summary_file)

        coverage_util_cmd = [
            "coverage_utils_process",
            "-v",
            "post_process",
            "-src-root-dir=/",
            f"-summary-file={summary_file}",
            f"-output-dir={coverage_dir}",
        ]
        print_debug(f"Executing coverage post-process command: {coverage_util_cmd}")

        output = subprocess.run(
            coverage_util_cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=coverage_dir,
        )
        #check_subprocess_output(output)
        if output.returncode != 0:
            err_msg = output.stderr.decode("utf-8")
            print(f"[!] WARNING: [For developer message, agents ignores] Failed to post-process coverage data due to unknown reason!\n{err_msg}")
            return
        CoverageUtils.source_coverage_process(coverage_dir)

    @staticmethod
    def source_coverage_process(coverage_dir: str):
        # source-level code coverage structure
        source_coverage_dir = os.path.join(coverage_dir, SOURCE_COVERAGE_DIR_NAME)
        os.makedirs(source_coverage_dir, exist_ok=True)

        text_cov_dir = os.path.join(coverage_dir, "coverage")
        html_report_dir = os.path.join(coverage_dir, "linux")

        # handle for harness coverage files
        text_cov_harness_dir = CoverageUtils.find_harness_coverage_dir(text_cov_dir)
        report_harness_dir = CoverageUtils.find_harness_coverage_dir(html_report_dir)
        if text_cov_harness_dir is not None and report_harness_dir is not None:
            CoverageUtils.copy_harness_coverage_files(source_coverage_dir, text_cov_harness_dir, report_harness_dir)

        text_cov_root_dir = os.path.join(text_cov_dir, "root", "src")
        report_root_dir = os.path.join(html_report_dir, "root", "src")
        CoverageUtils.merge_two_dirs(text_cov_root_dir, source_coverage_dir)
        CoverageUtils.merge_two_dirs(report_root_dir, source_coverage_dir)
        #shutil.rmtree(text_cov_dir, ignore_errors=True)
        #shutil.rmtree(html_report_dir, ignore_errors=True)

    @staticmethod
    def find_harness_coverage_dir(entry: str) -> Optional[str]:
        for root, dirs, _ in os.walk(entry):
            for dir in dirs:
                if dir == "harnesses":
                    return os.path.join(root, dir)
        return None

    @staticmethod
    def copy_harness_coverage_files(source_coverage_dir: str, text_cov_harness_dir: str, report_harness_dir: str):
        harness_id = os.path.dirname(source_coverage_dir).split("/")[-1][-3:]
        for file in os.listdir(text_cov_harness_dir):
            shutil.copyfile(os.path.join(text_cov_harness_dir, file), os.path.join(source_coverage_dir, file))

        for id, file in enumerate(os.listdir(report_harness_dir)):
            shutil.copyfile(os.path.join(report_harness_dir, file), os.path.join(source_coverage_dir, f"harness_{harness_id}.html"))

    @staticmethod
    def merge_two_dirs(src_dir: str, dst_dir: str):
        print_debug(f"Merging {src_dir} to {dst_dir}")
        for root, dirs, files in os.walk(src_dir):
            # 计算相对路径
            rel_path = os.path.relpath(root, src_dir)
            if rel_path == ".":
                rel_path = ""
            
            # 创建目标目录
            dst_root = os.path.join(dst_dir, rel_path)
            if not os.path.exists(dst_root):
                os.makedirs(dst_root)
            
            # 复制文件
            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(dst_root, file)
                shutil.copy2(src_file, dst_file)


    @staticmethod
    def load_llvm_cov_functions():
        coverage_dir = ProjectUtils.get_project_coverage_dir()
        llvm_cov = os.path.join(coverage_dir, "dumps", "llvm_cov.json")
        if not os.path.exists(llvm_cov):
            raise Exception(f"[!] Error: {llvm_cov} does not exist!")
        with open(llvm_cov, "r") as f:
            data = json.load(f)
        functions = data["data"][0]["functions"]
        names = []
        for func in functions:
            func_name = func["name"]
            if func_name.find(":") != -1:
                func_name = func_name.split(":")[-1]  # remove namespace
            names.append(func_name)
        if FUZZAGENT_DEBUG:
            print(f"Loaded {len(names)} functions from {llvm_cov}")
            print(f"Functions: {names}")
        return names

    @staticmethod
    def get_available_fuzzers() -> list[int]:
        print_debug("[*] Analyzing fuzzer status...")
        fuzzer_ids = []
        fuzz_profile = ProjectUtils.get_fuzzer_profile()
        for fuzzer_id, fuzzer_info in fuzz_profile.fuzzers.items():
            if fuzzer_info.state == FuzzerExecutionState.NOT_EXECUTED:
                print(f"[+] Fuzzer {fuzzer_id:03d} is not executed yet! Skip this fuzzer!")
                continue
            if fuzzer_info.state == FuzzerExecutionState.FIXED:
                print(f"[+] Fuzzer {fuzzer_id:03d} is fixed but not executed yet! Skip this fuzzer!")
                continue
            fuzzer_ids.append(fuzzer_id)
            print_debug(f"[+] Fuzzer {fuzzer_id:03d} is available in state :{fuzzer_info.state}")
        print_debug(f"[+] Analysis completed!")
        return fuzzer_ids

