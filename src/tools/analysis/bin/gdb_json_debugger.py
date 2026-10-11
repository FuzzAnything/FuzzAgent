import gdb
import json
import os
import sys
import re

def safe_execute(cmd):
    try:
        return gdb.execute(cmd, to_string=True).strip()
    except Exception as e:
        return f"Error: {e}"

def get_crash_context(error_msg="", command_output=""):
    context = {"status": "stopped", "error": error_msg, "command_output": command_output}                                                                           
    try:
        # Check if there is an active inferior before querying frame info
        inferiors = gdb.inferiors()
        running = any(inf.pid > 0 for inf in inferiors)
        if not running:
            context["status"] = "not_running"
            context["error"] = "Program is not running."
        else:
            try:
                # Auto-skip ASAN and libc frames to find the actual crashing location
                frame = gdb.selected_frame()
                while frame:
                    name = frame.name()
                    if name and any(skip in name for skip in ["__pthread_kill", "abort", "raise", "Die", "Abort", "ReportGenericError", "__asan_report", "ScopedInErrorReport"]):
                        frame = frame.older()
                        if frame:
                            frame.select()
                    else:
                        break

                # We disabled pwndbg stdout with context-output. We now route it to a temp file.
                try:
                    temp_pwndbg_file = "/tmp/pwndbg_output_buffer.txt"
                    if os.path.exists(temp_pwndbg_file):
                        os.remove(temp_pwndbg_file)
                    
                    # Ensure pwndbg gives us exactly what the user wants.
                    output_lines = []
                    
                    gdb.execute("set context-sections code")
                    gdb.execute(f"set context-output {temp_pwndbg_file}")
                    gdb.execute("context")
                    output_lines.append("1. Source Context")
                    with open(temp_pwndbg_file, "r") as f:
                        output_lines.append(f.read().replace("LEGEND: STACK | HEAP | CODE | DATA | WX | RODATA\n", "").replace("────────────────────────────────────────────────────────────────────────────────","").strip())
                    
                    gdb.execute("set context-sections stack")
                    gdb.execute(f"set context-output {temp_pwndbg_file}")
                    gdb.execute("context")
                    output_lines.append("\n2. Heap and Stack")
                    with open(temp_pwndbg_file, "r") as f:
                        output_lines.append(f.read().replace("LEGEND: STACK | HEAP | CODE | DATA | WX | RODATA\n", "").replace("────────────────────────────────────────────────────────────────────────────────","").strip())
                        
                    gdb.execute("set context-sections backtrace")
                    gdb.execute(f"set context-output {temp_pwndbg_file}")
                    gdb.execute("context")
                    output_lines.append("\n3. BACKTRACE")
                    with open(temp_pwndbg_file, "r") as f:
                        output_lines.append(f.read().replace("LEGEND: STACK | HEAP | CODE | DATA | WX | RODATA\n", "").replace("────────────────────────────────────────────────────────────────────────────────","").strip())
                    
                    # Strip ansi across all
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    pwndbg_clean = ansi_escape.sub('', "\n".join(output_lines))
                    context["pwndbg_context"] = pwndbg_clean
                            
                    os.remove(temp_pwndbg_file)
                except Exception as e:
                    context["error_pwndbg"] = str(e)
                    
                # Restore output
                try:
                    gdb.execute("set context-output stdout")
                    gdb.execute("set context-sections regs disasm code stack backtrace threads")
                except:
                    pass

                # If no pwndbg or it failed, try standard 'list'
                if "pwndbg_context" not in context:
                    try:
                        src = safe_execute("list")
                        if src and not src.startswith("Error"):
                            context["source"] = src
                    except Exception:
                        pass
                    
                    # Get standard fallback if pwndbg failed
                    context["backtrace"] = safe_execute("bt")
                    context["registers"] = safe_execute("info registers")
                
            except Exception as e:
                context["status"] = "error"
                context["error"] = f"No frame: {e}"
        
    except Exception as e:
        context["status"] = "error"
        context["error"] = str(e)
        
    print("\n===JSON_START===")
    print(json.dumps(context))
    print("===JSON_END===\n")

history_file = os.environ.get("GDB_HISTORY_FILE")

gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set print pretty on")
gdb.execute("set print array on")
gdb.execute("set print null-stop off")
gdb.execute("set follow-fork-mode parent")
gdb.execute("set detach-on-fork on")

asan_opts = os.environ.get("ASAN_OPTIONS", "")
if "abort_on_error" not in asan_opts:
    new_asan_opts = asan_opts + (":" if asan_opts else "") + "abort_on_error=1"
    gdb.execute(f"set env ASAN_OPTIONS={new_asan_opts}")

if history_file and os.path.exists(history_file):
    with open(history_file, 'r') as f:
        commands = [cmd.strip() for cmd in f.readlines() if cmd.strip()]
        
    cmd_outputs = []
    for cmd in commands:
        try:
            sys.stderr.write(f"(gdb) {cmd}\n")
            sys.stderr.flush()
            out = gdb.execute(cmd, to_string=True)
            if out:
                cmd_outputs.append(f"(gdb) {cmd}\n{out.strip()}")
        except gdb.error as e:
            cmd_outputs.append(f"(gdb) {cmd}\nError: {e}")
            sys.stderr.write(f"Error executing command '{cmd}': {e}\n")
            sys.stderr.flush()

get_crash_context("", "\n\n".join(cmd_outputs) if 'cmd_outputs' in locals() else "")                                                                            
gdb.execute("quit")