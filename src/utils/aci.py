import re
import os
import time
import json
import subprocess
import select
import threading
import signal
import psutil
import logging
import pty

from src.utils.llm import ToolCall
from src.tools.ToolCollection import TOOLs, SOURCE_TOOL_LIST
from .config import CONFIG
from src.utils.project import get_project_source_dir
import shlex

class EmptyFunctionCallError(Exception):
    """
    Raised when the LLM response does not contain any function calls.
    """

    message = "LLM response does not contain any function calls. Please check your response. You should always call a function you want to execute in your response."

    def __init__(self):
        message = self.message
        super().__init__(message)


class InvalidResponseFormatError(Exception):
    """
    Raised when the LLM response does not contain the required fields.
    """

    message = "You did not return any response and function calls. Please check your response. You should always return a response or function calls in your response."

    def __init__(self):
        message = self.message
        super().__init__(message)

class NotAllowedCommandError(Exception):
    """
    Raised when the command is not allowed.
    """

    message = """The command `{cmd}` or its arguments are not allowed. Please check your tool call arguments.
    NOTES: 
    - Interactivate edit commands are not allowed. 
    - You are only allowed to write files under `$OUTPUT`,`/tmp` and `$SRC`.
    """

    def __init__(self, cmd):
        message = self.message.format(cmd=cmd)
        super().__init__(message)

