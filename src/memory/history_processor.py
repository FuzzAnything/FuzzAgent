import json
from typing import List, Dict, Tuple, Any
from logging import Logger
import copy
from openai.types.chat import ChatCompletionMessage

class HistoryProcessor:
    """
    Agent history message processor.
    """

    def __init__(self, logger: Logger):
        self.logger: Logger = logger
        self.history = []
        self.last = []
        self.messages: List[Dict[str, Any]] = []
        self.original_messages: List[Dict[str, Any]] = []

    def set_messages(self, messages: List[Dict[str, Any]]):
        """
        Set the message history.
        """
        self.messages = messages
        self.original_messages = copy.deepcopy(messages)

    def get_messages(self) -> List[Dict[str, Any]]:
        """
        Get the message history.
        """
        return self.messages
    
    def get_original_messages(self) -> List[Dict[str, Any]]:
        """
        Get the original message history.
        """
        return self.original_messages

    def append_raw_messages(self, messages: ChatCompletionMessage):
        """
        Extends the history message to get a new messeage for query with raw messages.
        """
        # SGlang DeepSeek Reason output
        if hasattr(messages, "reasoning_content"):
            self.logger.info(f"LLM Thinking:\n {messages.reasoning_content}")
        elif hasattr(messages, "reasoning_details"):
            self.logger.info(f"LLM Thinking:\n {messages.reasoning_details[0]['text']}")
        elif hasattr(messages, "reasoning"):
            self.logger.info(f"LLM Thinking:\n {messages.reasoning}")

        # Truncate to single tool_call: the rest of the pipeline only executes/fulfills
        # tool_calls[0] (see llm.py and BaseAgent.run). Keeping extra tool_call_ids on
        # the assistant message would leave them without matching tool replies and
        # trigger "insufficient tool messages following tool_calls message" on the next
        # API call.
        tool_calls = getattr(messages, "tool_calls", None)
        if tool_calls and len(tool_calls) > 1:
            messages.tool_calls = [tool_calls[0]]

        self.messages.append(messages)

    def extend_msg(self, response_text: str, content: str):
        """
        Extends the history message to get a new messeage for query.
        """
        new_msg = [
            {"role": "assistant", "content": response_text},
            {"role": "user", "content": content},
        ]
        self.messages.extend(new_msg)
        self.original_messages.extend(new_msg)
        self.logger.info(f"Query\n{content}")

    def extend_user_msg(self, content: str):
        """
        Extends the history message to get a new messeage for query with user message.
        """
        new_msg = [
            {"role": "user", "content": content},
        ]
        self.messages.extend(new_msg)
        self.original_messages.extend(new_msg)
        self.logger.info(f"User message\n{content}")

    def extend_assistant_msg(self, content: str):
        """
        Extends the history message to get a new messeage for query with assistant message.
        """
        new_msg = [
            {"role": "assistant", "content": content},
        ]
        self.messages.extend(new_msg)
        self.original_messages.extend(new_msg)
        self.logger.info(f"Assistant message\n{content}")

    

    def extend_function_call_msg(self, content: str, name: str, id: str):
        """
        Extends the history message to get a new messeage for query with function call.
        """
        # OpenAI style
        # new_msg = [
        #     {"role": "function", "tool_call_id": id, "name": name, "content": content},
        # ]

        # OpenRouter style
        # new_msg = [
        #     {"role": "user", "tool_call_id": id, "name": name, "content": content},
        # ]

        # Qwen style
        new_msg = [
            {"role": "tool", "tool_call_id": id, "name": name, "content": content},
        ]

        self.messages.extend(new_msg)
        self.original_messages.extend(new_msg)
        self.logger.info(f"Function call message\n{content}")

    def record_history(self, msg: list):
        """
        Record the message history.
        """
        self.history = msg

    def delete_last_history_msg(self):
        """
        Delete the last history message.
        """
        if len(self.history) >= 2:
            self.history = self.history[:-2]

    def record_last_chat_msg(self, response_text: str, content: str):
        """
        Record the last message.
        """
        msg = [
            {"role": "assistant", "content": response_text},
            {"role": "user", "content": content},
        ]
        self.last = msg

    def clear_history(self):
        """
        Clear the message history.
        """
        self.history = []
        self.message = []
        self.original_messages = []
