#!/usr/bin/env python3
import os
import subprocess
import clang.cindex
from clang.cindex import Index, CursorKind, StorageClass, AccessSpecifier
from turtle import st
from project_utils import CompileKind, ProjectUtils, FUZZAGENT_DEBUG, print_debug, OSSCacheKind, OSSUtils
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple, Set
from pathlib import Path
from collections import deque
from clang.cindex import Index, CursorKind, TypeKind, StorageClass

# Environment preparation before analysis
def get_project_coverage_header_include_dir() -> str:
    work_dir = os.path.join(ProjectUtils.get_build_work_dir(CompileKind.Coverage))
    if not os.path.exists(work_dir):
        raise Exception(
            f"[!] Error: Library basic fuzzer build directory does not exist: {work_dir}"
        )
    header_dir = os.path.join(work_dir, "include")
    if not os.path.exists(header_dir):
        raise Exception(f"[!] Error: Header directory {header_dir} does not exist")
    return header_dir

header_include_path = get_project_coverage_header_include_dir()
if not os.path.exists(header_include_path):
    raise Exception(f"Include directory {header_include_path} does not exist")
project_name = ProjectUtils.get_project_name()
project_dir = os.environ.get("SRC", "Dummy")
os.chdir(header_include_path)

def get_lib_header_files(include_dir: str = header_include_path) -> List[str]:
    """
    Get all header files in the given include directory.
    """
    skip_dirs = {"absl", "upb"}
    header_files = []
    for root, dirs, files in os.walk(include_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for file in files:
            if (
                file.endswith(".h")
                or file.endswith(".hpp")
                or file.endswith(".hxx")
                or file.endswith(".h++")
                or file.endswith(".hh")
            ):
                full_path = os.path.join(root, file)
                header_files.append(full_path)
    return header_files

class TreeNode:
    """
    Tree node for representing header file dependencies.
    """

    def __init__(self, name: str):
        self.name = name.replace("./", "")
        self.children: List["TreeNode"] = []

    @classmethod
    def new_invalid(cls) -> "TreeNode":
        """Create an invalid tree node."""
        node = cls("invalid")
        return node

    def is_invalid(self) -> bool:
        """Check if the node is invalid."""
        return self.name == "invalid"

    def set_name(self, name: str):
        """Set the name of the node."""
        self.name = name

    def add_child(self, child: "TreeNode"):
        """Add a child node."""
        self.children.append(child)

    def get_name(self) -> str:
        """Get the name of the node."""
        return self.name

    def get_clean_root(self, include_path: str):
        """Clean the root path for all nodes in the tree."""
        work_list = deque([self])
        while work_list:
            node = work_list.popleft()
            for child in node.children:
                work_list.append(child)
            name = node.get_name()
            if name.startswith(include_path):
                name = name[len(include_path) :]
                if name.startswith("/"):
                    name = name[1:]
                node.set_name(name)


class Deopt:
    """
    Library optimization/dependency helper.
    """

    def __init__(self, lib_name: str):
        self.lib_name = lib_name

    def get_library_build_header_path(self) -> Optional[str]:
        """Get the path to the library's build header directory."""
        return get_project_coverage_header_include_dir()


class Executor:
    """
    Executor for extracting header file dependencies using clang++.
    """

    def __init__(self, deopt: Deopt):
        self.deopt = deopt

    def extract_header_dependency(self, header: str) -> TreeNode:
        """
        Extract header dependencies for a given header file using clang++.
        """
        print_debug(f"[+] Extracting header dependency for {header}...")
        header_path = self.deopt.get_library_build_header_path()
        if not header_path:
            return TreeNode.new_invalid()
        # Use clang++ to analyze header dependencies, filter out error messages, and keep only hierarchical header list
        cmd = ["clang++", "-fsyntax-only", "-ferror-limit=1", "-H", "-I.", header]
        try:
            output = subprocess.run(
                cmd,
                cwd=header_path,
                stdin=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE,
            )
        except Exception as e:
            if FUZZAGENT_DEBUG:
                print(f"Failed to run clang for {header}: {e}")
            return TreeNode.new_invalid()
        clang_output = output.stdout.decode("utf-8")
        # Only keep lines with hierarchical markers that belong to the library
        hierarchical_header_list = []
        for line in clang_output.split("\n"):
            if line.startswith(".") and line.split(" ")[-1].startswith(
                header_include_path
            ):
                hierarchical_header_list.append(line)
        # Parse to (layer, path) list
        node_layer = []
        for line in hierarchical_header_list:
            sep = line.find(" ")
            if sep == -1:
                continue
            layer = sep
            header_name = line[sep:].strip()
            node_layer.append((layer, header_name))
        base_name = os.path.relpath(header, header_path)
        base_name = f"./{base_name}"
        tree = TreeNode(base_name)
        for child in get_layer_child(node_layer, 1):
            tree.add_child(child)
        tree.get_clean_root(header_path)
        return tree


class ClangAPIExtractor:
    """
    Extracts public APIs from C/C++ header files using Clang.
    """

    def __init__(self, repo_path: str, include_path: str, top_level_headers: List[str]):
        self.repo_path = Path(repo_path)
        self.include_path = Path(include_path)
        self.exported_apis = set()
        self.top_level_headers = top_level_headers
        self.current_is_cpp = False

        # Initialize Clang
        self.index = Index.create()

        def get_compiler_includes(lang):
            compiler = 'clang++' if lang == 'c++' else 'clang'
            includes = []
            try:
                cmd = [compiler, '-E', '-x', lang, '-', '-v']
                output = subprocess.run(cmd, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, check=True)
                in_include_section = False
                for line in output.stderr.decode('utf-8').split('\n'):
                    line = line.strip()
                    if line == '#include <...> search starts here:':
                        in_include_section = True
                        continue
                    elif line == 'End of search list.':
                        in_include_section = False
                        continue
                    if in_include_section and line and not line.startswith('#'):
                        includes.extend(['-I', os.path.abspath(line)])
            except Exception:
                pass
            return includes

        c_system_includes = get_compiler_includes('c')
        cpp_system_includes = get_compiler_includes('c++')

        self.c_args = [
            "-I",
            str(self.include_path),
            "-I",
            str(self.repo_path / "include"),
            "-std=c11",
            "-x",
            "c-header",
            "-DVPX_DISABLE_CTRL_TYPECHECKS",
        ] + c_system_includes

        self.cpp_args = [
            "-I",
            str(self.include_path),
            "-I",
            str(self.repo_path / "include"),
            "-std=c++17",
            "-x",
            "c++-header",
            "-D__linux__",
        ] + cpp_system_includes

    def is_public_declaration(self, cursor) -> bool:
        """
        Check if the cursor is a public declaration.
        """
        # Check if in main file
        if cursor.location.file is None:
            return False

        file_path = Path(cursor.location.file.name)

        # Check if in include directory
        try:
            file_path.relative_to(self.include_path)
        except ValueError:
            return False

        # Skip internal APIs
        if cursor.spelling.startswith("_") and not self.current_is_cpp:
            return False
        
        if self.current_is_cpp and ("internal" in file_path.parts or "detail" in file_path.parts or "private" in file_path.parts):
            return False

        if cursor.access_specifier != AccessSpecifier.INVALID:
            if cursor.access_specifier != AccessSpecifier.PUBLIC:
                return False

        return True
    
    def get_fully_qualified_name(self, cursor) -> str:
        """
        Reconstructs the fully qualified name similar to c++filt output.
        Format: Namespace::Class::Method(Args)
        """
        name = cursor.displayname
        
        parent = cursor.semantic_parent
        while parent and parent.kind != CursorKind.TRANSLATION_UNIT:
            if parent.kind in [CursorKind.NAMESPACE, CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL]:
                parent_name = parent.spelling
                if not parent_name: 
                    parent_name = "(anonymous)"
                name = f"{parent_name}::{name}"
            parent = parent.semantic_parent
            
        return name

    def extract_cpp_function_api(self, cursor):
        """
        Extract C/C++ function/method API in mangled form (e.g., _ZN6google...).
        """
        valid_kinds = {
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.CONSTRUCTOR,
            CursorKind.DESTRUCTOR,
            CursorKind.FUNCTION_TEMPLATE,
            CursorKind.CONVERSION_FUNCTION
        }

        if cursor.kind in valid_kinds and self.is_public_declaration(cursor):
            try:
                if cursor.is_deleted_method():
                    return
            except AttributeError:
                pass

            mangled = cursor.mangled_name

            if mangled:

                self.exported_apis.add(mangled)
                
            else:
                if cursor.spelling:
                    self.exported_apis.add(cursor.spelling)


    def extract_function_api(self, cursor):
        """
        Extract function API from cursor.
        """
        if cursor.kind == CursorKind.FUNCTION_DECL and self.is_public_declaration(
            cursor
        ):
            # Check storage class
            if cursor.storage_class != StorageClass.STATIC:
                func_name = cursor.spelling
                if func_name:
                    # # Optionally, get function signature
                    # return_type = cursor.result_type.spelling
                    # params = []
                    # for param in cursor.get_arguments():
                    #     param_type = param.type.spelling
                    #     param_name = param.spelling
                    #     params.append(f"{param_type} {param_name}")

                    # signature = f"{return_type} {func_name}({', '.join(params)})"
                    # self.exported_apis.add(f"function:{func_name}")
                    self.exported_apis.add(f"{func_name}")
                    # self.exported_apis.add(f"function_signature:{signature}")

    def extract_struct_api(self, cursor):
        """
        Extract struct API from cursor.
        """
        if cursor.kind == CursorKind.STRUCT_DECL and self.is_public_declaration(cursor):
            struct_name = cursor.spelling
            if struct_name:
                self.exported_apis.add(f"struct:{struct_name}")
                # Extract struct fields
                for child in cursor.get_children():
                    if child.kind == CursorKind.FIELD_DECL:
                        field_name = child.spelling
                        if field_name:
                            self.exported_apis.add(
                                f"struct_field:{struct_name}.{field_name}"
                            )

    def extract_union_api(self, cursor):
        """
        Extract union API from cursor.
        """
        if cursor.kind == CursorKind.UNION_DECL and self.is_public_declaration(cursor):
            union_name = cursor.spelling
            if union_name:
                self.exported_apis.add(f"union:{union_name}")

    def extract_enum_api(self, cursor):
        """
        Extract enum API from cursor.
        """
        if cursor.kind == CursorKind.ENUM_DECL and self.is_public_declaration(cursor):
            enum_name = cursor.spelling
            if enum_name:
                self.exported_apis.add(f"enum:{enum_name}")
            # Extract enum values
            for child in cursor.get_children():
                if child.kind == CursorKind.ENUM_CONSTANT_DECL:
                    enum_value = child.spelling
                    if enum_value:
                        self.exported_apis.add(f"enum_value:{enum_value}")

    def extract_typedef_api(self, cursor):
        """
        Extract typedef API from cursor.
        """
        if cursor.kind == CursorKind.TYPEDEF_DECL and self.is_public_declaration(
            cursor
        ):
            typedef_name = cursor.spelling
            if typedef_name:
                self.exported_apis.add(f"typedef:{typedef_name}")

    def extract_macro_api(self, cursor):
        """
        Extract macro API from cursor.
        """
        if cursor.kind == CursorKind.MACRO_DEFINITION and self.is_public_declaration(
            cursor
        ):
            macro_name = cursor.spelling
            if macro_name and not macro_name.startswith("_"):
                self.exported_apis.add(f"macro:{macro_name}")

    def extract_variable_api(self, cursor):
        """
        Extract variable API from cursor (only extern variables).
        """
        if cursor.kind == CursorKind.VAR_DECL and self.is_public_declaration(cursor):
            # Only extract extern variables
            if cursor.storage_class == StorageClass.EXTERN:
                var_name = cursor.spelling
                if var_name:
                    self.exported_apis.add(f"variable:{var_name}")

    def extract_class_api(self, cursor):
        """
        Extract C++ class API from cursor.
        """
        if cursor.kind == CursorKind.CLASS_DECL and self.is_public_declaration(cursor):
            class_name = cursor.spelling
            if class_name:
                self.exported_apis.add(f"class:{class_name}")
                # Extract class members
                for child in cursor.get_children():
                    if child.access_specifier == clang.cindex.AccessSpecifier.PUBLIC:
                        if child.kind == CursorKind.CXX_METHOD:
                            method_name = child.spelling
                            if method_name:
                                self.exported_apis.add(
                                    f"method:{class_name}.{method_name}"
                                )
                        elif child.kind == CursorKind.FIELD_DECL:
                            field_name = child.spelling
                            if field_name:
                                self.exported_apis.add(
                                    f"class_field:{class_name}.{field_name}"
                                )

    def traverse_ast(self, cursor):
        """
        Traverse AST and extract APIs from each node.
        """
        self.extract_function_api(cursor)
        # self.extract_struct_api(cursor)
        # self.extract_union_api(cursor)
        # self.extract_enum_api(cursor)
        # self.extract_typedef_api(cursor)
        # self.extract_macro_api(cursor)
        # self.extract_variable_api(cursor)
        # self.extract_class_api(cursor)
        # Recursively traverse child nodes
        self.extract_cpp_function_api(cursor)
        for child in cursor.get_children():
            self.traverse_ast(child)

    def guess_language(self, header_file: str) -> bool:
        """Based on file extension and content, guess if it is C++"""
        if str(header_file).endswith(('.hpp', '.hxx', '.hh', '.h++')):
            return True
        try:
            with open(header_file, 'r', errors='ignore') as f:
                content = f.read()
                if any(kw in content for kw in ['namespace ', 'class ', 'template <', 'public:', 'virtual ']):
                    return True
        except Exception:
            pass
        return False

    def parse_header_file(self, header_file: str):
        """
        Parse a single header file and extract APIs with dynamic language detection and fallback.
        """
        try:
            if FUZZAGENT_DEBUG:
                print(f"[+] Parsing header file: {header_file}")
            
            is_cpp_guess = self.guess_language(header_file)
            args_primary = self.cpp_args if is_cpp_guess else self.c_args
            args_secondary = self.c_args if is_cpp_guess else self.cpp_args

            # Parse with primary guess
            translation_unit = self.index.parse(str(header_file), args=args_primary)
            err_count_primary = sum(1 for d in translation_unit.diagnostics if d.severity >= clang.cindex.Diagnostic.Error)

            self.current_is_cpp = is_cpp_guess
            final_tu = translation_unit

            # Fallback if there are errors and the default heuristic failed
            if err_count_primary > 0:
                tu_secondary = self.index.parse(str(header_file), args=args_secondary)
                err_count_secondary = sum(1 for d in tu_secondary.diagnostics if d.severity >= clang.cindex.Diagnostic.Error)
                
                if err_count_secondary < err_count_primary:
                    final_tu = tu_secondary
                    self.current_is_cpp = not is_cpp_guess

            # Print diagnostics if debug enabled
            if FUZZAGENT_DEBUG:
                for diagnostic in final_tu.diagnostics:
                    if diagnostic.severity >= clang.cindex.Diagnostic.Error:
                        print(f"[!] Error: {diagnostic.spelling}")
                    elif diagnostic.severity == clang.cindex.Diagnostic.Warning:
                        print(f"[!] Warning: {diagnostic.spelling}")
            # Traverse AST
            self.traverse_ast(final_tu.cursor)
        except Exception as e:
            print(f"[!] Error parsing header file {header_file}: {e}")

    def extract_exported_apis(self) -> List[str]:
        """
        Extract all exported APIs from top-level headers.
        """
        self.exported_apis.clear()
        if FUZZAGENT_DEBUG:
            print(
                f"[+] Found {len(self.top_level_headers)} header files to extract exported APIs."
            )
        for header_file in self.top_level_headers:
            self.parse_header_file(header_file)
        return sorted(list(self.exported_apis))


def get_layer_child(layered_nodes: List[Tuple[int, str]], depth: int) -> List[TreeNode]:
    """
    Recursively build tree nodes from layered node list.
    """
    childs = []
    i = 0
    n = len(layered_nodes)
    while i < n:
        layer, name = layered_nodes[i]
        if layer == depth:
            j = i + 1
            child_nodes = []
            while j < n and layered_nodes[j][0] > depth:
                child_nodes.append(layered_nodes[j])
                j += 1
            node = TreeNode(name)
            children = get_layer_child(child_nodes, depth + 1)
            for child in children:
                node.add_child(child)
            childs.append(node)
            i = j
        else:
            i += 1
    return childs


def get_library_dep_trees(deopt: Deopt) -> List[TreeNode]:
    """
    Get dependency trees for all header files in the library.
    """
    executor = Executor(deopt)
    header_dir = deopt.get_library_build_header_path()
    if not header_dir or not os.path.exists(header_dir):
        return []
    header_files = get_lib_header_files(header_dir)
    header_trees = []
    max_workers = min(32, (os.cpu_count() or 1) * 4)
    with ThreadPoolExecutor(max_workers=max_workers) as tp:
        future_to_header = {tp.submit(executor.extract_header_dependency, h): h for h in header_files}
        for future in as_completed(future_to_header):
            header_path = future_to_header[future]
            try:
                tree = future.result()
                if tree and not tree.is_invalid():
                    header_trees.append(tree)
            except Exception as e:
                print_debug(f"[!] Error processing {header_path}: {e}")
    return header_trees


def save_api_list(api_list: List[str]):
    """
    Save the API list to the cache API list file.
    """
    cache_api_list_file = ProjectUtils.get_project_cache_api_list_file()
    with open(cache_api_list_file, "w") as f:
        for api in api_list:
            f.write(api + "\n")
    OSSUtils.upload_file_to_oss_cache(cache_api_list_file, OSSCacheKind.APIList)

def load_api_list() -> List[str]:
    """
    Load the API list from the cache API list file.
    """
    cache_api_list_file = ProjectUtils.get_project_cache_api_list_file()
    if not os.path.exists(cache_api_list_file) and not OSSUtils.download_file_from_oss_cache(cache_api_list_file, OSSCacheKind.APIList):
        return []
    with open(cache_api_list_file, "r") as f:
        return [line.strip() for line in f.readlines()]


def filter_macro_apis(api_list: List[str]) -> List[str]:
    """
    Filter out macro APIs from the API list. They are expanded from C macro expression. They should be filtered out.
    """
    return [api for api in api_list if not api.startswith("aom_codec_control_typechecked_")]

def get_public_apis() -> List[str]:
    """
    Get all public APIs from the project headers.
    """
    api_list = load_api_list()
    if api_list:
        return api_list
    deopt = Deopt(project_name)
    dep_trees = get_library_dep_trees(deopt)
    top_level_headers = [
        os.path.join(header_include_path, node.name)
        for node in dep_trees
        if not node.is_invalid()
    ]
    extractor = ClangAPIExtractor(project_dir, header_include_path, top_level_headers)
    exported_apis = extractor.extract_exported_apis()
    exported_apis = filter_macro_apis(exported_apis)
    save_api_list(exported_apis)
    return exported_apis


if __name__ == "__main__":
    # Main entry: extract and print exported APIs from top-level headers
    deopt = Deopt("protobuf")
    dep_trees = get_library_dep_trees(deopt)
    top_level_headers = [node.name for node in dep_trees if not node.is_invalid()]
    top_level_headers = [
        os.path.join(header_include_path, node.name)
        for node in dep_trees
        if not node.is_invalid()
    ]
    extractor = ClangAPIExtractor(project_dir, header_include_path, top_level_headers)
    exported_apis = extractor.extract_exported_apis()
    print("[+] Top-level headers:", top_level_headers)
    print(
        f"[+] Exported APIs: {exported_apis}\nNumber of Exported APIs: {len(exported_apis)}"
    )
