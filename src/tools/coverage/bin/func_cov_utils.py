from typing import List
import os
import math
from header_analysis import get_public_apis
from project_utils import ProjectUtils, FUZZAGENT_DEBUG
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import os
from llvm_cov import LLVM_COV_DATA
from project_utils import ProjectUtils
from call_graph_analysis import parse_call_graph
from header_analysis import get_public_apis
from harness_analysis import extract_function_calls
from functools import lru_cache
import networkx as nx
import random

MAX_FUNCTION_TO_CALCULATE = 1000

class FunctionCoverage():
    func_name: str = Field(alias="Func name")
    filename: str = Field(alias="Functions filename")
    call_depth: int = Field(alias="Function call depth")
    reached_by_fuzzers: List[str] = Field(alias="Reached by Fuzzers")
    hit_count: int = Field(alias="Fuzzers runtime hit")
    lines_hit_percent: float = Field(alias="Func lines hit %")
    branch_complexity: int = Field(alias="Cyclomatic complexity")
    accumulated_branch_complexity: int = Field(alias="Accumulated cyclomatic complexity")
    undiscovered_accumulated_complexity: int = Field(alias="Undiscovered complexity")
    reached_by_closest_api: str = Field(alias="Reached by APIs")


    def __init__(self, func_name: str, filename: str, call_depth: int, reached_by_fuzzers: List[str], hit_count: int, branch_complexity: int, covered_branches: int, accumulated_branch_complexity: int, undiscovered_accumulated_complexity: int, reached_by_closest_api: str):
        self.func_name = func_name
        self.filename = filename
        self.call_depth = call_depth
        self.reached_by_fuzzers = reached_by_fuzzers
        self.hit_count = hit_count
        self.branch_complexity = branch_complexity
        self.accumulated_branch_complexity = accumulated_branch_complexity
        self.undiscovered_accumulated_complexity = undiscovered_accumulated_complexity
        self.reached_by_closest_api = reached_by_closest_api
        self.lines_hit_percent = covered_branches * 100 / self.branch_complexity if self.branch_complexity > 0 else 1



    def get_display_info(self) -> str:
        display_func_name = self.func_name.split(":")[-1] if ":" in self.func_name else self.func_name
        return f"|{display_func_name} | {self.filename} | {self.reached_by_fuzzers} | {self.call_depth} | {self.reached_by_closest_api} | {self.hit_count} | {self.lines_hit_percent} | {self.branch_complexity} | {self.accumulated_branch_complexity} | {self.undiscovered_accumulated_complexity}"

    def get_api_display_info(self) -> str:
        return f"|{self.func_name} | {self.filename} | {self.reached_by_fuzzers} | {self.hit_count} | {self.lines_hit_percent} | {self.branch_complexity} | {self.accumulated_branch_complexity} | {self.undiscovered_accumulated_complexity}"


