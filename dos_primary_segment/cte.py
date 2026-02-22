"""
Load CTE preferred employee IDs from CSV or Excel.
"""
import csv
from pathlib import Path
from typing import Optional, Set


def load_cte_preferred_csv(path: Path) -> Set[str]:
    """Load emp_id column from cte_preferred.csv. Expects column 'emp_id' or 'EmpID' or first numeric column."""
    ids = set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return ids
        # Prefer EmpID / emp_id
        id_col = None
        for name in ("EmpID", "emp_id", "Emp Id", "id"):
            for fn in reader.fieldnames:
                if fn.strip().lower().replace(" ", "") == name.replace(" ", "").lower():
                    id_col = fn
                    break
            if id_col:
                break
        if not id_col and reader.fieldnames:
            # First column that looks like ID (numeric header or last column often EmpID)
            for fn in reader.fieldnames:
                if "id" in fn.lower() or "emp" in fn.lower():
                    id_col = fn
                    break
            if not id_col:
                id_col = reader.fieldnames[-1]
        for row in reader:
            val = row.get(id_col, "").strip() if id_col else ""
            if val and val.isdigit():
                ids.add(val)
    return ids


def load_cte_preferred_xlsx(path: Path, sheet_name: Optional[str] = None) -> Set[str]:
    """Load EmpID (or similar) column from first sheet of Excel."""
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl required for Excel. pip install openpyxl")
    ids = set()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    if sheet_name:
        ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        wb.close()
        return ids
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    id_col_idx = None
    for name in ("EmpID", "emp_id", "Emp Id", "id"):
        for i, h in enumerate(header):
            if h and name.lower() in h.lower():
                id_col_idx = i
                break
        if id_col_idx is not None:
            break
    if id_col_idx is None and len(header) >= 3:
        id_col_idx = 2  # Common: Last Name, First Name, EmpID
    for row in rows[1:]:
        if row and id_col_idx is not None and id_col_idx < len(row):
            val = row[id_col_idx]
            if val is not None:
                s = str(val).strip()
                if s.isdigit():
                    ids.add(s)
    wb.close()
    return ids


def load_cte_preferred(path: Path) -> Set[str]:
    """Load from .csv or .xlsx."""
    path = Path(path)
    if not path.exists():
        return set()
    suf = path.suffix.lower()
    if suf == ".csv":
        return load_cte_preferred_csv(path)
    if suf in (".xlsx", ".xls"):
        return load_cte_preferred_xlsx(path)
    return set()
