import json
import os
import time
from typing import List, Dict, Any

from src.utils.llm import query_llm
from src.utils.config import CONFIG
from src.utils.log import get_logger
from openai import OpenAI
from src.utils.project import get_agent_summary_file

# Maximum length for showing summaries to manager
# This is used to limit the length of summaries displayed in the manager's interface
MAX_SHOW_SUMMARY_LENGTH = 500
RETRY_CNT = 5

SUMMARIZATION_LEADING_PROMPT = """
You are a professional AI Agent runtime process summarizer. You will be given a conversation history of the Agent's execution. Please carefully analyze the complete execution process of the Agent and generate a clear, structured summary.

**Summary Requirements:**
Please generate a concise but comprehensive summary that includes the following elements:
1. **Task Understanding**: How the Agent understood and interpreted the input task
2. **Execution Strategy**: Main execution strategies and methodologies adopted by the Agent
3. **Key Steps**: Major steps and decision points during execution
4. **Problems Encountered**: Issues encountered during execution and their solutions
5. **Final Results**: Task completion status and output results
6. **Lessons Learned**: Key experiences that can be referenced for subsequent runs

**Conversation History Format:**
The conversation history will be provided in the following. The content before the marker "=== End of Historical Records ===" is the conversation history.

=== Begin of Historical Records ===
"""

SUMMARIZATION_TAIL_PROMPT = """
=== End of Historical Records ===

You are the professional AI Agent runtime process summarizer. All above is the conversation history. Please generate a summary based on the conversation history.

**Output Format Requirements:**
Please output the summary in JSON format with the following structure:
```json
{{
    "task_understanding": "Understanding of the task",
    "execution_strategy": "Description of execution strategy",
    "key_steps": ["Step 1", "Step 2", "Step 3"],
    "problems_encountered": ["Problem 1 and solution", "Problem 2 and solution"],
    "final_result": "Description of final result",
    "lessons_learned": ["Lesson 1", "Lesson 2", "Lesson 3"]
}}
```

Please ensure the summary content is accurate, concise, and practically valuable for reference in subsequent Agent runs.
"""