class ACI:
    """
    The Agent-Computer Interface class.
    This class should handle all communication with the bash subprocess.
    """

    config = CONFIG

    def __init__(self, logger: logging.Logger):
        # Set the logger
        self.logger = logger

        # Initialize global state variables
        self.open_file = "n/a"
        self.working_dir = get_project_source_dir()
        self.timeout = False
        self.master_fd = None
        self.slave_fd = None
        self.system_info = ""
        self.env_variables = None
        self.envs = None

        # Load the configs and initialize the command
        self.init_cmd = self._init_cmd()

        # Initialize the ACI
        self.bash_subprocess = self._init_aci()

    def _init_cmd(self) -> str:
        """
        Load the configs and generate the ACI initialization command.
        """
        # Load environment variables
        self.env_variables = self.config.get_aci_variables()
        export_cmd = ""
        for sub_key, sub_value in self.env_variables.items():
            export_cmd += f"export {sub_key}={sub_value}\n"

        return f"{export_cmd}\nalias ls='ls -F'\ncd {self.working_dir}\n"


    def cmd_guardrail(self, command: str) -> bool:
        """
        Check if the action input is a command that is not allowed to run.

        Returns True if the command should be blocked.

        Blocking rules:
        - interactive editor commands are blocked (same as before)
        - any command that writes files outside allowed directories is blocked.
          Allowed directories: $OUTPUT, $SRC (from self.env_variables or os.environ), and /tmp and their subdirectories.
        """

        editor_commands_pattern = r"\b(nano|vi|vim|emacs|gedit|pico|crontab -e|ex|jed|joe|mcedit|nedit|pico|rlwrap|scite|vimx|xemacs|zile|exit)\b"

        if not command:
            return False

        # Only inspect the first logical line
        first_line = command.splitlines()[0].strip()
        if not first_line:
            return False

        # Block interactive editors
        if re.search(editor_commands_pattern, first_line):
            return True

        # Build allowed directories (real paths).
        # Prefer environment variables provided in self.env_variables (set by ACI),
        # fallback to os.environ.
        allowed_dirs = []
        for key in ("OUTPUT", "SRC"):
            v = None
            if self.env_variables and key in self.env_variables:
                v = self.env_variables.get(key)
            if not v:
                v = os.environ.get(key)
            if v:
                allowed_dirs.append(os.path.realpath(os.path.expanduser(os.path.expandvars(v))))
        allowed_dirs.extend([
            os.path.realpath("/tmp"),
            os.path.realpath("/dev/null"),
            os.path.realpath("/dev/tty"),
            os.path.realpath("/dev/pts"),
            os.path.realpath("/dev/ptmx"),
            os.path.realpath("/dev/fd"),
            os.path.realpath("/dev/stdout"),
            os.path.realpath("/dev/stderr"),
            os.path.realpath("/dev/console"),
            os.path.realpath("/dev/random"),
            os.path.realpath("/dev/urandom"),
        ])
        # Deduplicate
        allowed_dirs = list(dict.fromkeys(allowed_dirs))

        # Helper to normalize and check a path candidate
        def _is_allowed_path(path_token: str) -> bool:
            if not path_token:
                return True
            # strip quotes
            path_token = path_token.strip().strip("'\"")
            # expand env vars and user
            path_token = os.path.expanduser(os.path.expandvars(path_token))
            # ignore obvious non-path tokens (like &, |, ;, pipelines)
            if path_token in {"|", "&", ";"}:
                return True
            # If token looks like a file descriptor (/dev/...) allow (not a workspace write)
            # But conservative approach: check real path if possible
            try:
                if not os.path.isabs(path_token):
                    abs_path = os.path.realpath(os.path.join(self.working_dir or "/", path_token))
                else:
                    abs_path = os.path.realpath(path_token)
            except Exception:
                # If we cannot resolve, be conservative and block
                return False
            # Check if abs_path is under any allowed dir
            for d in allowed_dirs:
                if abs_path == d or abs_path.startswith(d + os.sep):
                    return True
            return False

        # Tokenize the command safely
        try:
            tokens = shlex.split(first_line, posix=True)
        except Exception:
            tokens = first_line.split()

        # Collect candidate path tokens to examine for writes/edits.
        # Strategy:
        # - Always inspect explicit redirections (>, >>, 2>, etc.) — they indicate writes.
        # - Use a conservative blacklist of commands that are known to write/modify files (cp, mv, install, tee, dd, touch, mkdir, chmod, chown, ln, rsync, truncate, sed -i, perl -i, etc.).
        # - Do NOT add generic "looks like a path" heuristics for arbitrary commands such as find/ls/grep.
        candidates = []

        # Redirection operators that indicate a write target
        redir_ops = {">", ">>", "2>", "2>>", "1>", "1>>", ">&"}

        # Commands that explicitly write/modify files (blacklist).
        # Keep this list focused to avoid false positives.
        write_blacklist = {
            "cp",
            "mv",
            "install",
            "tee",
            "dd",
            "truncate",
            "touch",
            "mkdir",
            "chmod",
            "chown",
            "ln",
            "rsync",
        }

        # Commands that are normally read-only; we won't treat their args as write targets
        # unless a redirection is present (handled above).
        safe_readonly = {"find", "ls", "grep", "rg", "fd", "locate", "find_file", "ack", "ag"}

        for i, tok in enumerate(tokens):
            # explicit redirections (e.g. '>' '2>' followed by a filename)
            if tok in redir_ops and i + 1 < len(tokens):
                candidates.append(tokens[i + 1])
                continue
            # combined redirection like '>file' or '2>file'
            for op in redir_ops:
                if tok.startswith(op) and len(tok) > len(op):
                    candidates.append(tok[len(op) :])
                    break

            # Normalize command token for checking (strip options like leading './' etc not expected here)
            cmd_name = tok
            # If token contains '=', it's likely an option (e.g., of=/path); skip treating as command
            if "=" in cmd_name:
                cmd_name = cmd_name.split("=", 1)[0]
            cmd_name = cmd_name.lower()

            # If command is in the explicit write blacklist, collect likely targets according to common syntax
            if cmd_name in write_blacklist:
                if cmd_name == "tee":
                    for j in range(i + 1, len(tokens)):
                        if tokens[j].startswith("-"):
                            continue
                        if tokens[j] in {"|", "&", ";"}:
                            break
                        candidates.append(tokens[j])
                    continue

                if cmd_name in {"cp", "mv", "rsync"}:
                    # destination is usually the last non-option token after this command
                    for j in range(len(tokens) - 1, i, -1):
                        if tokens[j] in {"|", "&", ";"}:
                            continue
                        if not tokens[j].startswith("-"):
                            candidates.append(tokens[j])
                            break
                    continue

                if cmd_name in {"mkdir", "touch", "chmod", "chown", "ln", "truncate"}:
                    for j in range(i + 1, len(tokens)):
                        if tokens[j] in {"|", "&", ";"}:
                            break
                        if tokens[j].startswith("-"):
                            continue
                        # Heuristic: treat tokens that look like paths as targets
                        if tokens[j].startswith(("/", "./", "../", "~")) or "/" in tokens[j] or re.search(r"\.\w{1,6}$", tokens[j]):
                            candidates.append(tokens[j])
                    continue

                if cmd_name == "dd":
                    # dd uses of=FILE to write; also if of is separate arg like of=path
                    # check current token and following tokens for of=
                    if "of=" in tok:
                        ofval = tok.split("of=", 1)[1]
                        if ofval:
                            candidates.append(ofval)
                    for j in range(i + 1, len(tokens)):
                        if tokens[j].startswith("of="):
                            candidates.append(tokens[j].split("=", 1)[1])
                        # also stop if pipe/ctl
                        if tokens[j] in {"|", "&", ";"}:
                            break
                    continue

                # Generic: if blacklisted cmd but no special parsing above, collect following path-like tokens
                for j in range(i + 1, len(tokens)):
                    if tokens[j] in {"|", "&", ";"}:
                        break
                    if tokens[j].startswith("-"):
                        continue
                    if tokens[j].startswith(("/", "./", "../", "~")) or "/" in tokens[j] or re.search(r"\.\w{1,6}$", tokens[j]):
                        candidates.append(tokens[j])
                continue

            # sed/perl in-place edits: only consider files when -i is present
            if cmd_name in {"sed", "perl"} and "-i" in tokens:
                for j in range(i + 1, len(tokens)):
                    if tokens[j] in {"|", "&", ";"}:
                        break
                    if tokens[j].startswith("-"):
                        continue
                    candidates.append(tokens[j])
                continue

            # For safe read-only commands we do not collect path candidates (unless redirection already did)
            if cmd_name in safe_readonly:
                continue

            # Otherwise: do not add generic "looks like a path" tokens here to avoid false positives.
            # Redirections and blacklisted commands cover the common write cases.

        # If no write targets were found, allow
        if not candidates:
            return False

        # Validate each candidate; if any candidate is outside allowed dirs, block
        for c in candidates:
            if not _is_allowed_path(c):
                # log and block (True = blocked)
                try:
                    self.logger.warning(f"Guardrail blocked write to path candidate: {c}")
                except Exception:
                    pass
                return True

        return False

    def read_from_fd(self, fd, timeout: int | float = 10) -> bytes:
        """
        Read data from a subprocess with a timeout.
        This function uses a file descriptor to read data from the subprocess in a non-blocking way.
        """
        data = b""
        start_time = time.time()
        while time.time() - start_time < timeout:
            ready, _, _ = select.select([fd], [], [], timeout / 2.0)
            if fd in ready:
                part = os.read(fd, 4096)  # Read in chunks to handle large outputs
                if not part:
                    break
                data += part
            else:
                # If timeout is specified, and no data is ready, break
                if timeout and time.time() - start_time > timeout:
                    break
        return data

    def update_state(self):
        """
        Read the state of the bash subprocess and update global variables.
        """
        try:
            if self.bash_subprocess.poll() is None:
                cwd = psutil.Process(self.bash_subprocess.pid).cwd()
                if cwd and not cwd.isspace():
                    self.working_dir = cwd

                self._get_bash_env_variables()
                current_file = self.envs.get("CURRENT_FILE") if self.envs else None
                if current_file and not current_file.isspace():
                    self.open_file = current_file
                else:
                    self.open_file = "n/a"
        except Exception as e:
            self.logger.info(f":Failed to update state!\n")
            # raise Exception("Failed to update state!")

    def clean_ansi_codes(self, input: str) -> str:
        """
        Clean ANSI control sequences from the given input string and return the cleaned text.
        """
        ansi_escape = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
        cleaned_text = ansi_escape.sub("", input).strip()
        return cleaned_text

    def kill_process(self, pids: list[int]) -> int:
        """
        Kill the given processes.
        """
        self.logger.warning("Command timed out. Trying to terminate the process......")
        try:
            if pids:
                self.logger.info("Terminating the process...")
                fail_flag = False
                for pid in pids:
                    if psutil.pid_exists(pid):
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except Exception:
                            # ignore per-pid kill errors and continue
                            pass
                    else:
                        self.logger.warning(
                            f"The process with PID {pid} does not exist."
                        )
                        fail_flag = True
                        continue
                    if psutil.pid_exists(pid):  # Check if the process is terminated
                        try:
                            os.kill(pid, signal.SIGKILL)
                            self.logger.warning(
                                "Process was not terminated successfully. Killing the process..."
                            )
                        except Exception:
                            pass
                    else:
                        self.logger.info(
                            f"The process with PID {pid} has been terminated."
                        )
                if fail_flag:
                    self.logger.error("One or more processes failed to terminate.")
                    return 1
                else:
                    return 0
            else:
                # No pids provided: try to interrupt the current command on the pty
                self.logger.warning(
                    f"No process to kill. Attempting to interrupt the pty and check bash."
                )
                try:
                    if self.master_fd is not None:
                        # send Ctrl-C to interrupt any running foreground job
                        os.write(self.master_fd, b"\x03")
                        os.write(self.master_fd, f"\n".encode())
                except Exception as e:
                    self.logger.debug(f"write to master_fd failed: {e}")

                time.sleep(0.2)
                # If bash is dead or gone, restart it to recover a clean shell
                try:
                    if (
                        self.bash_subprocess is None
                        or self.bash_subprocess.poll() is not None
                    ):
                        self.logger.warning("bash is dead or gone, restarting bash...")
                        try:
                            self._restart_bash(self.envs or {})
                        except Exception as e:
                            self.logger.error(f"Failed to restart bash: {e}")
                            return 1
                    else:
                        self.logger.info(
                            "bash still alive after interrupt, restarting bash..."
                        )
                        try:
                            self._restart_bash(self.envs or {})
                        except Exception as e:
                            self.logger.error(f"Failed to restart bash: {e}")
                            return 1
                except Exception as e:
                    # as a fallback try to restart bash
                    self.logger.error(f"Error checking bash status: {e}")
                    try:
                        if (
                            self.bash_subprocess is None
                            or self.bash_subprocess.poll() is not None
                        ):
                            self._restart_bash(self.envs or {})
                    except Exception:
                        pass
                return 0
        except Exception as e:
            self.logger.error(
                f"Error while killing the processes. PID list: {pids}, Error: {e}"
            )
            # attempt to recover bash if it's dead
            try:
                if (
                    self.bash_subprocess is None
                    or self.bash_subprocess.poll() is not None
                ):
                    self._restart_bash(self.envs or {})
            except Exception:
                pass
            return 1

    def get_child_pid(self, bash_pid: int) -> list[int]:
        """
        Get child PIDs using psutil.
        """
        try:
            parent = psutil.Process(bash_pid)
            children = parent.children(recursive=True)
            if children:
                return [child.pid for child in children]
            else:
                return []
        except psutil.NoSuchProcess as e:
            self.logger.warning(f"No process with PID {bash_pid} exists.")
            raise e

    def kill_process_tree(self, bash_process: subprocess.Popen):
        """
        Kill the given process and all its children.
        """
        pid = bash_process.pid
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                os.kill(child.pid, signal.SIGTERM)
            os.kill(pid, signal.SIGKILL)
        except psutil.NoSuchProcess:
            self.logger.warning(f"No process with PID {pid} exists.")
        self.bash_subprocess.terminate()
        self.bash_subprocess.wait()

    def _init_aci(self) -> subprocess.Popen:
        """
        Initialize the ACI and return a Popen object.
        """
        self.master_fd, self.slave_fd = pty.openpty()
        bash_subprocess = subprocess.Popen(
            ["/bin/bash"],
            stdin=self.slave_fd,
            stdout=self.slave_fd,
            stderr=self.slave_fd,
            preexec_fn=os.setsid,
            universal_newlines=True,
            env=os.environ,
            cwd=self.working_dir,
            user="root",
        )
        os.write(
            self.master_fd, f"{self.init_cmd}\n".encode()
        )  # Enter the initialization command to the pseudo terminal
        time.sleep(0.5)
        os.write(
            self.master_fd, f'export PS1=""\nexport PS2=""\nstty -echo\n'.encode()
        )  # Disable pseudo-terminal echo
        time.sleep(0.5)
        self.read_from_fd(self.master_fd, 1)  # Flush the `stdout` pipe

        return bash_subprocess

    def _get_bash_env_variables(self):
        """
        Save the environment variables of the current bash subprocess.
        """
        envs = {}
        if (
            self.bash_subprocess and self.bash_subprocess.poll() is None
        ):  # Check if the bash subprocess is still running
            # Get the current working directory
            if not self.master_fd:
                raise Exception("The master fd in ACI didn't initialize.")
            os.write(self.master_fd, b"pwd\n")
            time.sleep(0.5)
            pwd_output = self.read_from_fd(self.master_fd, 1).decode().strip()
            if pwd_output:
                envs["PWD"] = pwd_output

            # Get the environment variables from the bash subprocess
            os.write(self.master_fd, b"env\n")
            time.sleep(0.5)
            output = self.read_from_fd(self.master_fd, 1).decode()
            for line in output.splitlines():
                if "=" in line:
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key, value = parts
                        envs[key] = value
                    envs[key] = value
        self.envs = envs

    def _restart_bash(self, envs: dict):
        """
        Restart the bash subprocess with the given environment variables
        """
        self.logger.warning("Restarting the bash subprocess......")

        # Get a new bash subprocess bash subprocess
        if self.bash_subprocess:
            self.bash_subprocess.terminate()
            self.bash_subprocess.wait()
        self.bash_subprocess = self._init_aci()
        if not self.master_fd:
            raise Exception("Restart bash failed. The master fd has not been initialized.")
        # Recover the working directory
        if self.working_dir:
            os.write(self.master_fd, f"cd {self.working_dir}\n".encode())

        # Write the environment variables to the new bash subprocess
        for key, value in envs.items():
            os.write(self.master_fd, f"export {key}={value}\n".encode())
        time.sleep(0.5)

    def _run_command_with_timeout(
        self,
        bash_subprocess: subprocess.Popen,
        command: str,
        timeout: float,
        max_output_lines: int,
        update: bool = True,
    ) -> tuple[str, str]:
        """
        The implementation to run a given command in the bash subprocess's bash terminal.
        """
        if not self.master_fd:
            raise Exception("The master fd has not been initialized.")
        _, ready_to_write, _ = select.select([], [self.master_fd], [], 1)
        if ready_to_write:
            self.timeout = False  # Reset the command timeout flag
            command = command if command.endswith("\n") else command + "\n"
            output = ""
            exit_code = ""
            # Runs the command `command` in the shell whose handle is `bash_subprocess` and return the exit code of `command`.
            # Three steps to execute a command:
            # 1. Run the command with a timeout.
            # 2. Save the exit code.
            # 3. Echo the sentinel.
            END_SENTINEL = "END_SENTINEL"  # This must be different from all lines of output from the command.
            SAVED_CODE = "MY_SAVED_EXIT_CODE"  # This must be different from all environment variables in the shell.

            if timeout > 0:  # Has a timeout
                # Write the command to the pseudo terminal
                os.write(
                    self.master_fd,
                    f"{command}\n{SAVED_CODE}=$?\necho {END_SENTINEL}\n".encode(),
                )

                # Get the PID of the bash process for timeout handling
                bash_pid = bash_subprocess.pid
                command_pids = self.get_child_pid(bash_pid)

                # Timeout handler, kill the process if it times out
                def wrapper(*args):
                    self.timeout = True
                    kill_exit_code = self.kill_process(*args)
                    self.logger.warning(f"Killing return code: {kill_exit_code}.")
                    if kill_exit_code == 1:  # Killing the process failed
                        # Send a Ctrl+C signal to the persudo terminal to interrupt the command
                        # This may terminate the bash subprocess, so we need to check if the bash subprocess is still running
                        if self.bash_subprocess.poll() is None:
                            if not self.master_fd:
                                raise Exception("The master fd has not been initialized.")
                            os.write(self.master_fd, b"\x03") 
                            os.write(self.master_fd, f"\n".encode())
                            time.sleep(0.2)
                        # If the bash subprocess is still running, we can continue to read the output
                        if self.bash_subprocess.poll() is None:
                            if not self.master_fd:
                                raise Exception("The master fd has not been initialized.")
                            os.write(
                                self.master_fd,
                                f"{SAVED_CODE}=$?\necho {END_SENTINEL}\necho ${SAVED_CODE}\n".encode(),
                            )
                            time.sleep(0.5)
                    # Check if the bash subprocess is dead and if it is, restart the bash subprocess
                    if self.bash_subprocess.poll() is not None:
                        self.logger.warning("Bash subprocess is dead, restarting...")
                        self._restart_bash(self.envs or {})
                    return

                # Use deamon thread to handle timeout
                # This will not block the main thread and will be killed when the main thread exits
                timer = threading.Timer(timeout, wrapper, args=(command_pids,))
                timer.daemon = True

                # Read command output
                try:
                    timer.start()
                    # Read the output from the bash terminal using select+os.read to avoid
                    # blocking on a stale fd if master_fd is replaced by the timer thread.
                    local_fd = self.master_fd
                    buf = ""
                    overall_start = time.time()
                    found_sentinel = False
                    # loop up to `timeout+1`s to collect output of arbitrary length but avoid permanent hang
                    while time.time() - overall_start < timeout + 1:
                        # if master_fd changed (restart occurred), switch to the new fd
                        if local_fd != self.master_fd:
                            local_fd = self.master_fd
                        # wait for data on the current fd
                        try:
                            ready, _, _ = select.select([local_fd], [], [], 0.2)
                        except Exception:
                            # if select fails (e.g. fd invalid), retry after short sleep
                            time.sleep(0.05)
                            continue
                        if not ready:
                            # no data this tick
                            if self.timeout:
                                exit_code = "1"
                                break
                            continue
                        try:
                            part = os.read(local_fd, 4096)
                        except Exception:
                            # fd might be closed; allow loop to pick up new master_fd
                            time.sleep(0.05)
                            continue
                        if not part:
                            # EOF on this fd
                            break
                        s = part.decode(errors="ignore")
                        buf += s
                        # process complete lines
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            # Detect the end sentinel and read the exit code
                            if END_SENTINEL in line:
                                # ask shell to echo the saved exit code
                                try:
                                    os.write(
                                        self.master_fd, f"echo ${SAVED_CODE}\n".encode()
                                    )
                                except Exception:
                                    pass
                                time.sleep(0.2)
                                # read exit code with a small timeout
                                start_ec = time.time()
                                while time.time() - start_ec < 3:
                                    try:
                                        ready2, _, _ = select.select(
                                            [self.master_fd], [], [], 0.2
                                        )
                                    except Exception:
                                        time.sleep(0.05)
                                        continue
                                    if not ready2:
                                        continue
                                    try:
                                        part2 = os.read(self.master_fd, 4096)
                                    except Exception:
                                        time.sleep(0.05)
                                        continue
                                    if not part2:
                                        continue
                                    for l2 in part2.decode(
                                        errors="ignore"
                                    ).splitlines():
                                        if l2.strip().isdigit():
                                            exit_code = l2.strip()
                                            break
                                    if exit_code:
                                        break
                                found_sentinel = True
                                break
                            output += line + "\n"
                            if self.timeout:
                                exit_code = "1"
                                found_sentinel = True
                                break
                        if found_sentinel:
                            break
                    timer.cancel()
                except Exception as e:
                    timer.cancel()
                    self.logger.error(
                        f"Error occurred while running command {command}:\n {e}"
                    )

            else:  # No timeout
                os.write(
                    self.master_fd,
                    f"{command}\n{SAVED_CODE}=$?\necho {END_SENTINEL}\n".encode(),
                )

                # No timeout: still read using the safe select+os.read loop, but without timer
                local_fd = self.master_fd
                buf = ""
                found_sentinel = False
                overall_start = time.time()
                # loop up to `timeout+1`s to collect output of arbitrary length but avoid permanent hang
                while time.time() - overall_start < timeout + 1:
                    if local_fd != self.master_fd:
                        local_fd = self.master_fd
                    try:
                        ready, _, _ = select.select([local_fd], [], [], 0.2)
                    except Exception:
                        time.sleep(0.05)
                        continue
                    if not ready:
                        continue
                    try:
                        part = os.read(local_fd, 4096)
                    except Exception:
                        time.sleep(0.05)
                        continue
                    if not part:
                        break
                    s = part.decode(errors="ignore")
                    buf += s
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        if END_SENTINEL in line:
                            try:
                                os.write(
                                    self.master_fd, f"echo ${SAVED_CODE}\n".encode()
                                )
                            except Exception:
                                pass
                            time.sleep(0.2)
                            # read exit code
                            start_ec = time.time()
                            while time.time() - start_ec < 1:
                                try:
                                    ready2, _, _ = select.select(
                                        [self.master_fd], [], [], 0.2
                                    )
                                except Exception:
                                    time.sleep(0.05)
                                    continue
                                if not ready2:
                                    continue
                                try:
                                    part2 = os.read(self.master_fd, 4096)
                                except Exception:
                                    time.sleep(0.05)
                                    continue
                                if not part2:
                                    continue
                                for l2 in part2.decode(errors="ignore").splitlines():
                                    if l2.strip().isdigit():
                                        exit_code = l2.strip()
                                        break
                                if exit_code:
                                    break
                            found_sentinel = True
                            break
                        output += line + "\n"
                    if found_sentinel:
                        break

            # Identify blank output
            output = "" if output.isspace() else output.strip()

            # Check whether the command has timed out
            if self.timeout:
                output = self.clean_ansi_codes(output)
                self.logger.warning(f"Command timed out. Output:\n{output}")
                output += f"Command executed with timeout: {timeout} seconds."
            # Replace the output with a default message if it's empty
            if not output and exit_code == "0":
                output = ""
            # logger.info(f"Command\nCommand:\n{command}\nOutput:\n{output}")
            # logger.info(f"State\nopen_file: {self.open_file}\nworking_dir: {self.working_dir}")

            # Extract the latest lines of output to avoid too long output
            output = self.truncate_and_clean_output(output, max_output_lines)
            # Update the state of the bash subprocess
            if update and not self.timeout:
                self.timeout = False
                self.update_state()

            return output, exit_code

        else:
            fail_msg = (
                "The command failed to run since the interface is not ready to write."
            )
            return fail_msg, "1"

    def truncate_and_clean_output(self, output: str, max_output_lines: int) -> str:
        # Extract the latest lines of output to avoid too long output
        lines = output.splitlines() if output else []
        last_lines = lines[
            -min(max_output_lines, len(lines)) :
        ]
        output = "\n".join(last_lines)
        # In interactive shells, heredoc and multiline input can emit PS2 continuation
        # prompt lines like ">". Strip those standalone prompt artifacts.
        output = re.sub(r">\s*\n", "", output).strip()
        max_length = self.config.ACIARGs["MAX_OUTPUT_CHARACTERS"]
        if len(output) > max_length:
            head_len = int(max_length * 0.5)
            tail_len = max_length - head_len
            output = (
                output[:head_len] 
                + f"\n\n... [Truncated {len(output) - max_length} characters] ...\n\n" 
                + output[-tail_len:]
            )
        output = self.clean_ansi_codes(output)
        return output
        

    def convert_tool_call_to_command(self, tool_call: ToolCall) -> str:
        tool = TOOLs.get_tool(tool_call.function_call)
        if not tool:
            raise ValueError(f"The tool {tool_call.function_call} is not exists. Please check your tool call.")
        arguments = tool.arguments
        argument_list = [] if tool_call.function_call == "bash" else [tool_call.function_call]
        # source aci commands
        if tool_call.function_call in SOURCE_TOOL_LIST:
            argument_list.insert(0, "source")
        if not arguments:
            command = " ".join(argument_list)
            return command
        
        for arg in arguments:
            arg_name = arg.name
            arg_required = arg.required
            arg_redirect = arg.redirect
            arg_ty = arg.type
            arg_value = tool_call.arguments.get(arg_name)
            if arg_value is None and arg_required:
                raise ValueError(f"The argument {arg_name} is required. Please check your tool call.")
            if arg_value is not None and arg_redirect:
                argument_list.append(f"<< 'end_of_write'\n{arg_value}\nend_of_write")
                continue
            if arg_value is not None:
                if arg_ty == "string" and tool_call.function_call != "bash":
                    argument_list.append(f"\"{arg_value}\"")
                else:
                    argument_list.append(str(arg_value))
        command = " ".join(argument_list)
        #if tool_call.function_call == "bash":
        #    if self.cmd_guardrail(command):
        #        raise ValueError(f"The command {command} is not allowed. Please check your tool call.")
        return command

    def execute_tool_calling(self, tool_call: ToolCall) -> str:
        command = self.convert_tool_call_to_command(tool_call)
        self.logger.debug(msg=f"Executing tool calling: {command}")
        tool = TOOLs.get_tool(tool_call.function_call)
        if not tool:
            raise ValueError(f"The tool {tool_call.function_call} is not exists. Please check your tool call.")
        return self.run_command_with_timeout(command, float(tool.timeout), tool.max_output_lines,  True)
    

    def run_command_with_timeout(
        self, command: str, timeout: float, max_output_lines: int, update: bool = True
    ) -> str:
        """
        Save the environment variables before executing the command and check the child process's status after the command execution.
        """
        # Save the environment variables
        self._get_bash_env_variables()

        # Check the bash subprocess's status and restart it if it has terminated
        if self.bash_subprocess.poll() is not None:
            self.logger.info("The bash subprocess has terminated. Restarting...")
            self._restart_bash(self.envs or {})

        try:
            # Execute the command
            output, exit_code = self._run_command_with_timeout(
                self.bash_subprocess, command, timeout, max_output_lines, update
            )
        except psutil.NoSuchProcess as e:
            output = "Command timed out. Please try again."
            exit_code = "-1"
            self._restart_bash(self.envs or {})
        output = f"Command executed with exit code {exit_code}.\n{output}"
        return output
