"""
Four outputs: included (human-readable), excluded ledger CSV, run summary, worklog CSV.
"""
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from .packets import Packet
from .segments import (
    Segment,
    compute_segments,
    compute_alt_synthetic_segment,
    ot_pay_type,
    _alt_pay_type_from_notes,
    _lpi_pay_type_from_notes,
    LPI_TREATMENT_UNKNOWN,
)


@dataclass
class IncludedResult:
    """One included packet with computed segments for human-readable output."""
    packet: Packet
    segments: List[Segment]
    annotation: Optional[str]
    ot_pay_type: str
    lpi_minutes: int
    lpi_pay_type: str
    total_worked_str: str


def _total_worked_display(start_min: int, end_min: int) -> str:
    from . import time_utils
    total = time_utils.total_minutes(start_min, end_min)
    h, m = divmod(total, 60)
    return f"{h}:{m:02d}"


def build_included_results(
    included_packets: List[Packet],
    cte_preferred_ids: Set[str],
) -> List[IncludedResult]:
    """Compute segments and metadata for each included packet."""
    from . import time_utils
    results = []
    for p in included_packets:
        if getattr(p, "is_alt_synthetic", False):
            pay_type = _alt_pay_type_from_notes(p.notes_text, p.emp_id, cte_preferred_ids)
            segs = compute_alt_synthetic_segment(
                p.actual_start_min,
                p.actual_end_min,
                pay_type,
            )
            results.append(IncludedResult(
                packet=p,
                segments=segs,
                annotation="Alt driver (day off) — entire shift as OT/CTE",
                ot_pay_type=pay_type,
                lpi_minutes=0,
                lpi_pay_type=LPI_TREATMENT_UNKNOWN,
                total_worked_str=_total_worked_display(p.actual_start_min, p.actual_end_min),
            ))
            continue
        ot_type = ot_pay_type(p.emp_id, cte_preferred_ids)
        lpi_min = time_utils.lpi_minutes_computed(p.actual_end_min, p.scheduled_end_min)
        lpi_pt = _lpi_pay_type_from_notes(p.notes_text)
        segs, ann = compute_segments(
            p.actual_start_min,
            p.actual_end_min,
            p.scheduled_end_min,
            ot_type,
            p.notes_text,
        )
        total_str = _total_worked_display(p.actual_start_min, p.actual_end_min)
        results.append(IncludedResult(
            packet=p,
            segments=segs,
            annotation=ann,
            ot_pay_type=ot_type,
            lpi_minutes=lpi_min,
            lpi_pay_type=lpi_pt,
            total_worked_str=total_str,
        ))
    return results


def format_included_output(results: List[IncludedResult]) -> str:
    """Human-readable output for operator to enter into TimeClock."""
    lines = []
    for r in results:
        p = r.packet
        lines.append(f"EMPLOYEE: {p.employee_name} ({p.emp_id})")
        # Scheduled run = source of truth from Shift Time column; LPI = actual_end vs scheduled_end
        if p.scheduled_run_str:
            lines.append(f"Scheduled run (shift time): {p.scheduled_run_str}")
        lines.append(f"Scheduled end: {p.scheduled_end_time}   Actual end: {p.actual_end_time}")
        lines.append(f"Shift: {p.actual_start_time}–{p.actual_end_time} ({r.total_worked_str})")
        lines.append(f"Std OT: {'CTE Preferred' if r.ot_pay_type == 'CTE' else 'OT'}")
        if r.lpi_minutes > 0:
            if r.lpi_pay_type == LPI_TREATMENT_UNKNOWN:
                lines.append("LPI: (from note)")
            else:
                lines.append(f"LPI: {r.lpi_pay_type} (from note)")
        lines.append("")
        lines.append("SEGMENTS:")
        for seg in r.segments:
            code_str = f" ({seg.code})" if seg.code else ""
            lines.append(f"  {seg.label}{code_str}  {seg.start} → {seg.end}")
        if r.annotation:
            lines.append(f"  ({r.annotation})")
        lines.append("")
    if results:
        lines.append(f"Total included: {len(results)} employees")
    return "\n".join(lines).rstrip()


def write_excluded_ledger_csv(path: Path, excluded: List[Packet]) -> None:
    """Excluded ledger CSV: emp_id, employee_name, work_date, shift_start, shift_end, exclusion_tags, notes_text, primary_condition_text, status."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "emp_id", "employee_name", "work_date", "shift_start", "shift_end",
            "exclusion_tags", "notes_text", "primary_condition_text", "status",
        ])
        for p in excluded:
            tags_str = ";".join(p.exclusion_tags)
            w.writerow([
                p.emp_id, p.employee_name, p.work_date,
                p.actual_start_time, p.actual_end_time,
                tags_str, p.notes_text, p.primary_condition_text, "pending",
            ])


def format_run_summary(
    detected: int,
    included: int,
    excluded: int,
    stopped_at_row: int,
) -> str:
    """Run summary text."""
    return (
        f"Detected employees: {detected}\n"
        f"Included: {included}\n"
        f"Excluded: {excluded}\n"
        f"Stopped at TRANSIT SUPERVISOR row: {stopped_at_row}"
    )


def append_worklog(path: Path, emp_id: str, date: str, shape: str, status: str = "ok") -> None:
    """Append one row to worklog CSV. shape: A, B, or C."""
    import datetime
    timestamp = datetime.datetime.now().isoformat()
    file_exists = path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["emp_id", "date", "shape", "status", "timestamp"])
        w.writerow([emp_id, date, shape, status, timestamp])


def _shape_from_segments(segments: List[Segment]) -> str:
    labels = [s.label for s in segments]
    if labels == ["REG"] or labels == ["REG", "GUARANTEE"]:
        return "A"
    if len(segments) == 2:
        return "B"
    return "C"
