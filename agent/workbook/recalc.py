"""Recalculate a workbook in place so openpyxl can read formula results.

openpyxl writes formula text without cached values. Engines, in order of
preference (ADR-0006): headless LibreOffice, then Excel via COM (Windows).
Override with ``VSCP_RECALC_ENGINE=libreoffice|excel``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

LIBREOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]

_MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub RecalculateAndSave()
  ThisComponent.calculateAll()
  ThisComponent.store()
  ThisComponent.close(True)
End Sub
</script:module>"""


class RecalcError(Exception):
    pass


def find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    return next((p for p in LIBREOFFICE_CANDIDATES if Path(p).exists()), None)


def _excel_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Excel.Application"))
        return True
    except OSError:
        return False


def available_engine() -> str | None:
    forced = os.environ.get("VSCP_RECALC_ENGINE")
    if forced:
        return forced
    if find_soffice():
        return "libreoffice"
    if _excel_available():
        return "excel"
    return None


def recalc(path: str | Path, engine: str | None = None, timeout: int = 180) -> str:
    """Recalculate ``path`` in place. Returns the engine used."""
    path = Path(path).resolve()
    engine = engine or available_engine()
    if engine == "libreoffice":
        _recalc_libreoffice(path, timeout)
    elif engine == "excel":
        _recalc_excel(path)
    else:
        raise RecalcError("No recalculation engine: install LibreOffice (or Microsoft Excel on Windows).")
    return engine


def _recalc_libreoffice(path: Path, timeout: int) -> None:
    soffice = find_soffice()
    if not soffice:
        raise RecalcError("LibreOffice (soffice) not found")
    with tempfile.TemporaryDirectory(prefix="vscp-lo-") as profile:
        url = Path(profile).as_uri()
        subprocess.run([soffice, "--headless", "--terminate_after_init", f"-env:UserInstallation={url}"],
                       capture_output=True, timeout=timeout)
        macro_dir = Path(profile) / "user" / "basic" / "Standard"
        if not macro_dir.exists():
            raise RecalcError("LibreOffice did not create a usable profile")
        (macro_dir / "Module1.xba").write_text(_MACRO, encoding="utf-8")
        before = path.stat().st_mtime_ns
        proc = subprocess.run(
            [soffice, "--headless", "--norestore", f"-env:UserInstallation={url}",
             "vnd.sun.star.script:Standard.Module1.RecalculateAndSave?language=Basic&location=application", str(path)],
            capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RecalcError(f"LibreOffice failed: {proc.stderr.strip() or proc.returncode}")
        if path.stat().st_mtime_ns == before:
            raise RecalcError("LibreOffice exited without rewriting the file (another instance running?)")


def _recalc_excel(path: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")  # private instance, never the user's
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AskToUpdateLinks = False
        excel.EnableEvents = False
        excel.AutomationSecurity = 3  # msoAutomationSecurityForceDisable: never run macros (default for COM is "enable")
        wb = excel.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=False)
        try:
            excel.CalculateFullRebuild()
            deadline = time.monotonic() + 300
            while excel.CalculationState != 0 and time.monotonic() < deadline:  # 0 = xlDone
                time.sleep(0.2)
            wb.Save()
        finally:
            wb.Close(SaveChanges=False)
    except Exception as e:  # COM errors are opaque; surface them as one type
        raise RecalcError(f"Excel recalculation failed: {e}") from e
    finally:
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()
