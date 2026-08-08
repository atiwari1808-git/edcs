from __future__ import annotations

from pathlib import Path

from edcs.content_validator.base import ExtractionResult, register
from edcs.content_validator.corruption import is_encrypted_office

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


@register(".xlsx", ".xlsm", ".xltx")
def extract_xlsx(path: Path) -> ExtractionResult:
    res = ExtractionResult()
    if is_encrypted_office(path):
        res.protected = True
        return res
    if openpyxl is None:
        res.error = "openpyxl not installed"
        return res
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        cells, sample = 0, []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if v is not None and str(v).strip():
                        cells += 1
                        if len(sample) < 200:
                            sample.append(str(v))
        wb.close()
        res.cell_count = cells
        res.text = " ".join(sample)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res
