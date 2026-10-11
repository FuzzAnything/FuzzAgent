import orjson
import cxxfilt
import re
#from header_analysis import IS_CPP_PROJECT
def mangle_to_c_style(mangled_name):
    try:
        demangled = cxxfilt.demangle(mangled_name)
    except:
        return mangled_name 

    if '(' in demangled:
        demangled = demangled.split('(')[0].strip()

    while re.search(r'<[^<>]*>', demangled):
        demangled = re.sub(r'<[^<>]*>', '', demangled)
    
    if ' ' in demangled:
        demangled = demangled.split(' ')[-1]

    c_style_name = demangled.replace('::', '_')

    return c_style_name

class LLVM_COV_UNIT_META:
    count: int
    covered: int
    notcovered: int
    percent: float

    def __init__(self, json_data: dict):
        self.count = json_data.get("count", 0)
        self.covered = json_data.get("covered", 0)
        self.notcovered = json_data.get("notcovered", 0)
        self.percent = json_data.get("percent", 0.0)

class LLVM_COV_SUMMARY:
    branches: LLVM_COV_UNIT_META
    functions: LLVM_COV_UNIT_META
    instantiations: LLVM_COV_UNIT_META
    lines: LLVM_COV_UNIT_META
    regions: LLVM_COV_UNIT_META

    def __init__(self, json_data: dict):
        self.branches = LLVM_COV_UNIT_META(json_data["branches"])
        self.functions = LLVM_COV_UNIT_META(json_data["functions"])
        self.instantiations = LLVM_COV_UNIT_META(json_data["instantiations"])
        self.lines = LLVM_COV_UNIT_META(json_data["lines"])
        self.regions = LLVM_COV_UNIT_META(json_data["regions"])

class LLVM_COV_BRANCH:
    # [line_start, col_start, line_end, col_end, exec_count, false_count, fileid, expand_file_id, kind]
    # those 9 numbers idenitify an unique branch
    line_start: int
    col_start: int
    line_end: int
    col_end: int
    true_count: int
    false_count: int
    fileid: int
    expand_file_id: int
    kind: int

    def __init__(self, json_data: list[int]):
        self.line_start = json_data[0]
        self.col_start = json_data[1]
        self.line_end = json_data[2]
        self.col_end = json_data[3]
        self.true_count = json_data[4]
        self.false_count = json_data[5]
        self.fileid = json_data[6]
        self.expand_file_id = json_data[7]
        self.kind = json_data[8]


class LLVM_COV_FUNCTION:
    branches: list[LLVM_COV_BRANCH]
    count: int
    filenames: list[str]
    name: str

    def __init__(self, json_data: dict):
        self.branches = [LLVM_COV_BRANCH(branch) for branch in json_data["branches"]]
        self.count = json_data["count"]
        self.filenames = json_data["filenames"]
        self.name = json_data["name"]
        #if self.name.startswith("_ZN") and not IS_CPP_PROJECT:
        #    self.name = mangle_to_c_style(self.name)
        if self.name.find(":") != -1:
            self.name = self.name.split(":")[-1]
    
    def calculate_branch_complexity(self):
        return len(self.branches) * 2
    
    def calculate_covered_branch_count(self):
        covered_branch_count = 0
        for branch in self.branches:
            if branch.true_count > 0:
                covered_branch_count += 1
            if branch.false_count > 0:
                covered_branch_count += 1
        return covered_branch_count
    



class LLVM_COV_FILE:
    branches: list[LLVM_COV_BRANCH]
    filiename: str
    summary: LLVM_COV_SUMMARY

    def __init__(self, json_data: dict):
        self.branches = [LLVM_COV_BRANCH(branch) for branch in json_data["branches"]]
        self.filiename = json_data["filename"]
        self.summary = LLVM_COV_SUMMARY(json_data["summary"])

class LLVM_COV_DATA:
    files: list[LLVM_COV_FILE]
    functions: list[LLVM_COV_FUNCTION]
    totals: LLVM_COV_SUMMARY

    def __init__(self, json_data_file: str):
        with open(json_data_file, "rb") as f:
            llvm_cov = orjson.loads(f.read())
        data = llvm_cov["data"][0]
        self.files = [LLVM_COV_FILE(file) for file in data["files"]]
        self.functions = [LLVM_COV_FUNCTION(function) for function in data["functions"]]
        self.totals = LLVM_COV_SUMMARY(data["totals"])
    
    def get_function_coverage(self, function_name: str) -> LLVM_COV_FUNCTION | None:
        for function in self.functions:
            if function.name == function_name:
                return function
        return None
