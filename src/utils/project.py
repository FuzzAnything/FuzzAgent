import os, sys
from pathlib import Path
import shutil
import subprocess
from src.utils.vms import VMS
import pydantic
from enum import Enum
import json

# Project directory paths
_script_path = os.path.realpath(__file__)
_script_dir = os.path.dirname(_script_path)
_root_dir = Path(_script_dir).parent.parent
_output_dir = os.path.join(_root_dir, "output")
_src_root_dir = "/src/"
_fuzz_src_dir = "/root/src/"

def get_fuzz_library_src():
    # The fuzz library source directory should contain only one directory
    dirs = os.listdir(_fuzz_src_dir)
    if len(dirs) != 1:
        raise Exception(f"Fuzz library source directory {_fuzz_src_dir} should contain only one directory")
    return os.path.join(_fuzz_src_dir, dirs[0])

def copy_project_source():
    """
    Copy the project source code from the input source directory to the destination directory.
    The destination directory is set as the SRC environment variable.
    """
    print("[+] Copying project source code...")
    if os.path.exists(_fuzz_src_dir):
        shutil.rmtree(_fuzz_src_dir)
    shutil.copytree(_src_root_dir, _fuzz_src_dir)

    print(f"[+] The target project has been copied to {_fuzz_src_dir}.\n$SRC={_fuzz_src_dir}")

# Copy the project source code
copy_project_source()
_src_dir = os.path.join(_fuzz_src_dir, os.path.basename(get_fuzz_library_src()))
os.environ["SRC"] = _src_dir
_project_output_dir = os.path.join(_output_dir, os.path.basename(get_fuzz_library_src()))

PROJECT_VMS = VMS(_project_output_dir)


def is_autoclean_enabled():
    if os.environ.get("FUZZAGENT_AUTO_CLEAN", "0") == "1":
        return True
    return False


def init_environment():
    """
    Initialize the environment for the project by setting up necessary directories and environment variables.
    If `delete` is True, existing directories will be deleted and recreated.
    """
    # Ask the user if they want to delete existing output files
    if is_autoclean_enabled():
        delete = True
    else:
        ins = input(
            "Do you want to delete existing output files? Enter 1 to delete, others not delete:"
        )
        if ins.strip() == "1":
            delete = True
        else:
            delete = False

    print("[+] Initializing environment...")

    # Clean up the /tmp directory if delete is True
    if delete:
        tmp_dir = "/tmp"
        print("[+] Deleting temperorary files under /tmp ...")
        for entry in os.listdir(tmp_dir):
            if entry not in ["introspector", "wllvm", "last_edit_backup.env"]:
                continue
            entry_path = os.path.join(tmp_dir, entry)
            try:
                if os.path.isfile(entry_path) or os.path.islink(entry_path):
                    os.remove(entry_path)
                elif os.path.isdir(entry_path):
                    shutil.rmtree(entry_path)
            except Exception as e:
                print(f"[!] Failed to delete {entry_path}: {e}")

    # Set up environment variables
    os.environ["CC"] = "clang"
    os.environ["CXX"] = "clang++"
    os.environ["CFLAGS"] = "-O0"
    os.environ["CXXFLAGS"] = "-O0"
    os.environ["FUZZ_BUILD_DIR"] = _project_output_dir
    os.environ["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    os.environ["AFL_BENCH_UNTIL_CRASH"] = "1"
    os.environ["AFL_SKIP_CPUFREQ"] = "1"
    print(
        f"Environment variables set:\nCC={os.environ['CC']}\nCXX={os.environ['CXX']}\nCFLAGS={os.environ['CFLAGS']}\nCXXFLAGS={os.environ['CXXFLAGS']}\nFUZZ_BUILD_DIR={os.environ['FUZZ_BUILD_DIR']}"
    )

    # Create and set project-specific directories
    print("[+] Initializing working directories...")
    if os.getenv("SRC") is None:
        print("SRC is not set. Please set it in the .env file.")
        sys.exit(1)
    
    if os.path.exists(_project_output_dir) and delete:
        shutil.rmtree(_project_output_dir, ignore_errors=True)
    os.makedirs(_project_output_dir, exist_ok=True)
    os.environ["OUTPUT"] = _project_output_dir

    project_build_dir = os.path.join(_project_output_dir, "build")
    if os.path.exists(project_build_dir) and delete:
        shutil.rmtree(project_build_dir)
    os.makedirs(project_build_dir, exist_ok=True)
    os.environ["PROJECT_BUILD_DIR"] = project_build_dir


    project_fuzzer_build_dir = os.path.join(project_build_dir, "sanitizer")
    project_sanitizer_build_dep_dir = os.path.join(project_build_dir, "sanitizer", "dependencies")
    if os.path.exists(project_fuzzer_build_dir) and delete:
        shutil.rmtree(project_fuzzer_build_dir)
    os.makedirs(project_fuzzer_build_dir, exist_ok=True)
    os.makedirs(project_sanitizer_build_dep_dir, exist_ok=True)
    os.environ["LIB_FUZZER_LINK_BUILD_DIR"] = project_fuzzer_build_dir
    os.environ["WORK"] = project_fuzzer_build_dir
    os.environ["WORK_DEP"] = project_sanitizer_build_dep_dir



    project_cov_build_dir = os.path.join(project_build_dir, "coverage")
    project_cov_build_dep_dir = os.path.join(project_build_dir, "coverage", "dependencies")
    if os.path.exists(project_cov_build_dir) and delete:
        shutil.rmtree(project_cov_build_dir)
    os.makedirs(project_cov_build_dir, exist_ok=True)
    os.makedirs(project_cov_build_dep_dir, exist_ok=True)
    os.environ["LIB_COVERAGE_BUILD_DIR"] = project_cov_build_dir

    project_harness_dir = os.path.join(_project_output_dir, "harnesses")
    if os.path.exists(project_harness_dir) and delete:
        shutil.rmtree(project_harness_dir)
    os.makedirs(project_harness_dir, exist_ok=True)
    os.environ["HARNESS_DIR"] = project_harness_dir

    fuzzer_dir = os.path.join(_project_output_dir, "fuzzers")
    if os.path.exists(fuzzer_dir) and delete:
        shutil.rmtree(fuzzer_dir)
    os.makedirs(fuzzer_dir, exist_ok=True)
    os.environ["FUZZER_DIR"] = fuzzer_dir

    dictionary_dir = os.path.join(_project_output_dir, "dictionary")
    if os.path.exists(dictionary_dir) and delete:
        shutil.rmtree(dictionary_dir)
    os.makedirs(dictionary_dir, exist_ok=True)
    os.environ["DICTIONARY_DIR"] = dictionary_dir

    seed_dir = os.path.join(_project_output_dir, "seeds")
    if os.path.exists(seed_dir) and delete:
        shutil.rmtree(seed_dir)
    os.makedirs(seed_dir, exist_ok=True)
    os.environ["SEED_DIR"] = seed_dir

    coverage_guidance_dir = os.path.join(_project_output_dir, "coverage_guidance")
    if os.path.exists(coverage_guidance_dir) and delete:
        shutil.rmtree(coverage_guidance_dir)
    os.makedirs(coverage_guidance_dir, exist_ok=True)
    os.environ["COVERAGE_GUIDANCE_DIR"] = coverage_guidance_dir


    crash_report_dir = os.path.join(_project_output_dir, "crash_reports")
    if os.path.exists(crash_report_dir) and delete:
        shutil.rmtree(crash_report_dir)
    os.makedirs(crash_report_dir, exist_ok=True)
    os.environ["CRASH_REPORT"] = crash_report_dir

    cache_dir = get_project_cache_dir()
    if os.path.exists(cache_dir) and delete:
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["CACHE_DIR"] = cache_dir
    print("[+] Working directories initialized.")
    copy_fuzzer_wrapper_to_cache()
    
    if delete:
        print("[+] Deleting existing VMS...")
        PROJECT_VMS.delete_vms()
        print("[+] VMS deleted.\n[+] Initializing new VMS...")
        PROJECT_VMS.init_vms()
        print("[+] New VMS initialized.")
    print("[+] Environment initialization completed.")


class FuzzerExecutionState(Enum):
    NOT_EXECUTED = "NOT_EXECUTED"
    CRASHED = "CRASHED"
    HARNESS_BUG = "HARNESS_BUG"
    LIBRARY_BUG = "LIBRARY_BUG"
    PLATEAU = "PLATEAU"
    FIXED = "FIXED"

class FuzzerExecutionInfo(pydantic.BaseModel):
    fuzzer_id: int
    state: FuzzerExecutionState
    execution_time: float
    coverage: int
    crashes: int
    finish_time: str = ""


class FuzzProfile(pydantic.BaseModel):
    fuzzers: dict[int, FuzzerExecutionInfo]

# Helper functions to get project directories and names
def get_project_name():
    """
    Get the name of the project from the SRC environment variable.
    """
    return os.path.basename(get_fuzz_library_src())


def get_project_output_dir() -> str:
    if not os.path.exists(_project_output_dir):
        raise Exception(f"Project build directory {_project_output_dir} does not exist")
    return _project_output_dir


def get_project_cache_dir() -> str:
    cache_dir = os.path.join(_project_output_dir, ".cache")
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_log_dir() -> str:
    log_dir = os.path.join(get_project_cache_dir(), "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    return log_dir

def get_agent_summary_file() -> str:
    return os.path.join(get_project_cache_dir(), "agent_summary.json")


def get_project_source_dir() -> str:
    """
    Get the source directory for the project.
    """
    project_dir = os.getenv("SRC")
    if not project_dir or not os.path.exists(project_dir):
        raise Exception(f"Project source directory {project_dir} does not exist")
    return project_dir


def get_project_harness_dir() -> str:
    """
    Get the directory containing harness files for the project.
    """
    harness_dir = os.getenv("HARNESS_DIR")
    if not harness_dir or not os.path.exists(harness_dir):
        raise Exception(f"Project harness directory {harness_dir} does not exist")
    return harness_dir


def get_project_header_include_dir() -> str:
    """
    Get the directory containing header files for the project.
    """
    work_dir = os.getenv("WORK")
    if not work_dir or not os.path.exists(work_dir):
        raise Exception(
            "WORK environment variable is not set or work directory does not exist"
        )
    header_dir = os.path.join(work_dir, "include")
    if not os.path.exists(header_dir):
        raise Exception(f"Header directory {header_dir} does not exist")
    return header_dir


def get_project_lib_dir() -> str:
    """
    Get the directory containing fuzzer files for the project.
    """
    work_dir = os.getenv("WORK")
    if not work_dir or not os.path.exists(work_dir):
        raise Exception(
            "WORK environment variable is not set or work directory does not exist"
        )
    lib_dir = os.path.join(work_dir, "lib")
    if not os.path.exists(lib_dir):
        raise Exception(f"Lib directory {lib_dir} does not exist")
    return lib_dir


def get_project_fuzzer_dir() -> str:
    """
    Get the directory containing fuzzer files for the project.
    """
    fuzzer_dir = os.getenv("FUZZER_DIR")
    if not fuzzer_dir or not os.path.exists(fuzzer_dir):
        raise Exception(
            "FUZZER_DIR environment variable is not set or fuzzer directory does not exist"
        )
    return fuzzer_dir


def get_project_crash_dir() -> str:
    """
    Get the directory containing crash files for the project.
    """
    crash_dir = os.getenv("CRASH")
    if not crash_dir or not os.path.exists(crash_dir):
        raise Exception(
            "CRASH environment variable is not set or crash directory does not exist"
        )
    return crash_dir


def get_project_crash_report_dir() -> str:
    """
    Get the directory containing crash report files for the project.
    """
    crash_report_dir = os.getenv("CRASH_REPORT")
    if not crash_report_dir or not os.path.exists(crash_report_dir):
        raise Exception(
            "CRASH_REPORT environment variable is not set or crash report directory does not exist"
        )
    return crash_report_dir

def get_project_coverage_guidance_dir() -> str:
    """
    Get the directory containing coverage guidance files for the project.
    """
    coverage_guidance_dir = os.getenv("COVERAGE_GUIDANCE_DIR")
    if not coverage_guidance_dir or not os.path.exists(coverage_guidance_dir):
        raise Exception(
            "COVERAGE_GUIDANCE_DIR environment variable is not set or coverage guidance directory does not exist"
        )
    return coverage_guidance_dir

def copy_fuzzer_wrapper_to_cache():
    """
    Copy the fuzzer wrapper file to the cache directory.
    """
    wrapper_file = os.path.join(_root_dir, "src", "utils", "fuzz_wrapper.cpp")
    if not os.path.exists(wrapper_file):
        raise Exception(f"Fuzz wrapper file {wrapper_file} does not exist")
    shutil.copy(wrapper_file, os.path.join(get_project_cache_dir(), "fuzz_wrapper.cpp"))

def get_fuzzer_stat_file() -> str:
    return os.path.join(get_project_cache_dir(), "fuzzer_stat.json")

def get_fuzzer_profile() -> FuzzProfile:
    if not os.path.exists(get_fuzzer_stat_file()):
        return FuzzProfile(fuzzers={})
    with open(get_fuzzer_stat_file(), "r") as f:
        stat = json.load(f)
    return FuzzProfile.model_validate(stat)