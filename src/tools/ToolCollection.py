from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from src.utils.config import CONFIG
import yaml
import os

script_path = os.path.abspath(__file__)

script_dir = os.path.dirname(script_path)


class Argument(BaseModel):
    name: str
    type: str
    description: str
    required: bool
    redirect: Optional[bool] = False
    enum: Optional[List[str]] = Field(default=None, description="The enum of the parameter")


class Tool(BaseModel):
    timeout: int = Field(default=10, description="The timeout of the tool in seconds")
    max_output_lines: int = Field(default=CONFIG.ACIARGs.CMD_OUTPUT_LINES, description="The maximum number of lines of output for the tool")
    signature: str
    docstring: str
    arguments: Optional[List[Argument]] = Field(default_factory=list)

    def get_description(self) -> str:
        # Split the signature into lines
        sig_lines = self.signature.split("\n")

        # Build the lines of the resulting YAML
        lines = ["@ command line tool"]

        # Signature block with proper indentation and |- indicator
        lines.append("signature: |-")
        for line in sig_lines:
            lines.append(f"    {line}")

        # Docstring line
        lines.append(f"docstring: {self.docstring}")

        # Arguments section
        lines.append("arguments:")
        if self.arguments is not None:  
            for arg in self.arguments:
                required_str = "true" if arg.required else "false"
                lines.append(f"- name: {arg.name}")
                lines.append(f"  type: {arg.type}")
                lines.append(f"  description: {arg.description}")
                lines.append(f"  required: {required_str}")
        # Join all lines into a single string
        return "\n".join(lines)


class ToolCollection(BaseModel):
    tools: Dict[str, Tool] = Field(default_factory=dict)

    @staticmethod
    def new() -> "ToolCollection":
        return ToolCollection(tools={})

    def merge(self, other: "ToolCollection"):
        for tool_name, tool in other.tools.items():
            if tool_name not in self.tools:
                self.tools[tool_name] = tool

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        return self.tools.get(tool_name)

    def get_tools(self, tool_names: List[str]) -> List[Tool]:
        tools = []
        for tool_name in tool_names:
            tool = self.get_tool(tool_name)
            if tool is None:
                raise ValueError(f"Tool '{tool_name}' not found in tool collection")
            tools.append(tool)
        return tools


def load_yaml_config(file_path: str) -> ToolCollection:
    with open(file_path, "r") as file:
        yaml_data = yaml.safe_load(file)
    return ToolCollection(**yaml_data)


def load_tool_collections() -> ToolCollection:
    tools = ToolCollection.new()
    for root, _, files in os.walk(script_dir, topdown=False):
        for file in files:
            if file.endswith(".yaml"):
                file_path = os.path.join(root, file)
                tools.merge(load_yaml_config(file_path))
    return tools

TOOLs = load_tool_collections()
SOURCE_TOOL_LIST = ["open", "goto", "find_file", "edit", "scroll_down", "scroll_up"]
