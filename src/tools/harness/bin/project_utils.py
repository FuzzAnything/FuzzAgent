import os
import json
from enum import Enum
import subprocess
import sys
import shutil
import time
from dotenv import load_dotenv
import pydantic

WORKDIR=os.environ.get("WORKDIR", "/root/FuzzAgent")
if WORKDIR:
    load_dotenv(os.path.join(WORKDIR, ".env")) # Load environment variables before importing other modules


def no_traceback_hook(exc_type, exc_value, exc_traceback):
    print(f"{exc_type.__name__}: {exc_value}")

def check_subprocess_output(output: subprocess.CompletedProcess) -> None:
    # 70 for libfuzzer timeout, 77 for libfuzer crash
    if output.returncode != 0 and output.returncode != 70 and output.returncode != 77:
        print(f"Execute {output.args} failed!")
        if output.stderr:
            err_msg = output.stderr.decode("utf-8", errors="ignore")
            err_msg = ProjectUtils.truncate_error_message(err_msg)
            raise Exception(f"[!] ERROR: {err_msg}")
        if output.stdout:
            out_msg = output.stdout.decode("utf-8", errors="ignore")
            out_msg = ProjectUtils.truncate_error_message(out_msg)
            raise Exception(f"[!] ERROR: {out_msg}")
        raise Exception(f"[!] ERROR: Unknown error: {output.returncode}")

FUZZAGENT_DEBUG = os.getenv("FUZZAGENT_DEBUG")
if not FUZZAGENT_DEBUG:
    sys.excepthook = no_traceback_hook

def print_debug(message: str):
    if FUZZAGENT_DEBUG:
        print(f"[DEBUG] {message}")

class FuzzingEngine(Enum):
    AFLpp = "afl++"
    LibFuzzer = "libfuzzer"

def get_fuzzing_engine() -> FuzzingEngine:
    fuzzing_engine = os.getenv("FUZZING_ENGINE", "libfuzzer").lower()
    if fuzzing_engine == "afl++":
        return FuzzingEngine.AFLpp
    elif fuzzing_engine == "libfuzzer":
        return FuzzingEngine.LibFuzzer
    else:
        raise Exception(f"Unsupported fuzzing engine: {fuzzing_engine}")


_in_src_dir = "/src/"
_src_dir = "/root/src/"

BASIC_SYMBOLS = []
# Select sanitizer symbols based on SANITIZER_MODE environment variable
# SANITIZER_MODE: 0: ASAN+UBSAN, 1: MSAN+UBSAN, 2: TSAN+UBSAN
if os.environ.get("SANITIZER_MODE")  == "0":
    SANITIZER_SYMBOLS = ["__asan", "__ubsan"]
elif os.environ.get("SANITIZER_MODE")  == "1":
    SANITIZER_SYMBOLS = ["__msan", "__ubsan"]
elif os.environ.get("SANITIZER_MODE")  == "2":
    SANITIZER_SYMBOLS = ["__tsan", "__ubsan"]
else:
    SANITIZER_SYMBOLS = ["__asan", "__ubsan"]
COVERAGE_SYMBOLS = ["__llvm_covmap"]

# Compilation flags. -fPIC is required for extract shared libraries.
COMMON_FLAGS = "-g -O0 -fstandalone-debug -w -fPIC -fno-inline -fno-omit-frame-pointer -fno-optimize-sibling-calls -Wno-error=enum-constexpr-conversion -Wno-error=incompatible-function-pointer-types -Wno-error=int-conversion -Wno-error=deprecated-declarations -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=vla-cxx-extension -DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION"
BASIC_CFLAGS = f"{COMMON_FLAGS}"
BASIC_CXXFLAGS = f"{BASIC_CFLAGS}"

SANCOV_SYMBOLS = ["__sancov"]
SANCOV_CFLAGS = f"{COMMON_FLAGS} -fsanitize=address -fsanitize-coverage=trace-pc-guard"
SANCOV_CXXFLAGS = f"{SANCOV_CFLAGS}"

# Select sanitizer flags based on SANITIZER_MODE environment variable
# SANITIZER_MODE: 0: ASAN+UBSAN, 1: MSAN+UBSAN, 2: TSAN+UBSAN
if os.environ.get("SANITIZER_MODE")  == "0":
    SANITIZER_CFLAGS = f"-fsanitize=address,undefined -fno-sanitize=function -fsanitize-address-use-after-scope {COMMON_FLAGS}"
