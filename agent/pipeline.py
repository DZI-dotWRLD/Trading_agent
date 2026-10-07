"""One weekly run: workspace -> agent -> validate -> publish or fail closed (ADR-0007, ADR-0009).

The poller calls ``run_week`` for each recognised source file; the evals call it
too, so both exercise the same code path. ``run_agent`` is injectable so tests
can substitute a deterministic builder for Claude.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from agent.checks.validate import ValidationReport, retry_feedback, validate
from agent.claude.memory.prior import find_prior_report
from agent.claude.runner import AgentRun, run_skill
from agent.workbook.reader import TradingUpdate, WorkbookError
from agent.workbook.style import TEMPLATE, apply_sample_style

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".claude" / "skills" / "trading-update"

# Only presentation defaults. The financing terms (model_start_date, po_advance_rate) are facts about each
# company and must be in its profile: a silent default would build, and pass, with another company's terms.
DEFAULT_ASSUMPTIONS = {
    "opening_loan_balance_eur": None,  # None = carry over from last week's output
    "forward_weeks": 28,
}
REQUIRED_ASSUMPTIONS = ("model_start_date", "po_advance_rate")

AgentFn = Callable[..., AgentRun]


@dataclass
class WeekResult:
    ok: bool
    source: Path
    published: Path | None = None
    validated: Path | None = None  # recalculated, validated output in the run folder (publish copies this)
    context: dict | None = None
    attempts: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def last_validation(self) -> dict | None:
        return self.attempts[-1].get("validation") if self.attempts else None


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def output_name(source: Path) -> str:
    return f"{source.stem}_vClaude.xlsx"


def prepare_workspace(source: Path, reports_dir: Path | None, work_dir: Path, company: str,
                      assumptions: dict | None = None, company_name: str | None = None,
                      previous_attempt: dict | None = None,
                      source_map: dict | None = None) -> tuple[dict, tuple[Path, ...]]:
    """Copy everything the agent may see into ``work_dir``. Returns (run_context, protected files).

    The context carries the company's source map and, resolved against this week's file, the concrete
    location of every input (``source``): the agent builds its formulas on those, and the validator
    recomputes from the same cells (ADR-0024).
    """
    tu = TradingUpdate(source, source_map)
    work_dir.mkdir(parents=True, exist_ok=True)
    src_copy = work_dir / source.name
    shutil.copy2(source, src_copy)
    shutil.copytree(SKILL_DIR, work_dir / ".claude" / "skills" / "trading-update", dirs_exist_ok=True)
    protected = [src_copy]

    prior_dir, prior_layout = None, None
    if reports_dir is not None:
        prior_src = find_prior_report(reports_dir, *tu.iso_week)
        if prior_src is not None:
            prior_dir = work_dir / "prior"
            prior_dir.mkdir(exist_ok=True)
            for f in (prior_src, prior_src.with_name(output_name(prior_src))):
                if f.exists():
                    shutil.copy2(f, prior_dir / f.name)
                    protected.append(prior_dir / f.name)
            try:  # where last week's inputs are, in last week's file (rows move week to week)
                prior_layout = TradingUpdate(prior_src, source_map).layout.to_context()
            except WorkbookError:
                prior_layout = None

    context = {
        "source_file": source.name,
        "output_file": output_name(source),
        "company": company,
        "company_name": company_name or company,  # used inside output labels, e.g. "Net Inceptua Cash Flow"
        "prior_reports_dir": str(prior_dir) if prior_dir else None,
        "assumptions": {**DEFAULT_ASSUMPTIONS, **(assumptions or {})},
        "source_map": tu.map,
        "source": tu.layout.to_context(),
        "prior_source": prior_layout,
    }
    if previous_attempt:  # a retry: say what went wrong last time (never the expected values)
        context["previous_attempt"] = previous_attempt
    (work_dir / "run_context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")
    protected.append(work_dir / "run_context.json")  # the agent reads its inputs; it never edits them
    return context, tuple(protected)


def run_week(source: Path, *, company: str, reports_dir: Path | None, runs_dir: Path, publish_dir: Path | None = None,
             assumptions: dict | None = None, run_agent: AgentFn = run_skill, max_attempts: int = 2,
             agent_kwargs: dict | None = None, company_name: str | None = None,
             style_template: Path | None = None, source_map: dict | None = None) -> WeekResult:
    result = WeekResult(ok=False, source=source)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    feedback: dict | None = None
    for attempt in range(1, max_attempts + 1):
        work = runs_dir / f"{source.stem}-{stamp}-a{attempt}"
        context, protected = prepare_workspace(source, reports_dir, work, company, assumptions, company_name,
                                               previous_attempt=feedback, source_map=source_map)
        inputs = {p: _sha256(p) for p in protected}
        agent = run_agent(work, protected=protected, transcript=work / "transcript.jsonl", **(agent_kwargs or {}))
        record: dict = {"attempt": attempt, "work_dir": str(work), "agent": agent.to_dict()}
        result.attempts.append(record)

        # The sandbox stops the file tools from writing these, but not a script or a copy command. The validator
        # reads the source and prior/ copies, so any change to them fails the attempt (fail closed, ADR-0007).
        changed = [p.relative_to(work).as_posix() for p, h in inputs.items() if not p.exists() or _sha256(p) != h]
        if changed:
            record["error"] = f"the agent changed its read-only inputs: {', '.join(changed)}"
            feedback = {"attempt": attempt, "error": record["error"] + ". Never write to the source, prior/ or "
                                                                       "run_context.json.", "failed_checks": []}
            continue

        out = work / context["output_file"]
        if not out.exists():
            record["error"] = agent.error or "agent produced no output file"
            if agent.final_text.upper().startswith("FAILED"):
                break  # the agent stopped on purpose (e.g. missing input): a retry would stop at the same place
            feedback = {"attempt": attempt, "error": record["error"][:500], "failed_checks": []}
            continue
        try:  # the sample output's look (ADR-0021); cosmetic, so a failure here never fails the run
            apply_sample_style(out, style_template or TEMPLATE)
        except Exception as e:
            record["style_error"] = f"{type(e).__name__}: {e}"[:300]
        try:
            report: ValidationReport = validate(out, work / source.name, context, keep_dir=work / "validated")
        except Exception as e:  # a crash in validation is a failed attempt, not a published file
            record["error"] = f"validation crashed: {type(e).__name__}: {e}"
            feedback = None  # not the agent's fault: retry clean
            continue
        record["validation"] = report.to_dict()
        (work / "validation.json").write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
        if report.passed:
            result.validated, result.context = Path(report.recalculated_path), context
            if publish_dir is not None:
                publish_dir.mkdir(parents=True, exist_ok=True)
                target = publish_dir / context["output_file"]
                if target.exists():  # ADR-0013: never overwrite; revisions arrive as _r2 sources
                    result.error = f"{target.name} already exists in {publish_dir}; not overwritten"
                    return result
                shutil.copy2(report.recalculated_path, target)
                result.published = target
            result.ok = True
            return result
        record["error"] = report.summary()
        feedback = {"attempt": attempt, "error": None, "failed_checks": retry_feedback(report)}
    result.error = result.attempts[-1].get("error") if result.attempts else "no attempts made"
    return result
