"""
Orchestrate: load DOS, build packets, split included/excluded, compute segments, write outputs.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from . import time_utils
from .parser import load_dos
from .packets import build_packets, partition_packets, build_alt_synthetic_packets, Packet
from .cte import load_cte_preferred
from .outputs import (
    build_included_results,
    format_included_output,
    format_run_summary,
    write_excluded_ledger_csv,
    append_worklog,
    _shape_from_segments,
)


@dataclass
class RunResult:
    included_output_text: str
    excluded_ledger_path: Optional[Path]
    summary_text: str
    detected: int
    included_count: int
    excluded_count: int
    stopped_at_row: int


def _work_date_from_filename(path: Path) -> Optional[str]:
    """Try to get work_date from filename like 2.12.26_Final.pdf -> 02/12/2026."""
    stem = path.stem
    # e.g. 2.12.26_Final or 2.12.26
    parts = stem.replace("_", " ").split()
    if not parts:
        return None
    first = parts[0]
    if "." in first:
        nums = first.split(".")
        if len(nums) >= 3:
            m, d, y = nums[0], nums[1], nums[2]
            if len(y) == 2:
                y = "20" + y
            try:
                return f"{int(m):02d}/{int(d):02d}/{y}"
            except ValueError:
                pass
    return None


def run(
    dos_path: Path,
    cte_path: Optional[Path] = None,
    work_date_override: Optional[str] = None,
    out_dir: Optional[Path] = None,
    worklog_path: Optional[Path] = None,
) -> RunResult:
    """
    Load DOS, build packets, compute segments. Write excluded ledger and worklog to out_dir if set.
    Returns RunResult with included text and summary.
    """
    raw_rows, stopped_at_1based, work_date_from_doc = load_dos(dos_path)
    work_date = work_date_override or work_date_from_doc or _work_date_from_filename(dos_path) or ""

    if not work_date and raw_rows:
        work_date = ""

    packets = build_packets(raw_rows, work_date, stopped_at_1based)
    included_list, excluded_list = partition_packets(packets)

    cte_ids: Set[str] = set()
    if cte_path and cte_path.exists():
        cte_ids = load_cte_preferred(cte_path)
    # Excel "in" sheet: try loading with sheet "in" for Config_Cte.xlsx
    if cte_path and cte_path.suffix.lower() == ".xlsx" and not cte_ids:
        from .cte import load_cte_preferred_xlsx
        try:
            cte_ids = load_cte_preferred_xlsx(cte_path, sheet_name="in")
        except Exception:
            cte_ids = load_cte_preferred(cte_path)

    alt_synthetic = build_alt_synthetic_packets(packets, cte_ids)
    included_list = included_list + alt_synthetic

    included_results = build_included_results(included_list, cte_ids)
    included_output_text = format_included_output(included_results)
    summary_text = format_run_summary(
        detected=len(packets),
        included=len(included_list),
        excluded=len(excluded_list),
        stopped_at_row=stopped_at_1based,
    )
    # Note: included_count includes alt synthetic

    out_dir = Path(out_dir) if out_dir else None
    excluded_ledger_path = None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        excluded_ledger_path = out_dir / "excluded_ledger.csv"
        write_excluded_ledger_csv(excluded_ledger_path, excluded_list)

    worklog_file = worklog_path or (out_dir / "worklog.csv" if out_dir else None)
    if worklog_file:
        for r in included_results:
            shape = _shape_from_segments(r.segments)
            append_worklog(worklog_file, r.packet.emp_id, r.packet.work_date, shape, "ok")

    return RunResult(
        included_output_text=included_output_text,
        excluded_ledger_path=excluded_ledger_path,
        summary_text=summary_text,
        detected=len(packets),
        included_count=len(included_list),  # includes alt synthetic
        excluded_count=len(excluded_list),
        stopped_at_row=stopped_at_1based,
    )
