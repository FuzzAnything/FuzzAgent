#! /usr/bin/python3
import re
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import networkx as nx
from dataclasses import dataclass
from project_utils import ProjectUtils, print_debug
from header_analysis import get_public_apis
import argparse
import cxxfilt

# Essential edges in building the call graph, but are not statically analyzed by wllvm. These edges can be infered by pointer analysis, but we manually add them here for convenience.
ESSENTIAL_EDGES = [
    ("aom_codec_decode", "decoder_decode"),
    ("aom_codec_encode", "encoder_encode"),
]

import cxxfilt
import re

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



@dataclass
class DotNode:
    id: int
    label: str

    @classmethod
    def new(cls, id_str: str, label: str) -> 'DotNode':
        return cls(
            id=int(id_str[2:], 16),
            label=label
        )

@dataclass
class DotEdge:
    src: int
    dst: int

    @classmethod
    def new(cls, src_str: str, dst_str: str) -> 'DotEdge':
        return cls(
            src=int(src_str[2:], 16),
            dst=int(dst_str[2:], 16)
        )

def dot_parser(dot_file: str) -> Tuple[List[DotNode], List[DotEdge]]:
    with open(dot_file, 'r') as f:
        content = f.read()
    
    node_re = re.compile(r'Node(0x[0-9a-fA-F]+) \[shape=record,label="\{(.+?)\}"];')
    nodes = []
    for match in node_re.finditer(content):
        id_str = match.group(1)
        label = match.group(2)
        #if label.startswith("_ZN") and not IS_CPP_PROJECT:
        #    label = mangle_to_c_style(label)
        #else:
        label = label.strip()
        nodes.append(DotNode.new(id_str, label))
    
    edge_re = re.compile(r'Node(0x[0-9a-fA-F]+) -> Node(0x[0-9a-fA-F]+);')
    edges = []
    for match in edge_re.finditer(content):
        src = match.group(1)
        dst = match.group(2)
        edges.append(DotEdge.new(src, dst))
    
    return nodes, edges

class CallGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.node_map: Dict[str, int] = {}  # label to node index
    
    def construct(self, nodes: List[DotNode], edges: List[DotEdge]) -> None:
        self.construct_nodes(nodes)
        self.construct_edges(nodes, edges)
    
    def construct_nodes(self, nodes: List[DotNode]) -> None:
        for node in nodes:
            self.node_map[node.label] = len(self.graph.nodes)
            self.graph.add_node(node.label)
    
    def get_node_index(self, func: str) -> Optional[int]:
        if func not in self.node_map:
            return None
        return self.node_map[func]
    
    def construct_edges(self, nodes: List[DotNode], edges: List[DotEdge]) -> None:
        id_to_label = {node.id: node.label for node in nodes}
        
        for edge in edges:
            src_label = id_to_label[edge.src]
            dst_label = id_to_label[edge.dst]
            self.graph.add_edge(src_label, dst_label)
    
    def get_caller(self, func: str) -> list[str]:
        if func not in self.node_map:
            raise ValueError(f"{func} not in callgraph!")
        
        return list(self.graph.predecessors(func))
    
    def get_callees(self, func: str) -> List[str]:
        if func not in self.node_map:
            raise ValueError(f"{func} not in callgraph!")
        
        return list(self.graph.successors(func))

    def get_call_traces_from_public_apis(self, public_apis: List[str], target_func: str) -> List[List[str]]:
        if target_func not in self.node_map:
            print_debug(f"Target function {target_func} not in callgraph!")
            return []

        all_paths = []
        for api in public_apis:
            if api in self.node_map:
                # Find all simple paths from an API to the target function.
                # A simple path is a path with no repeated nodes.
                try:
                    path = nx.shortest_path(self.graph, source=api, target=target_func)
                except nx.NetworkXNoPath:
                    continue
                all_paths.append(path)
        
        # Sort all found paths by their length (number of functions in the trace)
        all_paths.sort(key=len)

        # Return the 10 shortest paths
        return all_paths[:10]
    
    def get_all_reachable_functions(self, func: str) -> List[str]:
        if func not in self.node_map:
            print_debug(f"Func {func} not in callgraph!")
            return []
        
        # Optimization: directly use networkx's descendants algorithm
        # nx.descendants returns the set of all nodes reachable from source (excluding source itself)
        reachable = nx.descendants(self.graph, func)
        
        reachable.add(func)
        
        return list(reachable)
    
def parse_call_graph(dot_path: str) -> CallGraph:
    nodes, edges = dot_parser(dot_path)
    call_graph = CallGraph()
    call_graph.construct(nodes, edges)
    for src, dst in ESSENTIAL_EDGES:
        if src not in call_graph.node_map:
            call_graph.node_map[src] = len(call_graph.graph.nodes)
            call_graph.graph.add_node(src)
        if dst not in call_graph.node_map:
            call_graph.node_map[dst] = len(call_graph.graph.nodes)
            call_graph.graph.add_node(dst)
        call_graph.graph.add_edge(src, dst)
    return call_graph

def print_call_traces(call_traces: List[List[str]], target_func: str) -> None:
    print(f"Found {len(call_traces)} call traces from public APIs to {target_func}:")
    for trace in call_traces:
        print(" -> ".join(trace))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_func", type=str, help="The target function to analyze.")
    args = parser.parse_args()

    dot_path = ProjectUtils.get_project_wllvm_callgraph_file()
    call_graph = parse_call_graph(dot_path)
    public_apis = get_public_apis()
    call_traces = call_graph.get_call_traces_from_public_apis(public_apis, args.target_func)
    print_call_traces(call_traces, args.target_func)

if __name__ == "__main__":
    main()