elif os.environ.get("SANITIZER_MODE")  == "1":
    SANITIZER_CFLAGS = f"-fsanitize=memory,undefined -fno-sanitize=function {COMMON_FLAGS}"
elif os.environ.get("SANITIZER_MODE")  == "2":
    SANITIZER_CFLAGS = f"-fsanitize=thread,undefined -fno-sanitize=function {COMMON_FLAGS}"
else:
    SANITIZER_CFLAGS = f"-fsanitize=address,undefined -fno-sanitize=function -fsanitize-address-use-after-scope {COMMON_FLAGS}"

if get_fuzzing_engine() == FuzzingEngine.AFLpp:
    FUZZER_CFLAGS = SANITIZER_CFLAGS
elif get_fuzzing_engine() == FuzzingEngine.LibFuzzer:
    FUZZER_CFLAGS = f"-fsanitize=fuzzer-no-link {SANITIZER_CFLAGS} "
else:
    FUZZER_CFLAGS = f"-fsanitize=fuzzer-no-link {SANITIZER_CFLAGS} "

SANITIZER_CXXFLAGS = f"{SANITIZER_CFLAGS}"
FUZZER_CXXFLAGS = f"{FUZZER_CFLAGS}"

COVERAGE_CFLAGS = f"-fprofile-instr-generate -fcoverage-mapping {COMMON_FLAGS} -mllvm -runtime-counter-relocation -pthread -Wl,--no-as-needed -Wl,-ldl -Wl,-lm -Wno-unused-command-line-argument"
COVERAGE_CXXFLAGS = f"{COVERAGE_CFLAGS} "

WLLVM_FLAGS = f"-g -O0 {COMMON_FLAGS}"
DEFAULT_DICTIONARY_FILE = "dictionary.dict"

class CompileKind(Enum):
    Basic = "basic"
    Fuzzer = "fuzzer"
    Coverage = "coverage"
    WLLVM = "wllvm"
    SanCov = "sancov"
    CMPLOG = "cmplog"
    Sanitizer = "sanitizer"



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


import alibabacloud_oss_v2 as oss

class OSSCacheKind(Enum):
    Bitcode = "bitcode"
    Callgraph = "callgraph"
    Cmplog = "cmplog"
    BuildScript = "build_script"
    APIList = "apilist"
    AFLInstrument = "AFLInstrument"

