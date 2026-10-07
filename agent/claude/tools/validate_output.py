"""The agent's ``validate_output`` tool: run VSCP's real validator before replying DONE (ADR-0019).

An in-process SDK tool, so a plain Python function in this process with no server or network.
Claude calls it after saving its output, gets back which checks fail and where, fixes the
formulas, and checks again, all with its full context, instead of failing and starting a
blind retry.

Safety:
- The tool takes **no arguments**. It always validates this run's ``output_file`` against this
  run's source, using the run context snapshotted **before** the agent started (the agent could
  edit run_context.json in its workspace, so the file is never re-read).
- It reports hints only, never expected values (``validate.retry_feedback``, ADR-0018).
- It is advisory. The pipeline still validates the final file itself, and that decides.
- It is capped at ``MAX_CALLS`` per run, since each call recalculates the workbook (about a minute).
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

SERVER = "vscp"
TOOL = "validate_output"
TOOL_NAME = f"mcp__{SERVER}__{TOOL}"  # how the SDK names it to Claude and to the PreToolUse hook
MAX_CALLS = 3


def check_output(work_dir: Path, context: dict) -> str:
    """Validate the agent's current output; return the text the agent sees."""
    from agent.checks.validate import retry_feedback, validate

    out = work_dir / context["output_file"]
    if not out.exists():
        return f"No output yet: save {context['output_file']} in the working folder first, then call {TOOL} again."
    scratch = Path(tempfile.mkdtemp(prefix="vscp-selfcheck-"))  # outside the workspace: nothing for the agent to edit
    try:
        report = validate(out, work_dir / context["source_file"], context, keep_dir=scratch)
    except Exception as e:
        return f"The validator could not check the file ({type(e).__name__}: {e}). Make sure it is a valid .xlsx."
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    errors = [c for c in report.checks if c.severity == "error"]
    if report.passed:
        return f"PASS: all {len(errors)} checks pass. You can finish (agent_report.json, then reply DONE)."
    hints = retry_feedback(report)
    return (f"FAIL: {len(hints)} of {len(errors)} checks fail. Expected values are not shown on purpose; "
            "fix the cause in the formulas (never type numbers), save, and call validate_output again.\n- "
            + "\n- ".join(hints))


def build_server(work_dir: Path, context: dict):
    """The SDK MCP server config holding the tool, bound to this run's workspace and context."""
    return create_sdk_mcp_server(SERVER, tools=[make_tool(work_dir, context)])


def make_tool(work_dir: Path, context: dict):
    calls = {"n": 0}

    @tool(TOOL, "Run VSCP's validator on your saved output file (output_file in run_context.json). It "
          "recalculates the workbook and checks every label, formula and number against the source; takes "
          "about a minute. Returns PASS, or which checks fail and where (never the expected values). "
          f"Call it after saving, fix any failures, and call again. At most {MAX_CALLS} calls per run.", {})
    async def validate_output(args):
        calls["n"] += 1
        if calls["n"] > MAX_CALLS:
            text = (f"Limit of {MAX_CALLS} checks reached. Finish: write agent_report.json listing any checks "
                    "you could not fix under warnings, then reply DONE. The final file is validated anyway.")
        else:
            text = await asyncio.to_thread(check_output, work_dir, dict(context))
        return {"content": [{"type": "text", "text": text}]}

    return validate_output
