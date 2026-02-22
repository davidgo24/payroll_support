"""
Segment shapes A/B/C and pay type rules. LPI treatment from notes.
"""
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from . import time_utils

# Pay types
CTE = "CTE"
OT = "OT"
LPI_TREATMENT_UNKNOWN = "LPI_TREATMENT_UNKNOWN"

# TimeClock segment codes
CODE_REG = "1020"
CODE_OT = "1013"
CODE_CTE = "3002"
CODE_GUARANTEE = "1000"


@dataclass
class Segment:
    """One time segment (REG, OT, CTE, LPI, or GUARANTEE) with TimeClock code."""
    label: str   # "REG", "OT", "CTE", "LPI", "GUARANTEE"
    start: str   # HH:MM
    end: str     # HH:MM
    code: str = ""  # e.g. 1020, 1013, 3002, 1000


def _lpi_pay_type_from_notes(notes: str) -> str:
    """Notes indicate LPI treatment, not duration. LPI+CTE -> CTE, LPI+OT -> OT, else UNKNOWN."""
    n = (notes or "").upper()
    if "LPI" not in n:
        return LPI_TREATMENT_UNKNOWN
    if "CTE" in n:
        return CTE
    if "OT" in n:
        return OT
    return LPI_TREATMENT_UNKNOWN


def compute_segments(
    actual_start_min: int,
    actual_end_min: int,
    scheduled_end_min: int,
    ot_pay_type: str,
    notes_text: str,
) -> Tuple[List[Segment], Optional[str]]:
    """
    Compute segment list and optional annotation ("OT includes LPI").
    Uses minutes; returns segments with HH:MM strings.
    """
    total = time_utils.total_minutes(actual_start_min, actual_end_min)
    t8 = time_utils.t8_minutes(actual_start_min)
    lpi_min = time_utils.lpi_minutes_computed(actual_end_min, scheduled_end_min)
    lpi_pay_type = _lpi_pay_type_from_notes(notes_text)

    annotation = None
    segments = []

    # Shape A: total <= 8 hours (480 min)
    if total <= 480:
        segments.append(Segment("REG", time_utils.format_time(actual_start_min), time_utils.format_time(actual_end_min), CODE_REG))
        # Sub-8: add guarantee segment from actual_end to (start + 8 hrs) so they get 8 hrs
        if total < 480:
            guarantee_end_min = time_utils.t8_minutes(actual_start_min)
            segments.append(Segment("GUARANTEE", time_utils.format_time(actual_end_min), time_utils.format_time(guarantee_end_min), CODE_GUARANTEE))
        return segments, annotation

    # Shape B or C: > 8 hours
    # REG: start -> t8
    segments.append(Segment("REG", time_utils.format_time(actual_start_min), time_utils.format_time(t8), CODE_REG))

    ot_code = CODE_CTE if ot_pay_type == CTE else CODE_OT
    lpi_code = CODE_CTE if lpi_pay_type == CTE else CODE_OT

    if lpi_min <= 0 or lpi_pay_type == LPI_TREATMENT_UNKNOWN:
        # Shape B (default): one OT/CTE segment; if LPI exists but type unknown, still one segment, annotate
        segments.append(Segment(ot_pay_type, time_utils.format_time(t8), time_utils.format_time(actual_end_min), ot_code))
        if lpi_min > 0:
            annotation = "OT includes LPI"
        return segments, annotation

    if lpi_pay_type == ot_pay_type:
        # LPI same as OT type: do not split (Shape B), annotate
        segments.append(Segment(ot_pay_type, time_utils.format_time(t8), time_utils.format_time(actual_end_min), ot_code))
        annotation = "OT includes LPI"
        return segments, annotation

    # Shape C: lpi_min > 0 and lpi_pay_type != ot_pay_type
    # REG: start -> t8
    # OT remainder: t8 -> scheduled_end (ot_pay_type) — only if scheduled_end > t8
    # LPI: max(t8, scheduled_end) -> actual_end (lpi_pay_type)
    if scheduled_end_min > t8:
        segments.append(Segment(ot_pay_type, time_utils.format_time(t8), time_utils.format_time(scheduled_end_min), ot_code))
        segments.append(Segment(lpi_pay_type, time_utils.format_time(scheduled_end_min), time_utils.format_time(actual_end_min), lpi_code))
    else:
        # No OT remainder (scheduled end before t8); all overtime is LPI
        segments.append(Segment(lpi_pay_type, time_utils.format_time(t8), time_utils.format_time(actual_end_min), lpi_code))
    return segments, annotation


def ot_pay_type(emp_id: str, cte_preferred_ids: Set[str]) -> str:
    """CTE if emp_id in cte_preferred else OT."""
    return CTE if emp_id in cte_preferred_ids else OT


def _alt_pay_type_from_notes(notes: str, alt_emp_id: str, cte_preferred_ids: Set[str]) -> str:
    """For alt-only drivers: pay type from note (paid as cte/ot) or fallback to cte_preferred."""
    n = (notes or "").lower()
    if "paid as cte" in n:
        return CTE
    if "paid as ot" in n:
        return OT
    return ot_pay_type(alt_emp_id, cte_preferred_ids)


def compute_alt_synthetic_segment(
    actual_start_min: int,
    actual_end_min: int,
    pay_type: str,
) -> List[Segment]:
    """
    Single segment for alt-only driver (subbing in for primary): all hours OT or CTE.
    No REG — they're on their day off, entire shift is overtime.
    """
    code = CODE_CTE if pay_type == CTE else CODE_OT
    seg = Segment(
        pay_type,
        time_utils.format_time(actual_start_min),
        time_utils.format_time(actual_end_min),
        code,
    )
    return [seg]
