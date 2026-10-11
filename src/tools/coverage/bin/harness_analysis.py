#!/usr/bin/env python3
"""
Analyze C++ files using tree-sitter and extract all function call names
"""
import sys
import warnings
from typing import List, Set, Optional

# tree_sitter may throw FutureWarning, ignore it
warnings.simplefilter("ignore", category=FutureWarning)

try:
    from tree_sitter_languages import get_language, get_parser
    from tree_sitter import Language, Parser
    import tree_sitter_cpp as ts_cpp
except ImportError:
    print("Error: tree-sitter-languages library is required")
    print("Please run: pip install tree-sitter-languages")
    sys.exit(1)

CPP_LANGUAGE = Language(ts_cpp.language())
parser = Parser(CPP_LANGUAGE)


def extract_function_calls(file_path: str) -> List[str]:
    """
    Parse a C++ file using tree-sitter and extract all function call names
    
    Args:
        file_path: Path to the C++ file
        
    Returns:
        List of function call names (may contain duplicates)
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            source_code = f.read()
    except Exception as e:
        print(f"Error: Failed to read file {file_path}: {e}", file=sys.stderr)
        return []

    
    # Parse source code
    source_bytes = bytes(source_code, "utf-8")
    tree = parser.parse(source_bytes)
    
    function_calls = []
    
    # Traverse AST to find all call_expression nodes
    def traverse(node):
        """Recursively traverse AST nodes"""
        # If it's a function call expression
        if node.type == 'call_expression':
            # Get function name node (usually the first child)
            function_node = node.child_by_field_name('function')
            if function_node is None:
                # If there's no function field, try to get the first child
                if node.child_count > 0:
                    function_node = node.children[0]
            
            if function_node is not None:
                # Extract function name
                func_name = extract_function_name(function_node, source_bytes)
                if func_name:
                    function_calls.append(func_name)
        
        # Recursively traverse all child nodes
        for child in node.children:
            traverse(child)
    
    def extract_function_name(node, source_bytes: bytes) -> Optional[str]:
        """
        Extract function name from a node
        
        Function name can be:
        - identifier: Direct function name, e.g., foo()
        - field_expression: Member function, e.g., obj.method()
        - qualified_identifier: Qualified name, e.g., std::cout
        - template_function: Template function
        """
        if node.type == 'identifier':
            # Direct identifier
            return source_bytes[node.start_byte:node.end_byte].decode('utf-8', errors='ignore')
        elif node.type == 'field_expression':
            # Member function call, e.g., obj.method()
            # Get field field (method name)
            field_node = node.child_by_field_name('field')
            if field_node and field_node.type == 'field_identifier':
                return source_bytes[field_node.start_byte:field_node.end_byte].decode('utf-8', errors='ignore')
        elif node.type == 'qualified_identifier':
            # Qualified name, e.g., std::cout or namespace::function
            # Get the last identifier as function name
            for child in reversed(node.children):
                if child.type == 'identifier':
                    return source_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='ignore')
        elif node.type == 'template_function':
            # Template function, e.g., std::vector<int>()
            # Find identifier within
            for child in node.children:
                if child.type == 'identifier':
                    return source_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='ignore')
        elif node.type == 'subscript_expression':
            # Array subscript, e.g., arr[i], not a function call, skip
            pass
        else:
            # Other cases, try to recursively find identifier
            for child in node.children:
                result = extract_function_name(child, source_bytes)
                if result:
                    return result
        
        return None
    
    # Start traversal from root node
    traverse(tree.root_node)
    
    return function_calls