class FunctionCoverageCollection():
    functions: List[FunctionCoverage]
    COVERAGE_PAGE_SIZE = 50


    def __init__(self, coverage_dir: str, only_api: bool = False):
        self.coverage_dir = coverage_dir
        import time
        self.llvm_cov_data = self.parse_llvm_cov_data()
        dot_path = ProjectUtils.get_project_wllvm_callgraph_file()
        self.call_graph = parse_call_graph(dot_path)
        self.public_apis = get_public_apis()
        if only_api:
            self.filter_llvm_cov_data_by_apis()
        else:
            self.filter_out_llvm_cov_data_by_apis()
        self.harnesses = ProjectUtils.list_all_harnesses()
        self.harnesses_apis = self.get_harnesses_apis()
        self.functions = self.parse_function_coverage()

    def parse_llvm_cov_data(self):
        llvm_cov_data_file = os.path.join(self.coverage_dir, "llvm_cov.json")
        llvm_cov_data = LLVM_COV_DATA(llvm_cov_data_file)
        return llvm_cov_data

    def filter_llvm_cov_data_by_apis(self):
        functions = []
        for function in self.llvm_cov_data.functions:
            if function.name in self.public_apis:
                functions.append(function)
        self.llvm_cov_data.functions = functions
    
    def filter_out_llvm_cov_data_by_apis(self):
        functions = []
        for function in self.llvm_cov_data.functions:
            if function.name not in self.public_apis:
                functions.append(function)
        self.llvm_cov_data.functions = functions

    def filter_functions_by_max_function_to_calculate(self):
        if len(self.llvm_cov_data.functions) > MAX_FUNCTION_TO_CALCULATE:
            return random.sample(self.llvm_cov_data.functions, MAX_FUNCTION_TO_CALCULATE)
        return self.llvm_cov_data.functions

    def parse_function_coverage(self):
        function_coverage = []
        for function in self.filter_functions_by_max_function_to_calculate():
            filename = function.filenames[0]
            hit_count = function.count
            branch_complexity = function.calculate_branch_complexity()
            covered_branch = function.calculate_covered_branch_count()
            accumulated_branch_complexity, covered_accumulated_branch_complexity = self.calculate_accumulated_branch_complexity(function.name)
            undiscovered_accumulated_complexity = accumulated_branch_complexity - covered_accumulated_branch_complexity
            call_depth, reached_by_closest_api = self.calculate_call_depth_and_apis(function.name)
            reached_by_fuzzers = self.calculate_reached_by_fuzzers(function.name)
            function_coverage.append(FunctionCoverage(function.name, filename, call_depth, reached_by_fuzzers, hit_count, branch_complexity, covered_branch, accumulated_branch_complexity, undiscovered_accumulated_complexity, reached_by_closest_api))
        random.shuffle(function_coverage)
        function_coverage.sort(key=lambda x: (x.hit_count, len(x.reached_by_fuzzers), -x.undiscovered_accumulated_complexity))
        return function_coverage
    
    @lru_cache(maxsize=None) 
    def _get_function_metrics(self, function_name: str):
        """
        Helper function: get the complexity metrics of a single function.
        Separate this logic and cache it because the query of llvm_cov may involve fileIO, which is slow.
        """
        function_coverage = self.llvm_cov_data.get_function_coverage(function_name)
        if function_coverage is not None:
            return (function_coverage.calculate_branch_complexity(), 
                    function_coverage.calculate_covered_branch_count())
        return (0, 0)

    def calculate_accumulated_branch_complexity(self, function_name: str):
        accumulated_branch_complexity = 0
        covered_accumulated_branch_complexity = 0
        
        if self.call_graph.get_node_index(function_name) is None:
            return accumulated_branch_complexity, covered_accumulated_branch_complexity
            
        reachable_funcs = self.call_graph.get_all_reachable_functions(function_name)
        
        for function in reachable_funcs:
            complexity, covered = self._get_function_metrics(function)
            accumulated_branch_complexity += complexity
            covered_accumulated_branch_complexity += covered
            
        return accumulated_branch_complexity, covered_accumulated_branch_complexity

    def calculate_call_depth_and_apis(self, function_name: str):
        if self.call_graph.get_node_index(function_name) is None:
            return 0, ""

        min_depth = float('inf')
        closest_api = ""
        
        # 1. Create reversed graph (view, zero copy, fast)
        reversed_graph = self.call_graph.graph.reverse(copy=False)
        
        try:
            # 2. Start from the target function and perform single-source shortest path search
            # This will return a dictionary: {node: length}, containing all nodes reachable from function_name and their distances
            lengths = nx.single_source_shortest_path_length(reversed_graph, function_name, cutoff=50)
            
            # 3. Find the nodes that are Public APIs in the results
            for api in self.public_apis:
                if api in lengths:
                    # lengths[api] is the distance (number of edges), the number of nodes needs to be +1
                    depth = lengths[api] + 1 
                    if depth < min_depth:
                        min_depth = depth
                        closest_api = api
                        
        except Exception:
            pass # 处理图异常情况

        if min_depth == float('inf'):
             return 50, ""
             
        return int(min_depth), closest_api

    def get_harnesses_apis(self):
        harnesses_apis = {}
        for harness in self.harnesses:
            harness_apis = set(extract_function_calls(harness)) & set(self.public_apis)
            harness_id = ProjectUtils.get_harness_id_from_path(harness)
            harnesses_apis[harness_id] = harness_apis
        return harnesses_apis

    def calculate_reached_by_fuzzers(self, function_name: str):
        if self.call_graph.get_node_index(function_name) is None:
            return []
        
        reached_by_fuzzers = []
        

        ancestors_set = nx.ancestors(self.call_graph.graph, function_name)
        
        ancestors_set.add(function_name)
        
        for harness, apis in self.harnesses_apis.items():
            if not ancestors_set.isdisjoint(apis):
                reached_by_fuzzers.append(harness)
                
        return reached_by_fuzzers

    def filter_functions(self, search_func: str = ''):
        if search_func == '':
            return self.functions
        return [function for function in self.functions if search_func in function.func_name]
    
    def display(self, page: int, search_func: str = ''):
        self.functions = self.filter_functions(search_func)
        header = "| Function Name | File Name | Reached by Fuzzers | Call depth | Closest API | Hit count | Func lines hit % | Branch Count | Accumulated Branch Count | Undiscovered Accumulated Branches |\n"
        splash = "|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|\n"
        print(splash)
        print(header)
        print(splash)
        for function in self.functions[(page - 1) * self.COVERAGE_PAGE_SIZE: (page) * self.COVERAGE_PAGE_SIZE]:
            display_info = function.get_display_info()
            print(display_info)
        print(splash)
        print(f"Total Functions: {len(self.functions)}, Current page: {page}, Total pages: {math.ceil(len(self.functions) / self.COVERAGE_PAGE_SIZE)}")

class APICovUtils(FunctionCoverageCollection):

    def __init__(self, coverage_dir: str):
        super().__init__(coverage_dir, True)
    
    def display(self, page: int):
        
        header = "| API Name | File Name | Reached by Fuzzers | Hit count | Func lines hit % | Branch Count | Accumulated Branch Count | Undiscovered Accumulated Branches |\n"
        splash = "|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|\n"
        print(splash)
        print(header)
        print(splash)
        for function in self.functions[(page - 1) * self.COVERAGE_PAGE_SIZE: (page) * self.COVERAGE_PAGE_SIZE]:
            display_info = function.get_api_display_info()
            print(display_info)
        print(splash)
        print(f"Total APIs: {len(self.functions)}, Current page: {page}, Total pages: {math.ceil(len(self.functions) / self.COVERAGE_PAGE_SIZE)}")