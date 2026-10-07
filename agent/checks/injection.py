"""Find text in a company's workbook that is written to an AI rather than to a reader (prompt injection).

A safety net for the reviewer, not a defence: the agent treats workbook text as data (SKILL.md), its
sandbox has no network, and nothing is published without a person's approval. This only makes sure the
reviewer hears about a planted instruction even when the agent never read that cell.

Fast path: Excel stores every text cell once in xl/sharedStrings.xml (other writers put the text inline
in the sheet), so the patterns run over those strings and the cell comments. The sheets are opened
(read-only) only to name the cells of a match.
"""
from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import openpyxl

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_AI = r"(?:ai|a\.i\.|llm|gpt|chatgpt|claude|assistant|agent|language model|model|bot)"
PATTERNS = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in (
    r"\b(?:ignore|disregard|forget|override)\b.{0,40}\b(?:instructions?|prompts?|rules|guidelines|above|previous)\b",
    rf"\b(?:note|message|instructions?|attention|hey|dear)\s+(?:to|for)?\s*(?:the\s+|any\s+|all\s+)?{_AI}s?\b",
    rf"\byou\s+are\s+(?:an?\s+|the\s+)?{_AI}\b",
    r"\bsystem\s+prompt\b",
    r"\b(?:skip|disable|bypass|turn\s+off)\b.{0,20}\b(?:validation|checks?|review|approval)\b",
    r"\b(?:e-?mail|send|forward|upload|post)\b.{0,30}\b(?:this|the)\s+(?:file|workbook|data|report|spreadsheet)\s+to\b",
    r"\b(?:set|change|replace)\s+(?:every|all)\s+(?:numbers?|values?|figures?|cells?)\b",
    r"\bdo\s+not\s+(?:tell|mention|report|flag|show)\b",
)]


@dataclass
class Finding:
    where: str  # "Summary!C70", or "a cell comment"
    text: str


def _plain(text: str) -> str:
    """Inline strings arrive as raw XML (<t>...</t>, entities); compare on the text alone."""
    if "<" in text or "&" in text:
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return " ".join(text.split())


def _flagged(text: str) -> bool:
    return any(p.search(text) for p in PATTERNS)


def _texts(root, tag: str) -> list[str]:
    return ["".join(t.text or "" for t in el.iter(f"{NS}t")) for el in root.iter(f"{NS}{tag}")]


def _strings(z: zipfile.ZipFile) -> tuple[list[str], list[str]]:
    """(cell texts: the shared table plus any inline strings, comment texts)"""
    cells, comments = [], []
    for name in z.namelist():
        if name == "xl/sharedStrings.xml":
            cells += _texts(ET.fromstring(z.read(name)), "si")
        elif re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
            raw = z.read(name)
            if b"<is>" in raw:  # inline strings (some writers, e.g. openpyxl, use them instead of the shared table)
                cells += [m.decode("utf-8", "replace") for m in re.findall(rb"<is>(.*?)</is>", raw, re.DOTALL)]
        elif re.fullmatch(r"xl/(?:comments/)?comments?\d*\.xml", name):
            comments += _texts(ET.fromstring(z.read(name)), "comment")
    return cells, comments


def find_instructions(path: Path, limit: int = 10) -> list[Finding]:
    try:
        with zipfile.ZipFile(path) as z:
            cells, comments = _strings(z)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError):
        return []
    hits = {_plain(s) for s in cells if _flagged(_plain(s))}
    found = [Finding("a cell comment", c) for c in comments if _flagged(c)]
    if hits:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for c in row:
                        if isinstance(c.value, str) and _plain(c.value) in hits:
                            found.append(Finding(f"{ws.title}!{c.coordinate}", c.value))
        finally:
            wb.close()
    return found[:limit]


def describe(f: Finding, width: int = 90) -> str:
    text = " ".join(f.text.split())
    return f'{f.where}: "{text[:width]}{"…" if len(text) > width else ""}"'
