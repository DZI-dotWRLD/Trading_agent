"""The discovery agent's ``check_source_map`` tool: run ``check_map`` on its map before replying DONE (ADR-0024).

Same pattern as ``validate_output``: an in-process SDK tool with **no arguments**. It always checks this
run's ``source_map.json`` against this run's source copy (both bound when the run starts), and it is
advisory: ``agent.claude.discover`` re-runs ``check_map`` on the final map itself and that decides.
Capped at ``MAX_CALLS`` per run. The reply is factual (which check, which rows or cells disagree).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

SERVER = "vscp"
TOOL = "check_source_map"
TOOL_NAME = f"mcp__{SERVER}__{TOOL}"
MAP_FILE = "source_map.json"
MAX_CALLS = 3


def check_file(work_dir: Path, source_name: str) -> str:
    """Check the agent's current source_map.json; return the text the agent sees."""
    import openpyxl

    from agent.workbook.map_check import check_map, failures

    path = work_dir / MAP_FILE
    if not path.exists():
        return f"No map yet: write {MAP_FILE} in the working folder first, then call {TOOL} again."
    try:
        source_map = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return f"FAIL: {MAP_FILE} is not valid JSON ({e}). Fix it and call {TOOL} again."
    if not isinstance(source_map, dict):
        return f"FAIL: {MAP_FILE} must hold one JSON object."
    try:
        wb = openpyxl.load_workbook(work_dir / source_name, data_only=True)
        checks = check_map(wb, source_map)
    except Exception as e:  # a malformed map (wrong types) must come back as a fixable failure
        return f"FAIL: the map could not be checked ({type(e).__name__}: {e}). Check its structure against the skill."
    errors = failures(checks, "error")
    warnings = failures(checks, "warning")
    warn = "".join(f"\n- warning: {c.name}: {c.detail}" for c in warnings)
    if not errors:
        n = sum(1 for c in checks if c.severity == "error")
        return f"PASS: all {n} checks pass.{warn}\nYou can finish (reply DONE)."
    return (f"FAIL: {len(errors)} checks fail. Re-read the cells named, fix {MAP_FILE} (never the workbook) and call "
            f"{TOOL} again.\n- " + "\n- ".join(f"{c.name}: {c.detail}" for c in errors) + warn)


def build_server(work_dir: Path, source_name: str):
    return create_sdk_mcp_server(SERVER, tools=[make_tool(work_dir, source_name)])


def make_tool(work_dir: Path, source_name: str):
    calls = {"n": 0}

    @tool(TOOL, f"Check your {MAP_FILE} against the workbook: every input resolves, value types fit, and the "
          "accounting identities hold (gp = sales - purchase, segments add up, net debt = debt - cash, ...). "
          f"Returns PASS, or which checks fail and where. At most {MAX_CALLS} calls per run.", {})
    async def check_source_map(args):
        calls["n"] += 1
        if calls["n"] > MAX_CALLS:
            text = (f"Limit of {MAX_CALLS} checks reached. Finish: reply DONE if you believe the map is right, "
                    "or FAILED: <reason>. The map is checked again by code anyway.")
        else:
            text = await asyncio.to_thread(check_file, work_dir, source_name)
        return {"content": [{"type": "text", "text": text}]}

    return check_source_map