class OSSUtils:
    
    @staticmethod
    def get_oss_client() -> oss.Client | None:
        access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
        access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
        endpoint = os.getenv("OSS_ENDPOINT")
        region = os.getenv("OSS_REGION")
        if not access_key_id or not access_key_secret or not endpoint or not region:
            return None
        credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()
        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        cfg.region = region
        cfg.endpoint = endpoint
        client = oss.Client(cfg)
        return client
    
    @staticmethod
    def get_oss_bucket_name() -> str:
        bucket_name = os.getenv("OSS_BUCKET")
        if not bucket_name:
            raise Exception("OSS_BUCKET environment variable is not set")
        return bucket_name

    @staticmethod
    def is_oss_available() -> bool:
        client = OSSUtils.get_oss_client()
        if not client:
            return False
        try:
            requet = oss.ListBucketsRequest()
            client.list_buckets(requet)
            return True
        except Exception as e:
            print_debug(f"[!] Warning: OSS is not available: {e}")
            return False

    @staticmethod
    def upload_file_to_oss(bucket_name: str, object_key: str, local_file: str) -> None:
        client = OSSUtils.get_oss_client()
        if not client:
            return None
        with open(local_file, 'rb') as f:
            result = client.put_object(oss.PutObjectRequest(
                bucket=bucket_name,
                key=object_key,
                body=f,
            ))
        print_debug(f'[+] put object successfully, ETag {result}')

    @staticmethod
    def format_object_key(local_file: str, cache_kind: OSSCacheKind) -> str:
        project_name = ProjectUtils.get_project_name()
        source_dir = ProjectUtils.get_source_code_dir()
        git_describe = subprocess.check_output(["git", "describe", "--always"], cwd=source_dir).decode("utf-8").strip()
        # git_describe format: "tag-commits-ghash"
        # Extract tag by finding the second-to-last dash (e.g., "curl-8_19_0-240-gf0f0a7f7d6" -> "curl-8_19_0")
        last_dash = git_describe.rfind("-")
        if last_dash != -1:
            second_last_dash = git_describe.rfind("-", 0, last_dash)
            if second_last_dash != -1:
                git_tag = git_describe[:second_last_dash]
            else:
                git_tag = git_describe
        else:
            git_tag = git_describe
        file_name = os.path.basename(local_file)
        object_key = f"cache/{cache_kind.value}/{project_name}/{git_tag}/{file_name}"
        return object_key


    @staticmethod
    def upload_file_to_oss_cache(local_file:str, cache_kind: OSSCacheKind) -> None:
        client = OSSUtils.get_oss_client()
        if not client:
            return None
        with open(local_file, 'rb') as f:
            key = OSSUtils.format_object_key(local_file, cache_kind)
            client.put_object(oss.PutObjectRequest(
                bucket=OSSUtils.get_oss_bucket_name(),
                key=key,
                body=f,
            ))
        print_debug(f'[+] Successfully put {local_file} to OSS cache with key: {key}')
    
    @staticmethod
    def is_file_in_oss_cache(local_file: str, cache_kind: OSSCacheKind) -> bool:
        client = OSSUtils.get_oss_client()
        if not client:
            return False
        object_key = OSSUtils.format_object_key(local_file, cache_kind)
        try:
            client.get_object(oss.GetObjectRequest(
                bucket=OSSUtils.get_oss_bucket_name(),
                key=object_key,
            ))
            print_debug(f"[+] {cache_kind.value.capitalize()} file is found in OSS cache: {object_key}")
            return True
        except Exception as e:
            print_debug(f"[+] {cache_kind.value.capitalize()} file is not found in OSS cache: {object_key}.")
            return False
    
    @staticmethod
    def download_file_from_oss_cache(local_file: str, cache_kind: OSSCacheKind) -> bool:
        client = OSSUtils.get_oss_client()
        if not client:
            return False
        object_key = OSSUtils.format_object_key(local_file, cache_kind)
        try:
            client.get_object_to_file(oss.GetObjectRequest(
                bucket=OSSUtils.get_oss_bucket_name(),
                key=object_key,
            ), local_file)
            print_debug(f'[+] Download {local_file} file from OSS cache successfully: {object_key}')
            if not os.path.exists(local_file):
                print_debug(f'[!] Warning: Failed to download {local_file} file from OSS cache: {object_key}.')
                return False
        except Exception as e:
            print_debug(f'[!] Warning: Failed to download {local_file} file from OSS cache: {object_key}. Built it locally.')
            return False
        return True

