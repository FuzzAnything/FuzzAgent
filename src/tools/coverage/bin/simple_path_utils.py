# simple_path_utils.py - Simplified path utilities for FuzzAgent
import re
from typing import List, Union

def simplify_path(path_input: Union[str, List[str]], path_type: str = "auto") -> Union[str, List[str]]:
    """
    Simplify paths for coverage display
    
    Args:
        path_input: Path string or list of paths to simplify
        path_type: "auto", "branch", or "fuzzer" (auto-detection if not specified)
    
    Returns:
        Simplified path string or list
    """
    if isinstance(path_input, str):
        if path_type == "auto":
            # Auto-detect: if contains .txt: and line number, treat as branch path
            if '.txt:' in path_input and path_input.split(':')[-1].isdigit():
                return _simplify_branch_path(path_input)
            else:
                # Single path, wrap in list and simplify
                return _simplify_path_list([path_input])
        elif path_type == "branch":
            return _simplify_branch_path(path_input)
        else:  # fuzzer type
            return _simplify_path_list([path_input])
    
    elif isinstance(path_input, list):
        return _simplify_path_list(path_input)
    
    else:
        return path_input

def _simplify_branch_path(path: str) -> str:
    """Simplify branch coverage path"""
    if not path or ':' not in path:
        return path
    
    # Extract fuzzer ID - look for various patterns
    fuzzer_id = _extract_fuzzer_id(path)
    if not fuzzer_id:
        fuzzer_id = "f???"
    
    # Extract project name (try multiple patterns)
    project_name = "unknown"
    
    # Pattern 1: /build/project/ 
    project_match = re.search(r'/build/([^/]+)/', path)
    if project_match:
        project_name = project_match.group(1)
    else:
        # Pattern 2: /real_projects/project-testing-version/
        project_match = re.search(r'/real_projects/([^/]+?)(?:-testing|-v\d|$)', path)
        if project_match:
            project_name = project_match.group(1)
        else:
            # Pattern 3: Any directory with project-like name
            project_match = re.search(r'/([^/]*(?:JSON|protobuf|ssl|xml|png|zip)[^/]*)', path, re.IGNORECASE)
            if project_match:
                project_name = project_match.group(1).split('-')[0]
    
    # Extract filename and line number
    parts = path.split('/')
    filename = "unknown"
    line_num = ""
    
    for part in parts:
        if '.c.txt:' in part or '.cpp.txt:' in part or '.cc.txt:' in part or '.h.txt:' in part:
            file_parts = part.split('.txt:')
            if len(file_parts) == 2:
                filename = file_parts[0]
                line_num = f"L{file_parts[1]}"
                break
    
    return f"{fuzzer_id}:{project_name}:{filename}:{line_num}"

def _simplify_path_list(paths: List[str]) -> List[str]:
    """Simplify list of fuzzer/harness paths"""
    if not paths:
        return []
    
    simplified = []
    for path in paths:
        if not path:
            simplified.append("")
            continue
            
        fuzzer_id = _extract_fuzzer_id(path)
        if fuzzer_id:
            simplified.append(fuzzer_id)
        else:
            # Extract filename as fallback
            filename = path.split('/')[-1] if '/' in path else path
            simplified.append(filename)
    
    return sorted(list(set(simplified)))  # Remove duplicates and sort

def _extract_fuzzer_id(path: str) -> str:
    """Extract fuzzer ID from path"""
    # Match fuzzer_xxx pattern
    fuzzer_match = re.search(r'fuzzer[_-](\d+)', path)
    if fuzzer_match:
        return f"f{fuzzer_match.group(1).zfill(3)}"
    
    # Match harness_xxx pattern  
    harness_match = re.search(r'harness[_-](\d+)', path)
    if harness_match:
        return f"h{harness_match.group(1).zfill(3)}"
    
    # For now, if no fuzzer pattern found, derive from project path
    # Look for patterns like /real_projects/project-testing-v1.7.17/
    # and assign a default fuzzer ID
    if '/real_projects/' in path:
        # Extract project directory and create a hash-based ID
        project_match = re.search(r'/real_projects/([^/]+)', path)
        if project_match:
            project_dir = project_match.group(1)
            # Simple hash to get consistent ID for same project
            hash_val = hash(project_dir) % 1000
            return f"f{str(hash_val).zfill(3)}"
    
    return ""

def get_simplification_rules() -> str:
    """Get path simplification rules explanation"""
    return """
Path Simplification Rules:
=========================
• Branch paths: f000:project:file.c:L123
  - f000 = fuzzer_000
  - project = project name from build path
  - file.c = source filename
  - L123 = line number

• Fuzzer/Harness lists: ['f001', 'h005', 'h010']
  - f001 = fuzzer_001
  - h005 = harness_005
  - Sorted and deduplicated

• To find original paths, check:
  - Fuzzer paths: $OUTPUT/fuzzers/fuzzer_XXX/
  - Harness paths: ./harnesses/harness_XXX.cpp
  - Coverage reports: fuzzer_XXX/coverage_output/report/
"""

# Export the main function for easy import
__all__ = ['simplify_path', 'get_simplification_rules']
