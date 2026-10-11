import os
import openai
import time
import logging
import json
from typing import Tuple, Any, Literal
from logging import Logger

from openai.types.chat import ChatCompletionMessage
from src.utils.config import CONFIG

RETRY_CNT = 5

# Global token statistics variables
global_prompt_tokens = 0
global_completion_tokens = 0
global_total_tokens = 0

class TokenLenExceed(Exception):
    def __init__(self, current_len, max_len, message=None):
        self.current_len = current_len
        self.max_len = max_len
        
        if message is None:
            message = f"Token length exceeded! Current: {current_len}, Max allowed: {max_len}"
            
        super().__init__(message)

class TokenLenWillExceed(Exception):
    def __init__(self, current_len, max_len, message=None):
        self.current_len = current_len
        self.max_len = max_len
        
        if message is None:
            message = f"Token length will exceed! Current: {current_len}, Max allowed: {max_len}"
            
        super().__init__(message)

class ToolCall:

    def __init__(self, function_call: str, function_call_id: str, arguments: dict) -> None:
        self.function_call = function_call
        self.function_call_id = function_call_id
        self.arguments = arguments

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=4)

 
def query_llm(
    client: openai.OpenAI,
    messages: list,
    tools: list = [],
    logger: Logger = logging.getLogger(__name__),
    tool_choice: Literal["auto", "required", "none"] = "required",
) -> Tuple[str, ToolCall | None, ChatCompletionMessage | None]:
    """
    Query the LLM API and get the response.
    """
    # Check if the LLM query has timed out in 60 seconds. Retry up to 3 times.
    # logger.info(f"Query\n{messages}")
    retry = 0
    think = ""
    result = ""
    tool_call = None
    out_messages = None
    while retry < RETRY_CNT:
        try:
            # Only the agent summarizer does not need to invoke tool calls
            response = client.chat.completions.create(
                    model=CONFIG.LLMARGs["OPENAI_MODEL"],
                    messages=messages,
                    temperature=CONFIG.LLMARGs["LLM_TEMPERATURE"],
                    top_p=CONFIG.LLMARGs["LLM_TOP_P"],
                    timeout=CONFIG.LLMARGs["LLM_REPLY_TIMEOUT"],
                    tools=tools,
                    tool_choice=tool_choice, # Experimental: "auto" | "required" | "none"
                    extra_body={
                         # VLLM Thinking configuration
                         "chat_template_kwargs": {"thinking": True},
                         # Dashscope Thinking configuration
                         "enable_thinking":True,
                         # Openrouter Thinking configuration
                         "reasoning": {"enabled": True},
                        # SGlang Thinking configuration
                        "separate_reasoning": True,
                     }
                )

            # If the response is empty, retry
            if not response or not response.choices[0]:
                logger.warning("Empty response from LLM. Retrying......")
                time.sleep(60)
                continue
            
            result = response.choices[0].message.content if response.choices[0].message.content is not None else ""

            tool_calls = response.choices[0].message.tool_calls
            # Extract function call information if available
            if tool_calls:
                function_call = tool_calls[0].function.name
                function_call_id = tool_calls[0].id
                arguments = json.loads(
                    tool_calls[0].function.arguments
                )
                tool_call = ToolCall(function_call=function_call, function_call_id=function_call_id, arguments=arguments)


            # Log the query and response for debugging
            logger.debug(f"Query messages:\n{messages}")
            logger.debug(f"Response\n{response}")

            if result == "" and not tool_calls:
                logger.warning("Empty response from LLM. Retrying......")
                time.sleep(60)
                continue
            
            # Record the token usage for this API call
            record_token_usage(response, logger)
            out_messages = response.choices[0].message
            break
        except TokenLenWillExceed:
            raise
        except TokenLenExceed:
            raise
        except openai.RateLimitError:
            logger.warning("Rate Limit Exceeded. Retrying......")
            time.sleep(10)
        except openai.InternalServerError as e:
            err_msg = str(e)
            logger.warning(f"Service Overloaded. Error message: {err_msg}. Retrying......")
            time.sleep(10)
        except openai.APITimeoutError:
            logger.warning("LLM API Query Timed Out. Retrying......")
            time.sleep(10)
        except Exception as e:
            logger.warning(f"Error in LLM API query: {e}")
        finally:
            retry += 1

        if retry >= RETRY_CNT:
            logger.error("Max allowed retry count reached. Exiting......")
            result = "Error: LLM Query Failed."
            break
    
    # Log the parsed thinking, result, function call and arguments
    if think:
        logger.debug(f"LLM Thinking:\n {think}")  # For thinking models
    logger.debug(f"LLM Answer:\n{result}")

    return result, tool_call, out_messages


def record_token_usage(response: openai.ChatCompletion, logger: Logger):
    """
    Record token usage.
    """
    if (
        hasattr(response, "usage")
        and hasattr(response.usage, "completion_tokens")
        and hasattr(response.usage, "prompt_tokens")
        and hasattr(response.usage, "total_tokens")
    ):
        # Record current API call token usage
        cached_token = 0
        if response.usage:
            current_completion_tokens = response.usage.completion_tokens
            current_prompt_tokens = response.usage.prompt_tokens
            current_total_tokens = response.usage.total_tokens
        
            if hasattr(response.usage, "prompt_tokens_details") and response.usage.prompt_tokens_details is not None:
                prompt_tokens_details = response.usage.prompt_tokens_details
                cached_token = prompt_tokens_details.cached_tokens or 0

        logger.info(
            f"Response Tokens\nCompletion Tokens:{current_completion_tokens}\nPrompt Tokens:{current_prompt_tokens}\nTotal Tokens:{current_total_tokens}\nCached Tokens:{cached_token}"
        )

        if current_total_tokens >= CONFIG.LLMARGs["MAX_TOKEN_LEN"]:
            raise TokenLenExceed(current_total_tokens, CONFIG.LLMARGs["MAX_TOKEN_LEN"])
    
        if current_total_tokens >= CONFIG.LLMARGs["MAX_TOKEN_LEN"] * CONFIG.LLMARGs["REMINDER_TOKEN_RATIO"]:
            raise TokenLenWillExceed(current_total_tokens, CONFIG.LLMARGs["MAX_TOKEN_LEN"])

        # Update global token statistics
        global global_prompt_tokens, global_completion_tokens, global_total_tokens
        global_prompt_tokens += current_prompt_tokens
        global_completion_tokens += current_completion_tokens
        global_total_tokens += current_total_tokens

        # Log global cumulative token usage
        logger.debug(
            f"Global Token Statistics\nCumulative Prompt Tokens:{global_prompt_tokens}\nCumulative Completion Tokens:{global_completion_tokens}\nCumulative Total Tokens:{global_total_tokens}"
        )


def get_global_token_stats():
    """
    Get global token statistics.

    Returns:
        dict: Dictionary containing cumulative prompt_tokens, completion_tokens, total_tokens
    """
    return {
        "cumulative_prompt_tokens": global_prompt_tokens,
        "cumulative_completion_tokens": global_completion_tokens,
        "cumulative_total_tokens": global_total_tokens,
    }


def reset_global_token_stats():
    """
    Reset global token statistics.
    """
    global global_prompt_tokens, global_completion_tokens, global_total_tokens
    global_prompt_tokens = 0
    global_completion_tokens = 0
    global_total_tokens = 0