class ProjectUtils:

    @staticmethod
    def copy_project_source():
        """
        Copy the project source code from the input source directory to the destination directory.
        The destination directory is set as the SRC environment variable.
        """
        project = os.listdir(_in_src_dir)[0]
        project_path = os.path.join(_in_src_dir, project)
        if not os.path.exists(_src_dir):
            os.makedirs(_src_dir)
        dst_dir = os.path.join(_src_dir, project)
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir)
        shutil.copytree(project_path, dst_dir)
        os.environ["SRC"] = dst_dir

    # Utils funcitons to manage project directories
    @staticmethod
    def get_project_name() -> str:
        """
        Get the name of the project from the SRC environment variable.
        """
        project_path = os.getenv("SRC")
        if not project_path:
            raise Exception("[!] Error: SRC environment variable is not set!")
        project_name = os.path.basename(project_path)
        if not project_name:
            raise Exception("[!] Error: Project name is not set!")
        return project_name

    @staticmethod
    def get_source_code_dir() -> str:
        src = os.getenv("SRC")
        if not src:
            raise Exception("[!] Error: $SRC has not set!")

        if not os.path.exists(src):
            raise Exception(f"[!] Error: {src} does not exist!")
        return src

    @staticmethod
    def get_project_root_dir() -> str:
        root_dir = os.getenv("OUTPUT")
        if not root_dir or not os.path.exists(root_dir):
            raise Exception(
                "[!] Error: OUTPUT environment variable is not set or output directory does not exist"
            )
        return root_dir

    # ------------------------------------------------------------
    # Project directories
    # -------------------------------------------------------

    @staticmethod
    def get_project_cache_dir() -> str:
        root_dir = ProjectUtils.get_project_root_dir()
        cache_dir = os.path.join(root_dir, ".cache")
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        return cache_dir

    @staticmethod
    def get_project_cache_seeds_dir() -> str:
        cache_seeds_dir = os.path.join(ProjectUtils.get_project_cache_dir(), "seeds")
        if not os.path.exists(cache_seeds_dir):
            os.makedirs(cache_seeds_dir, exist_ok=True)
        return cache_seeds_dir

    @staticmethod
    def get_project_cache_fuzzers_dir() -> str:
        cache_fuzzers_dir = os.path.join(ProjectUtils.get_project_cache_dir(), "fuzzers")
        if not os.path.exists(cache_fuzzers_dir):
            os.makedirs(cache_fuzzers_dir, exist_ok=True)
        return cache_fuzzers_dir

    @staticmethod
    def get_project_cache_build_dir() -> str:
        cache_build_dir = os.path.join(ProjectUtils.get_project_cache_dir(), "build")
        if not os.path.exists(cache_build_dir):
            os.makedirs(cache_build_dir, exist_ok=True)
        return cache_build_dir

    @staticmethod
    def get_cache_coverage_dir() -> str:
        cache_coverage_dir = os.path.join(ProjectUtils.get_project_cache_dir(), "coverage")
        if not os.path.exists(cache_coverage_dir):
            os.makedirs(cache_coverage_dir, exist_ok=True)
        return cache_coverage_dir
    
    @staticmethod
    def get_who_project_coverage_dir() -> str:
        who_project_coverage_dir = os.path.join(ProjectUtils.get_cache_coverage_dir(), "whole")
        if not os.path.exists(who_project_coverage_dir):
            os.makedirs(who_project_coverage_dir, exist_ok=True)
        return who_project_coverage_dir
    
    @staticmethod
    def get_fuzzer_coverage_dir(fuzzer_id: int) -> str:
        fuzzer_id_str = str(fuzzer_id).zfill(3)
        fuzzer_coverage_dir = os.path.join(ProjectUtils.get_cache_coverage_dir(), f"fuzzer_{fuzzer_id_str}")
        if not os.path.exists(fuzzer_coverage_dir):
            os.makedirs(fuzzer_coverage_dir, exist_ok=True)
        return fuzzer_coverage_dir


    @staticmethod
    def get_fuzzer_profile() -> FuzzProfile:
        if not os.path.exists(ProjectUtils.get_fuzzer_stat_file()):
            return FuzzProfile(fuzzers={})
        with open(ProjectUtils.get_fuzzer_stat_file(), "r") as f:
            stat = json.load(f)
        return FuzzProfile.model_validate(stat)

    @staticmethod
    def save_fuzzer_profile(fuzzer_profile: FuzzProfile) -> None:
        with open(ProjectUtils.get_fuzzer_stat_file(), "w") as f:
            json.dump(fuzzer_profile.model_dump(mode="json"), f, indent=4)

    @staticmethod
    def get_fuzzer_stat_file() -> str:
        return os.path.join(ProjectUtils.get_project_cache_dir(), "fuzzer_stat.json")


    @staticmethod
    def get_project_build_dir() -> str:
        build_dir = os.path.join(ProjectUtils.get_project_root_dir(), "build")
        if not os.path.exists(build_dir):
            raise Exception(f"[!] Error: Build directory does not exist: {build_dir}")
        return build_dir

    @staticmethod
    def get_project_coverage_guidance_dir() -> str:
        coverage_guidance_dir = os.path.join(ProjectUtils.get_project_root_dir(), "coverage_guidance")
        if not os.path.exists(coverage_guidance_dir):
            os.makedirs(coverage_guidance_dir, exist_ok=True)
        return coverage_guidance_dir

    @staticmethod
    def get_build_work_dir(kind: CompileKind) -> str:
        cache_build_dir = ProjectUtils.get_project_cache_build_dir()
        build_dir = ProjectUtils.get_project_build_dir()
        if kind == CompileKind.Basic:
            work_dir = os.path.join(cache_build_dir, kind.value)
        elif kind == CompileKind.SanCov:
            work_dir = os.path.join(cache_build_dir, kind.value)
        elif kind == CompileKind.WLLVM:
            work_dir = os.path.join(cache_build_dir, kind.value)
        elif kind == CompileKind.CMPLOG:
            work_dir = os.path.join(cache_build_dir, kind.value)
        elif kind == CompileKind.Fuzzer:
            work_dir = os.path.join(build_dir, kind.value)
        elif kind == CompileKind.Coverage:
            work_dir = os.path.join(build_dir, kind.value)
        elif kind == CompileKind.Sanitizer:
            work_dir = os.path.join(build_dir, kind.value)
        else:
            raise Exception(f"[!] Error: Unsupport compilation kind: {kind}")
        return work_dir

    @staticmethod
    def get_project_fuzzers_dir(check_exist: bool = True) -> str:
        fuzzers_dir = os.path.join(ProjectUtils.get_project_root_dir(), "fuzzers")
        if check_exist and not os.path.exists(fuzzers_dir):
            raise Exception(
                f"[!] Error: Fuzzers directory does not exist: {fuzzers_dir}"
            )
        return fuzzers_dir

    @staticmethod
    def get_project_dictionary_dir() -> str:
        dictionary_dir = os.path.join(ProjectUtils.get_project_root_dir(), "dictionary")
        if not os.path.exists(dictionary_dir):
            os.makedirs(dictionary_dir, exist_ok=True)
        return dictionary_dir

    
    @staticmethod
    def get_fuzzing_dictionary_file() -> str:
        dictionary_dir = ProjectUtils.get_project_dictionary_dir()
        dictionary_file = os.path.join(dictionary_dir, DEFAULT_DICTIONARY_FILE)
        if not os.path.exists(dictionary_file):
            raise Exception(f"[!] ERROR: The dictionary file is not found: {dictionary_file}. Please generate the dictionary file and try again.")
        return dictionary_file

    @staticmethod
    def get_project_coverage_dir() -> str:
        coverage_dir = os.path.join(ProjectUtils.get_cache_coverage_dir(), "whole")
        if not os.path.exists(coverage_dir):
            os.makedirs(coverage_dir, exist_ok=True)
        return coverage_dir

    @staticmethod
    def get_project_harnesses_dir() -> str:
        harnesses_dir = os.path.join(ProjectUtils.get_project_root_dir(), "harnesses")
        if not os.path.exists(harnesses_dir):
            raise Exception(
                f"[!] Error: Harnesses directory does not exist: {harnesses_dir}"
            )
        return harnesses_dir

    @staticmethod
    def get_project_build_static_lib(work_dir: str) -> str:
        lib_dir = os.path.join(work_dir, "lib")
        return ProjectUtils.get_project_static_lib_from_dir(lib_dir)
    
    @staticmethod
    def get_project_static_lib_from_dir(lib_dir: str) -> str:
        static_libs = []
        for file in os.listdir(lib_dir):
            if file.endswith(".a"):
                static_libs.append(file)
        if len(static_libs) == 0:
            raise Exception(f"No archive library found in {lib_dir}")
        if len(static_libs) == 1:
            return os.path.join(lib_dir, static_libs[0])
        lib_name = ProjectUtils.get_project_name()
        target_lib = f"{lib_name}.a" if lib_name.startswith("lib") else f"lib{lib_name}.a"
        if target_lib in static_libs:
            return os.path.join(lib_dir, target_lib)
        raise Exception(f"Multiple archive libraries found in {lib_dir}: {static_libs}")
    
    @staticmethod
    def get_project_3rdparty_work_dir(work_dir: str) -> str:
        thirdparty_dir = os.path.join(work_dir, "3rdparty")
        if not os.path.exists(thirdparty_dir):
            os.makedirs(thirdparty_dir, exist_ok=True)
        return thirdparty_dir
    
    @staticmethod
    def get_project_3rdparty_lib_dir(work_dir: str) -> str:
        thirdparty_dir = ProjectUtils.get_project_3rdparty_work_dir(work_dir)
        lib_dir = os.path.join(thirdparty_dir, "lib")
        if not os.path.exists(lib_dir):
            os.makedirs(lib_dir, exist_ok=True)
        return lib_dir
    
    @staticmethod
    def get_project_3rdparty_include_dir(work_dir: str) -> str:
        thirdparty_dir = ProjectUtils.get_project_3rdparty_work_dir(work_dir)
        include_dir = os.path.join(thirdparty_dir, "include")
        if not os.path.exists(include_dir):
            os.makedirs(include_dir, exist_ok=True)
        return include_dir


    @staticmethod
    def get_project_3rdparty_libs_from_dir(work_dir: str) -> list[str]:
        thirdparty_lib_dir = ProjectUtils.get_project_3rdparty_lib_dir(work_dir)
        if not os.path.exists(thirdparty_lib_dir) or len(os.listdir(thirdparty_lib_dir)) == 0:
            return []
        thirdparty_libs = []
        for file in os.listdir(thirdparty_lib_dir):
            if file.endswith(".a"):
                thirdparty_libs.append(os.path.join(thirdparty_lib_dir, file))
        return thirdparty_libs

    @staticmethod
    def get_project_shared_lib_from_dir(lib_dir: str) -> str:
        shared_libs = []
        for file in os.listdir(lib_dir):
            if file.endswith(".so"):
                shared_libs.append(file)
        if len(shared_libs) == 0:
            raise Exception(f"No shared library found in {lib_dir}")
        lib_name = ProjectUtils.get_project_name()
        target_lib = f"{lib_name}.so" if lib_name.startswith("lib") else f"lib{lib_name}.so"
        if target_lib in shared_libs:
            return os.path.join(lib_dir, target_lib)
        # Case-insensitive fallback: $SRC preserves source dir casing (e.g. "cJSON")
        # while CMake produces lowercase .so names (e.g. "libcjson.so"). Match
        # case-insensitively before giving up.
        target_lower = target_lib.lower()
        for file in shared_libs:
            if file.lower() == target_lower:
                return os.path.join(lib_dir, file)
        raise Exception(f"Multiple shared libraries found in {lib_dir}: {shared_libs}")

            
    @staticmethod
    def get_project_build_shared_lib(work_dir: str) -> str:
        lib_dir = os.path.join(work_dir, "lib")
        if not os.path.exists(lib_dir):
            raise Exception(f"No shared library found in {lib_dir}")
        return ProjectUtils.get_project_shared_lib_from_dir(lib_dir)

    @staticmethod
    def get_project_wllvm_callgraph_file() -> str:
        work_dir = ProjectUtils.get_build_work_dir(CompileKind.WLLVM)
        call_graph_file = (
            ProjectUtils.get_project_build_static_lib(work_dir) + ".bc.callgraph.dot"
        )
        return call_graph_file


    @staticmethod
    def get_project_seed_dir() -> str:
        seed_dir = os.path.join(ProjectUtils.get_project_root_dir(), "seeds")
        if not os.path.exists(seed_dir):
            raise Exception(f"[!] Error: Seed directory does not exist: {seed_dir}")
        return seed_dir
    
    @staticmethod
    def get_project_crash_report_dir() -> str:
        crash_report_dir = os.path.join(ProjectUtils.get_project_root_dir(), "crash_reports")
        if not os.path.exists(crash_report_dir):
            os.makedirs(crash_report_dir, exist_ok=True)
        return crash_report_dir

    # build
    @staticmethod
    def get_project_header_include_dir() -> str:
        work_dir = os.path.join(ProjectUtils.get_build_work_dir(CompileKind.Fuzzer))
        if not os.path.exists(work_dir):
            raise Exception(
                f"[!] Error: Library basic fuzzer build directory does not exist: {work_dir}"
            )
        header_dir = os.path.join(work_dir, "include")
        if not os.path.exists(header_dir):
            raise Exception(f"[!] Error: Header directory {header_dir} does not exist")
        return header_dir


    # ------------------------------------------------------------
    # Fuzzer directories
    # -------------------------------------------------------

    @staticmethod
    def get_fuzzer_str_by_id(fuzzer_id: int) -> str:
        if not isinstance(fuzzer_id, int):
            raise Exception(
                f"[!] Error: fuzzer_id must be an integer, got {type(fuzzer_id).__name__}"
            )
        return str(fuzzer_id).zfill(3)

    @staticmethod
    def get_fuzzer_dir_by_id(fuzzer_id: int, check_exist: bool = True) -> str:
        fuzzer_id_str = str(fuzzer_id).zfill(3)
        fuzzer_dir = os.path.join(
            ProjectUtils.get_project_fuzzers_dir(check_exist), f"fuzzer_{fuzzer_id_str}"
        )
        if check_exist and not os.path.exists(fuzzer_dir):
            raise Exception(f"[!] Error: Fuzzer directory does not exist: {fuzzer_dir}")
        return fuzzer_dir

    @staticmethod
    def get_fuzzer_binary_by_id(fuzzer_id: int, check_exist: bool = True) -> str:
        fuzzer_dir = ProjectUtils.get_fuzzer_dir_by_id(fuzzer_id)
        fuzzer_binary = os.path.join(fuzzer_dir, "fuzzer")
        if check_exist and not os.path.exists(fuzzer_binary):
            raise Exception(f"[!] Error: Fuzzer binary does not exist: {fuzzer_binary}")
        return fuzzer_binary

    @staticmethod
    def get_fuzzer_coverage_binary_by_id(
        fuzzer_id: int, check_exist: bool = True
    ) -> str:
        fuzzer_dir = ProjectUtils.get_cache_fuzzer_dir(fuzzer_id)
        fuzzer_binary = os.path.join(fuzzer_dir, "fuzzer_cov")
        if check_exist and not os.path.exists(fuzzer_binary):
            raise Exception(f"[!] Error: Fuzzer binary does not exist: {fuzzer_binary}")
        return fuzzer_binary

    @staticmethod
    def get_fuzzer_fuzzing_corpus_dir(fuzzer_id: int) -> str:
        fuzzer_dir = ProjectUtils.get_fuzzer_dir_by_id(fuzzer_id)
        fuzzer_corpus_dir = os.path.join(fuzzer_dir, "fuzzing_corpus")
        return fuzzer_corpus_dir

    @staticmethod
    def get_fuzzer_seeds_dir(fuzzer_id: int) -> str:
        fuzzer_dir = ProjectUtils.get_fuzzer_dir_by_id(fuzzer_id)
        fuzzer_seeds_dir = os.path.join(fuzzer_dir, "seeds")
        return fuzzer_seeds_dir

    @staticmethod
    def get_fuzzer_id_from_path(fuzzer_dir: str) -> int:
        fuzzer_name = os.path.basename(fuzzer_dir)
        fuzzer_id = fuzzer_name.removeprefix("fuzzer_")
        if len(fuzzer_id) != 3 or not fuzzer_id.isdigit():
            raise Exception(
                f"[!] Error: The format of fuzzer directory should be fuzzer_xxx (e.g., starts from fuzzer_000). Received: {fuzzer_name}"
            )
        return int(fuzzer_id)

    # harnesses
    @staticmethod
    def get_harness_path_by_id(harness_id: int) -> str:
        harness_id_str = str(harness_id).zfill(3)
        harness_dir = ProjectUtils.get_project_harnesses_dir()
        harness_path = os.path.join(harness_dir, f"harness_{harness_id_str}.cpp")
        return harness_path

    @staticmethod
    def get_harness_id_from_path(harness_path: str) -> str:
        harness_name = os.path.basename(harness_path)
        harness_id = harness_name.removeprefix("harness_").removesuffix(".cpp")
        if len(harness_id) != 3 or not harness_id.isdigit():
            raise Exception(
                f"[!] Error: The format of harness filename should be harness_xxx.cpp (e.g., starts from harness_000.cpp). Received: {harness_name}"
            )
        return harness_id

    @staticmethod
    def get_harness_path_by_fuzzer_dir(fuzzer_dir: str) -> str:
        harness_id = ProjectUtils.get_fuzzer_id_from_path(fuzzer_dir)
        return ProjectUtils.get_harness_path_by_id(int(harness_id))

    @staticmethod
    def list_all_harnesses() -> list[str]:
        harnesses = []
        harnesses_dir = ProjectUtils.get_project_harnesses_dir()
        for file in os.listdir(harnesses_dir):
            if file.endswith(".cpp"):
                harnesses.append(os.path.join(harnesses_dir, file))
        return harnesses


    @staticmethod
    def get_fuzzer_output_path(output_dir: str, compile_kind: CompileKind) -> str:
        if compile_kind == CompileKind.Coverage:
            fuzzer_name = "fuzzer_cov"
        elif compile_kind == CompileKind.Fuzzer:
            fuzzer_name = "fuzzer"
        elif compile_kind == CompileKind.Basic:
            fuzzer_name = "fuzzer"
        elif compile_kind == CompileKind.SanCov:
            fuzzer_name = "fuzzer_sancov"
        elif compile_kind == CompileKind.CMPLOG:
            fuzzer_name = "fuzzer_cmplog"
        else:
            raise Exception("Unknown compile kind")
        fuzzer_path = os.path.join(output_dir, fuzzer_name)
        return fuzzer_path


    @staticmethod
    def safe_copy_corpus_to_temp_dir(corpus_dir: str) -> str:
        temp_dir = os.path.join("/tmp", str(time.time()))
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        for file in os.listdir(corpus_dir):
            corpus_path = os.path.join(corpus_dir, file)
            dst_path = os.path.join(temp_dir, file)
            if os.path.exists(corpus_path):
                try:
                    shutil.copyfile(corpus_path, dst_path)
                except Exception as e:
                    continue
        return temp_dir

    @staticmethod
    def get_fuzzer_cache_seeds_dir(fuzzer_id: int) -> str:
        cache_seeds_dir = ProjectUtils.get_project_cache_seeds_dir()
        fuzzer_id_str = str(fuzzer_id).zfill(3)
        cache_seeds = os.path.join(cache_seeds_dir, f"{fuzzer_id_str}")
        if not os.path.exists(cache_seeds):
            os.makedirs(cache_seeds, exist_ok=True)
        return cache_seeds

    @staticmethod
    def get_cache_fuzzer_dir(fuzzer_id: int) -> str:
        cache_fuzzers_dir = ProjectUtils.get_project_cache_fuzzers_dir()
        fuzzer_id_str = str(fuzzer_id).zfill(3)
        cache_fuzzers = os.path.join(cache_fuzzers_dir, f"{fuzzer_id_str}")
        if not os.path.exists(cache_fuzzers):
            os.makedirs(cache_fuzzers, exist_ok=True)
        return cache_fuzzers

    @staticmethod
    def get_fuzzer_crash_dir(fuzzer_id: int) -> str:
        fuzzer_dir = ProjectUtils.get_fuzzer_dir_by_id(fuzzer_id)
        crash_dir = os.path.join(fuzzer_dir, "crashes")
        if not os.path.exists(crash_dir):
            os.makedirs(crash_dir, exist_ok=True)
        return crash_dir
    
    @staticmethod
    def get_afl_cache_fuzzer_queue_dirs(fuzzer_id: int) -> list[str]:
        fuzzer_dir = ProjectUtils.get_cache_fuzzer_dir(fuzzer_id)
        output_dir = os.path.join(fuzzer_dir, "output")
        if not os.path.exists(output_dir):
            return []
        queue_dirs = []
        for entry in os.listdir(output_dir):
            instance_dir = os.path.join(output_dir, entry)
            queue_dir = os.path.join(instance_dir, "queue")
            if os.path.exists(queue_dir):
                queue_dirs.append(queue_dir)
        return queue_dirs

    @staticmethod
    def truncate_error_message(err_msg: str) -> str:
        if not err_msg:
            return ""
            
        lines = err_msg.splitlines()
        
        if len(lines) <= 15:
            return err_msg
            
        head = lines[:10]
        tail = lines[-5:]
        
        truncated_msg = (
            "\n".join(head) + 
            f"\n\n[... Truncated {len(lines) - 15} lines for brevity ...]\n\n" + 
            "\n".join(tail)
        )
        
        return truncated_msg

    @staticmethod
    def get_project_cache_api_list_file() -> str:
        cache_api_list_file = os.path.join(ProjectUtils.get_project_cache_dir(), "api_list.txt")
        return cache_api_list_file
    
    @staticmethod
    def is_huge_library() -> bool:
        src_dir = ProjectUtils.get_source_code_dir()
        cmd = ["scc", "-f", "json", src_dir]
        total_lines = 0
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            scc_result = json.loads(output)
            for entry in scc_result:
                total_lines += entry.get("Code", 0)
        except subprocess.CalledProcessError:
            pass
        if total_lines > 1000000:  # If the codebase has more than 1 million lines of code, we consider it a huge library
            return True
        return False