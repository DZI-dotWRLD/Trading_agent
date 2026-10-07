"""Run the trading-update skill headless with the Claude Agent SDK (ADR-0001, ADR-0009)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from agent.claude.hooks.sandbox import ALLOWED_TOOLS, VALIDATE_OUTPUT_TOOL, decide
from agent.claude.tools import validate_output

# The weekly build: Sonnet matched Opus on every eval check at about 60% of the cost (evals/results/20261006-174606).
DEFAULT_MODEL = os.environ.get("VSCP_MODEL", "claude-sonnet-5-5")
DEFAULT_BUDGET_USD = float(os.environ.get("VSCP_MAX_BUDGET_USD", "5"))

PROMPT = """Use the trading-update skill.

Your working folder contains run_context.json (inputs and assumptions), the source workbook,
and prior/ with copies of last week's files when they exist. Build the output workbook exactly
as the skill specifies, save it under the output_file name from run_context.json, and write
agent_report.json. Work only inside this folder and run Python with the `python` command
(openpyxl is installed). Do not recalculate the workbook; the orchestrator does that.

After saving the output, call the validate_output tool. It runs VSCP's real validator and says which
checks fail and where. Fix any failures in the formulas and call it again (at most 3 calls).

When you are done, reply with one line: DONE, or FAILED: <reason>."""


@dataclass
class AgentRun:
    ok: bool
    final_text: str = ""
    cost_usd: float | None = None
    turns: int | None = None
    duration_s: float = 0.0
    error: str | None = None
    denials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _options(work_dir: Path, protected: tuple[Path, ...], model: str, max_turns: int, max_budget_usd: float,
             denials: list[str]) -> ClaudeAgentOptions:
    async def guard(input_data, tool_use_id, context):
        d = decide(input_data["tool_name"], input_data.get("tool_input", {}), work_dir, protected)
        if d.allow:
            return {}
        denials.append(f"{input_data['tool_name']}: {d.reason}")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": d.reason}}

    venv_bin = Path(sys.executable).parent  # so `python` is the project's interpreter with openpyxl
    builtin = sorted(ALLOWED_TOOLS - {"Skill", VALIDATE_OUTPUT_TOOL})
    # Snapshot the run context now: the agent can write run_context.json, but the self-check must not trust it.
    context = json.loads((work_dir / "run_context.json").read_text(encoding="utf-8"))
    return ClaudeAgentOptions(
        cwd=str(work_dir),
        model=model,
        tools=builtin,
        allowed_tools=[*builtin, VALIDATE_OUTPUT_TOOL],
        mcp_servers={validate_output.SERVER: validate_output.build_server(work_dir, context)},  # in-process, no network
        disallowed_tools=["WebFetch", "WebSearch", "Agent", "Task"],
        skills=["trading-update"],
        setting_sources=["project"],  # only the workspace's .claude/ (the copied skill), never user settings
        permission_mode="dontAsk",  # anything not pre-approved is denied, never prompted
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard])]},
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        env={"PATH": f"{venv_bin}{os.pathsep}{os.environ.get('PATH', '')}", "PYTHONIOENCODING": "utf-8"},
    )


async def _run(work_dir: Path, protected: tuple[Path, ...], transcript: Path, model: str, max_turns: int,
               max_budget_usd: float) -> AgentRun:
    run = AgentRun(ok=False)
    start = time.monotonic()
    opts = _options(work_dir, protected, model, max_turns, max_budget_usd, run.denials)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    with transcript.open("w", encoding="utf-8") as log:
        async for msg in query(prompt=PROMPT, options=opts):
            log.write(json.dumps(_serialise(msg), default=str) + "\n")
            if isinstance(msg, AssistantMessage):
                texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                if texts:
                    run.final_text = texts[-1].strip()
            elif isinstance(msg, ResultMessage):
                run.cost_usd, run.turns = msg.total_cost_usd, msg.num_turns
                if msg.is_error:
                    run.error = f"{msg.subtype}: {msg.errors or msg.result}"
    run.duration_s = round(time.monotonic() - start, 1)
    run.ok = run.error is None and run.final_text.upper().startswith("DONE")
    if not run.ok and run.error is None:
        run.error = run.final_text or "agent did not report DONE"
    return run


def run_skill(work_dir: Path, *, protected: tuple[Path, ...] = (), transcript: Path | None = None,
              model: str = DEFAULT_MODEL, max_turns: int = 80, max_budget_usd: float = DEFAULT_BUDGET_USD) -> AgentRun:
    """Run the skill in ``work_dir`` (already prepared by ``agent.pipeline.prepare_workspace``)."""
    transcript = transcript or work_dir / "transcript.jsonl"
    try:
        return asyncio.run(_run(work_dir, protected, transcript, model, max_turns, max_budget_usd))
    except Exception as e:  # SDK/CLI failures become a failed run, never a crash of the poller
        return AgentRun(ok=False, error=f"{type(e).__name__}: {e}")


def _serialise(msg) -> dict:
    out = {"type": type(msg).__name__}
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        blocks = []
        for b in content:
            if isinstance(b, TextBlock):
                blocks.append({"text": b.text})
            elif isinstance(b, ToolUseBlock):
                blocks.append({"tool": b.name, "input": b.input})
            else:
                blocks.append({"block": type(b).__name__, "repr": str(b)[:2000]})
        out["content"] = blocks
    for attr in ("subtype", "total_cost_usd", "num_turns", "is_error", "result", "duration_ms"):
        if hasattr(msg, attr):
            out[attr] = getattr(msg, attr)
    return out
