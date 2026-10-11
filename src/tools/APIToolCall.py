from src.tools.ToolCollection import Tool, Argument, ToolCollection, load_tool_collections
from typing import Any, List, Dict, Literal, Optional
from pydantic import BaseModel, Field
from openai import pydantic_function_tool


class FunctionCallParameterProperty(BaseModel):
    type: str = Field(description="The type of the parameter")
    description: str = Field(description="The description of the parameter")
    enum: Optional[List[str]] = Field(default=None, description="The enum of the parameter")



class FunctionCallParameters(BaseModel):
    type: str = Field(default="object", description="The type of the parameter object")
    required: List[str] = Field(default_factory=list, description="List of required parameter names")
    properties: Dict[str, FunctionCallParameterProperty] = Field(
        default_factory=dict, 
        description="Dictionary of parameter properties"
    )
    additionalProperties: Optional[bool] = Field(default=False, description="Whether to allow additional properties")

    @staticmethod
    def from_tool_arguments(arguments: List[Argument]) -> "FunctionCallParameters":
        properties: Dict[str, FunctionCallParameterProperty] = {}
        required = []
        for argument in arguments:
            properties[argument.name] = FunctionCallParameterProperty(
                type=argument.type,
                description=argument.description,
                enum=argument.enum
            )
            if argument.required:
                required.append(argument.name)
        return FunctionCallParameters(
            type="object",
            required=required,
            properties=properties,
            additionalProperties=False
        )

class FunctionCall(BaseModel):
    name: str = Field(description="The name of the function")
    description: str = Field(description="The description of the function")
    parameters: Optional[FunctionCallParameters] = Field(default=None, description="The parameters of the function")
    strict: Optional[bool] = Field(default=False, description="Whether to enable strict schema adherence when generating the function call")

    @staticmethod
    def from_tool(tool_name: str, tool: Tool) -> "FunctionCall":
        if tool.arguments is None:
            return FunctionCall(
                name=tool_name,
                description=tool.docstring,
                parameters=None,
                strict=False
            )
        parameters = FunctionCallParameters.from_tool_arguments(tool.arguments)
        return FunctionCall(
            name=tool_name,
            description=tool.docstring,
            parameters=parameters,
            strict=False
        )

class FunctionCallWrapper(BaseModel):
    type: Literal["function"] = Field(description="The type of the function call")
    function: FunctionCall = Field(description="The function call")


class FunctionCallCollection:
    def __init__(self, tool_collection: ToolCollection):
        self.tool_collection = tool_collection
        self.tool_calls = self.format_api_tool_calls()

    def format_api_tool_calls(self) -> List[dict]:
        tool_calls: List[dict] = []
        for tool_name, tool in self.tool_collection.tools.items():
            tool_calls.append(FunctionCallWrapper(
                type="function",
                function=FunctionCall.from_tool(tool_name, tool)
            ).model_dump(exclude_none=True))
        return tool_calls

    def get_tool_call(self, tool_name: str):
        for tool_call in self.tool_calls:
            if tool_call["function"]["name"] == tool_name:
                return tool_call
        return None
    
    def get_tool_calls(self, tool_names: List[str]) -> List[dict]:
        tool_calls = []
        for tool_name in tool_names:
            tool_call = self.get_tool_call(tool_name)
            if tool_call is not None:
                tool_calls.append(tool_call)
            else:
                raise Exception(f"Tool {tool_name} not found in the tool collection!")
        return tool_calls

pydantic_function_tool(FunctionCallWrapper)

API_TOOL_CALLS = FunctionCallCollection(load_tool_collections())
