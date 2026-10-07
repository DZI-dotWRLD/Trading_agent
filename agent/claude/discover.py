"""Claude discovers an unfamiliar workbook layout and proposes a source map (ADR-0024).

``run_discovery`` copies the company's workbook into a scratch workspace (Claude never sees the original
path), runs the ``source-map`` skill headless with the same sandbox policy as the build runner, then
**re-runs ``check_map`` itself** on the map Claude wrote. Claude's own ``check_source_map`` tool calls are
advisory and never trusted. A map that passes is still only a proposal: the reviewer approves it with the
first report built from it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.claude.hooks.sandbox import ALLOWED_TOOLS, VALIDATE_OUTPUT_TOOL, decide
from agent.claude.runner import AgentRun, _serialise
from agent.claude.tools import check_source_map
from agent.workbook.map_check import MapCheck, check_map, failures, passed

# Learning a new layout is rare (once per company) and the step that needs the most judgement: Opus.
DISCOVERY_MODEL = os.environ.get("VSCP_DISCOVERY_MODEL", "claude-opus-5-5")

ROOT = Path(__file__).resolve().parents[2]
SKILL = "source-map"
SKILL_DIR = ROOT / ".claude" / "skills" / SKILL
MAP_FILE = check_source_map.MAP_FILE

PROMPT = """Use the source-map skill.

Your working folder contains {source}, one weekly trading-update workbook from the portfolio company
{company}. Its layout may differ from the reference template. Find where each input is and write
source_map.json in the working folder, with evidence, exactly as the skill specifies. Work only inside this
folder, run Python with the `python` command (openpyxl is installed) and never modify the workbook.

After writing the map, call the check_source_map tool. Fix any failures in the map and call it again (at
most 3 calls).

When you are done, reply with one line: DONE, or FAILED: <what is missing>."""


@dataclass
class DiscoveryResult:
    ok: bool                                  # DONE, and every error-severity check passed on code's own re-check
    source_map: dict | None = None            # the map Claude wrote, when it parsed (use it only if ok)
    checks: list[MapCheck] = field(default_factory=list)
    final_text: str = ""
    cost_usd: float | None = None
    error: str | None = None
    duration_s: float = 0.0
    turns: int | None = None
    denials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "source_map": self.source_map, "checks": [c.to_dict() for c in self.checks],
                "final_text": self.final_text, "cost_usd": self.cost_usd, "error": self.error,
                "duration_s": self.duration_s, "turns": self.turns, "denials": self.denials}


# (work_dir, source_name, protected, transcript, company_name, model, max_turns, max_budget_usd) -> AgentRun
AgentFn = Callable[..., AgentRun]


def prepare_workspace(source: Path, work_dir: Path) -> tuple[Path, tuple[Path, ...]]:
    """Copy the workbook and the skill into ``work_dir``. Returns (source copy, protected files)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / MAP_FILE).unlink(missing_ok=True)  # never pick up a stale map
    src_copy = work_dir / source.name
    shutil.copy2(source, src_copy)
    shutil.copytree(SKILL_DIR, work_dir / ".claude" / "skills" / SKILL, dirs_exist_ok=True)
    return src_copy, (src_copy,)


def _options(work_dir: Path, source_name: str, protected: tuple[Path, ...], model: str, max_turns: int,
             max_budget_usd: float, denials: list[str]):
    """Mirrors ``runner._options``: same sandbox hook, own tool and skill instead of validate_output."""
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    async def guard(input_data, tool_use_id, context):
        name = input_data["tool_name"]
        if name == check_source_map.TOOL_NAME:
            return {}
        d = decide(name, input_data.get("tool_input", {}), work_dir, protected)
        if name == VALIDATE_OUTPUT_TOOL:  # the build job's tool has no place here
            d = type(d)(False, "tool not available in this job")
        if d.allow:
            return {}
        denials.append(f"{name}: {d.reason}")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": d.reason}}

    venv_bin = Path(sys.executable).parent
    builtin = sorted(ALLOWED_TOOLS - {"Skill", VALIDATE_OUTPUT_TOOL})
    return ClaudeAgentOptions(
        cwd=str(work_dir),
        model=model,
        tools=builtin,
        allowed_tools=[*builtin, check_source_map.TOOL_NAME],
        mcp_servers={check_source_map.SERVER: check_source_map.build_server(work_dir, source_name)},
        disallowed_tools=["WebFetch", "WebSearch", "Agent", "Task"],
        skills=[SKILL],
        setting_sources=["project"],
        permission_mode="dontAsk",
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard])]},
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        env={"PATH": f"{venv_bin}{os.pathsep}{os.environ.get('PATH', '')}", "PYTHONIOENCODING": "utf-8"},
    )


async def _run(work_dir: Path, source_name: str, protected: tuple[Path, ...], transcript: Path, company_name: str,
               model: str, max_turns: int, max_budget_usd: float) -> AgentRun:
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

    run = AgentRun(ok=False)
    start = time.monotonic()
    opts = _options(work_dir, source_name, protected, model, max_turns, max_budget_usd, run.denials)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(source=source_name, company=company_name)
    with transcript.open("w", encoding="utf-8") as log:
        async for msg in query(prompt=prompt, options=opts):
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
    return run


def run_agent_sdk(work_dir: Path, source_name: str, protected: tuple[Path, ...], transcript: Path, company_name: str,
                  model: str, max_turns: int, max_budget_usd: float) -> AgentRun:
    try:
        return asyncio.run(_run(work_dir, source_name, protected, transcript, company_name, model, max_turns,
                                max_budget_usd))
    except Exception as e:  # SDK/CLI failures become a failed run
        return AgentRun(ok=False, error=f"{type(e).__name__}: {e}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_discovery(source: Path, work_dir: Path, company_name: str, transcript: Path | None = None,
                  model: str = DISCOVERY_MODEL, max_turns: int = 40, max_budget_usd: float = 1.5,
                  run_agent: AgentFn = run_agent_sdk) -> DiscoveryResult:
    """Have Claude propose a source map for ``source``; return it with code's own check results."""
    source, work_dir = Path(source), Path(work_dir)
    src_copy, protected = prepare_workspace(source, work_dir)
    before = _sha256(src_copy)
    start = time.monotonic()
    run = run_agent(work_dir, src_copy.name, protected, transcript or work_dir / "transcript.jsonl", company_name,
                    model, max_turns, max_budget_usd)
    res = DiscoveryResult(ok=False, final_text=run.final_text, cost_usd=run.cost_usd, turns=run.turns,
                          denials=list(run.denials), duration_s=round(time.monotonic() - start, 1))

    if _sha256(src_copy) != before:
        res.error = "the workbook copy was modified during discovery"
        return res
    if run.final_text.strip().upper().startswith("FAILED"):
        res.error = run.final_text.strip()
        return res

    path = work_dir / MAP_FILE
    if not path.exists():
        res.error = run.error or f"no {MAP_FILE} was written"
        return res
    try:
        source_map = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        res.error = f"{MAP_FILE} is not valid JSON: {e}"
        return res
    if not isinstance(source_map, dict):
        res.error = f"{MAP_FILE} is not a JSON object"
        return res
    res.source_map = source_map

    import openpyxl
    try:  # never trust the agent's own tool calls: check again, on the untouched copy
        res.checks = check_map(openpyxl.load_workbook(src_copy, data_only=True), source_map)
    except Exception as e:
        res.error = f"the map could not be checked ({type(e).__name__}: {e})"
        return res
    ev = source_map.get("evidence")
    res.checks.append(MapCheck("evidence given", isinstance(ev, dict) and len(ev) > 0,
                               f"{len(ev) if isinstance(ev, dict) else 0} evidence entries"))

    if not passed(res.checks):
        res.error = "map checks fail: " + "; ".join(f"{c.name}: {c.detail}" for c in failures(res.checks, "error"))
    elif not run.ok:
        res.error = run.error or run.final_text or "agent did not report DONE"
    res.ok = res.error is None
    return res


if __name__ == "__main__":  # python -m agent.claude.discover SOURCE WORK_DIR [COMPANY]
    r = run_discovery(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "the company")
    print(json.dumps({k: v for k, v in r.to_dict().items() if k != "source_map"}, indent=2, default=str))