class AgentSummarizer:
    """LLM-based Agent runtime summarizer"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"), 
            base_url=CONFIG.LLMARGs["OPENAI_API_BASE"]
        )
        self.logger = get_logger("AgentSummarizer")
        self.summary_file = get_agent_summary_file()
        
    

    def generate_summary(
        self,
        agent_name: str,
        original_input: str,
        exit_output: str,
        conversation_history: List[Dict],
    ) -> Dict[str, Any]:
        """Generate Agent runtime summary"""
        try:
            messages = [
                {"role": "system", "content": SUMMARIZATION_LEADING_PROMPT},
            ]
            messages.extend(conversation_history)
            messages.append({"role": "user", "content": SUMMARIZATION_TAIL_PROMPT})
            
            response, _ = query_llm(client=self.client, messages=messages, tools=[], logger=self.logger, tool_choice="none")
            
            # Try to parse JSON response
            try:
                # Extract JSON part
                start = response.find('{')
                end = response.rfind('}') + 1
                if start != -1 and end > start:
                    json_str = response[start:end]
                    summary_data = json.loads(json_str)
                else:
                    # If no JSON found, use default format
                    summary_data = {
                        "task_understanding": "Failed to extract task understanding information",
                        "execution_strategy": "Failed to extract execution strategy information",
                        "key_steps": ["Information extraction failed"],
                        "problems_encountered": ["Information extraction failed"],
                        "final_result": exit_output,
                        "lessons_learned": ["Information extraction failed"],
                        "raw_response": response
                    }
            except json.JSONDecodeError:
                # JSON parsing failed, save raw response
                summary_data = {
                    "task_understanding": "JSON parsing failed",
                    "execution_strategy": "JSON parsing failed", 
                    "key_steps": ["JSON parsing failed"],
                    "problems_encountered": ["JSON parsing failed"],
                    "final_result": exit_output,
                    "lessons_learned": ["JSON parsing failed"],
                    "raw_response": response
                }
                
            return summary_data
            
        except Exception as e:
            self.logger.error(f"Failed to generate summary: {e}")
            return {
                "task_understanding": f"Summary generation failed: {str(e)}",
                "execution_strategy": "Summary generation failed",
                "key_steps": ["Summary generation failed"],
                "problems_encountered": ["Summary generation failed"],
                "final_result": exit_output,
                "lessons_learned": ["Summary generation failed"]
            }
    
    def save_agent_summary(self, agent_name: str, original_input: str, 
                          exit_output: str, summary: Dict[str, Any]) -> None:
        """Save Agent summary to file"""
        try:
            # Extract actual task from potentially nested historical input
            actual_task = self.extract_actual_task_from_input(original_input)

            # Read existing summary file
            if os.path.exists(self.summary_file):
                with open(self.summary_file, "r", encoding="utf-8") as f:
                    summaries = json.load(f)
            else:
                summaries = {}

            # Calculate the run count for this Agent
            agent_runs = [
                key for key in summaries.keys() if key.startswith(f"{agent_name}_")
            ]
            run_number = len(agent_runs) + 1

            # Create new summary entry with cleaned task input
            key = f"{agent_name}_{run_number}"
            summaries[key] = {
                "Original_Input": actual_task,
                "Exit_Information": exit_output,
                "Running_Summary": summary,
            }

            # Save to file
            with open(self.summary_file, "w", encoding="utf-8") as f:
                json.dump(summaries, f, ensure_ascii=False, indent=2)

            self.logger.info(f"Agent summary saved: {key}")

        except Exception as e:
            self.logger.error(f"Failed to save summary: {e}")

    def get_agent_history_summaries(
        self, agent_name: str, max_count: int = 3
    ) -> List[Dict[str, Any]]:
        """Get historical summaries for specified Agent"""
        try:
            if not os.path.exists(self.summary_file):
                return []

            with open(self.summary_file, "r", encoding="utf-8") as f:
                summaries = json.load(f)

            # Find all historical run records for this Agent
            agent_summaries = []
            for key, value in summaries.items():
                if key.startswith(f"{agent_name}_"):
                    agent_summaries.append({"run_id": key, "summary": value})

            # Sort by run number, take the most recent ones
            agent_summaries.sort(
                key=lambda x: int(x["run_id"].split("_")[-1]), reverse=True
            )
            return agent_summaries[:max_count]

        except Exception as e:
            self.logger.error(f"Failed to get historical summaries: {e}")
            return []

    def format_history_for_agent(self, agent_name: str, max_count: int = 3) -> str:
        """Format historical summaries for Agent use"""
        histories = self.get_agent_history_summaries(agent_name, max_count)

        if not histories:
            return ""
        
        formatted_history = f"\n=== {agent_name} Historical Execution Records ===\n"

        for i, history in enumerate(histories, 1):
            summary_data = history["summary"]
            running_summary = summary_data.get("Running_Summary", {})

            # The original task should now be clean (no nested history)
            original_task = summary_data.get("Original_Input", "N/A")

            # Calculate execution number (most recent first)
            formatted_history += f"\nExecution #{history['run_id']}:\n"
            formatted_history += f"- Original Task: {original_task[:MAX_SHOW_SUMMARY_LENGTH]}{'...' if len(original_task) > MAX_SHOW_SUMMARY_LENGTH else ''}\n"
            # formatted_history += f"- Task Understanding: {running_summary.get('task_understanding', 'N/A')[:MAX_SHOW_SUMMARY_LENGTH]}{'...' if len(running_summary.get('task_understanding', '')) > MAX_SHOW_SUMMARY_LENGTH else ''}\n"
            # formatted_history += f"- Execution Strategy: {running_summary.get('execution_strategy', 'N/A')[:MAX_SHOW_SUMMARY_LENGTH]}{'...' if len(running_summary.get('execution_strategy', '')) > MAX_SHOW_SUMMARY_LENGTH else ''}\n"
            # formatted_history += f"- Main Tools: {', '.join(running_summary.get('tools_used', []))}\n"
            formatted_history += f"- Final Result: {running_summary.get('final_result', 'N/A')[:MAX_SHOW_SUMMARY_LENGTH]}{'...' if len(running_summary.get('final_result', '')) > MAX_SHOW_SUMMARY_LENGTH else ''}\n"
            # formatted_history += f"- Key Lessons: {'; '.join(running_summary.get('lessons_learned', []))[:MAX_SHOW_SUMMARY_LENGTH]}{'...' if len('; '.join(running_summary.get('lessons_learned', []))) > MAX_SHOW_SUMMARY_LENGTH else ''}\n"

        formatted_history += "\nPlease refer to the above historical experiences to complete the current task.\n"
        formatted_history += "=== End of Historical Records ===\n\n"

        return formatted_history

    def extract_actual_task_from_input(self, input_with_history: str) -> str:
        """Extract the actual task from input that may contain historical context"""
        if not input_with_history:
            return ""

        # Look for the LAST occurrence of historical records end marker
        # This handles nested historical records correctly
        end_marker = "=== End of Historical Records ==="

        # Find the last occurrence of the end marker
        last_end_pos = input_with_history.rfind(end_marker)

        if last_end_pos != -1:
            # Extract everything after the last end marker
            start_pos = last_end_pos + len(end_marker)
            actual_task = input_with_history[start_pos:].strip()

            if actual_task:
                return actual_task
            else:
                return "No actual task found"

        # If no end marker found, check if this contains historical data at all
        if "Historical Execution Records" in input_with_history:
            # This input contains historical data but no proper end marker
            # Try to extract the task from the end of the input

            # Split by lines and try to find the actual task
            lines = input_with_history.split("\n")

            # Find the last occurrence of any task indicator
            actual_task_lines = []
            task_started = False

            for i in range(len(lines) - 1, -1, -1):  # Iterate backwards
                line = lines[i].strip()

                # Skip empty lines
                if not line:
                    if task_started:
                        actual_task_lines.insert(0, "")
                    continue

            if actual_task_lines:
                extracted = "\n".join(actual_task_lines).strip()
                return extracted
            else:
                return "Task extraction failed - unable to identify actual task content"

        # If no historical context detected, return original input
        return input_with_history
    
    def generate_and_save_summary(self, agent_name, original_input: str, exit_reason: str, conversation_history: List[Dict]):
        """Generate and save Agent runtime summary"""
        try:
            # Generate summary
            summary = self.generate_summary(
                agent_name=agent_name,
                original_input=original_input or "No input provided",
                exit_output=exit_reason or "No exit reason provided",
                conversation_history=conversation_history
            )
            
            # Save summary
            self.save_agent_summary(
                agent_name=agent_name,
                original_input=original_input or "No input provided",
                exit_output=exit_reason or "No exit reason provided",
                summary=summary
            )
            
            self.logger.info(f"{agent_name} runtime summary generated and saved")
            
        except Exception as e:
            self.logger.error(f"Failed to generate summary: {e}")
