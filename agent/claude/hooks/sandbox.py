"""Tool-use policy for the headless agent (ADR-0009).

Pure functions, so the policy is unit-tested without calling Claude. The
runner wires ``decide`` into a PreToolUse hook: every tool call is checked
here before it runs.

Defence in depth: the agent only ever sees *copies* (source file, prior-week
files) inside its working folder, and the orchestrator publishes from there.
Python run by the agent is not filesystem-sandboxed on Windows, so the copies
are what actually keeps VSCP's report folder out of reach.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

READ_TOOLS = {"Read", "Glob", "Grep"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
VALIDATE_OUTPUT_TOOL = "mcp__vscp__validate_output"  # agent.claude.tools.validate_output: no arguments, in-process (ADR-0019)
ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS | {"Bash", "Skill", "TodoWrite", VALIDATE_OUTPUT_TOOL}

PYTHON_COMMANDS = {"python", "python3", "py"}
ALLOWED_COMMANDS = PYTHON_COMMANDS | {"ls", "dir", "cat", "head", "tail", "wc", "echo", "mkdir", "pwd",
                                      "cd", "type", "cp", "copy"}
BLOCKED_WORDS = re.compile(
    r"\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|ssh|scp|ftp|nc|netcat|pip|uv|npm|git|"
    r"powershell|pwsh|cmd|start-process|rm|del|rmdir|remove-item|format|shutdown|reg|schtasks|setx)\b",
    re.IGNORECASE)
SAFE_ENV_PREFIX = re.compile(r"^(?:(?:PYTHONIOENCODING|PYTHONUTF8)=\S+\s+)+")  # e.g. PYTHONIOENCODING=utf-8 python x.py
PY_NETWORK = re.compile(r"\b(requests|urllib|http\.client|socket|smtplib|ftplib|httpx|aiohttp)\b")
ABS_PATH = re.compile(
    r"""(?:(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\|(?<![\w.:/])/(?:[a-z]/|Users|home|etc|tmp|var|mnt))[^\s'"|;&<>]*""")


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve(p: str, cwd: Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else cwd / q


def decide(tool: str, tool_input: dict, work_dir: Path, protected: tuple[Path, ...] = ()) -> Decision:
    """Allow or deny one tool call. ``protected`` files may be read but never written."""
    if tool not in ALLOWED_TOOLS:
        return Decision(False, f"tool {tool} is not available in this job")

    if tool in READ_TOOLS | WRITE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path") or "."
        target = _resolve(str(raw), work_dir)
        if not _under(target, work_dir):
            return Decision(False, f"{tool} outside the working folder is not allowed: {raw}")
        if tool in WRITE_TOOLS and any(_under(target, p) and target.resolve() == p.resolve() for p in protected):
            return Decision(False, f"{raw} is read-only (never modify the source or prior-week files)")
        return Decision(True)

    if tool == "Bash":
        return _decide_bash(str(tool_input.get("command", "")), work_dir)
    return Decision(True)


def _decide_bash(command: str, work_dir: Path) -> Decision:
    if not command.strip():
        return Decision(False, "empty command")
    # `python - <<'EOF' ... EOF`: the body is Python code, not shell; only the first line is a command.
    shell_part = command.split("\n", 1)[0] if re.match(r"\s*\S*(python3?|py)(\.exe)?\s+-\s*<<", command) else command
    for segment in _split_unquoted(shell_part):
        seg = SAFE_ENV_PREFIX.sub("", segment.strip())
        if not seg:
            continue
        try:
            first = shlex.split(seg, posix=True)[0]
        except (ValueError, IndexError):
            first = seg.split()[0]
        name = Path(first).name.lower().removesuffix(".exe")
        if name not in ALLOWED_COMMANDS:
            return Decision(False, f"'{first}' is not an allowed command (use python)")
        # Words inside python code (e.g. str.format) are fine; shell-level use is not.
        if name not in PYTHON_COMMANDS and BLOCKED_WORDS.search(seg):
            return Decision(False, f"'{BLOCKED_WORDS.search(seg).group(0)}' is not allowed in this job")
        if name in PYTHON_COMMANDS and re.search(r"\s-m\s+(pip|http\.server|venv|ensurepip)\b", seg):
            return Decision(False, "installing packages or starting servers is not allowed")
    if PY_NETWORK.search(command):
        return Decision(False, "network access from Python is not allowed in this job")
    if re.search(r"(^|[\s'\"=\\/])\.\.([\\/]|$)", command):
        return Decision(False, "'..' paths are not allowed; stay inside the working folder")
    for m in ABS_PATH.finditer(command):
        if not _under(Path(m.group(0)), work_dir):
            return Decision(False, f"path outside the working folder: {m.group(0)}")
    return Decision(True)


def _split_unquoted(command: str) -> list[str]:
    """Split on ; | && || outside quotes, so python -c code with semicolons stays one segment."""
    parts, buf, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == "\\" and i + 1 < len(command):
                buf += [ch, command[i + 1]]
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "&" and ((buf and buf[-1] == ">") or command[i + 1:i + 2] == ">"):
            pass  # redirection (2>&1, &>), not a separator
        elif ch in ";|&":
            parts.append("".join(buf))
            buf = []
            while i + 1 < len(command) and command[i + 1] in "|&":
                i += 1
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts
