"""
Produce JSON-serializable structures for the web API.
Bucket classification for UI filtering.
"""
from typing import Any, Dict, List

from .packets import Packet
from .segments import Segment
from .outputs import IncludedResult, build_included_results, _shape_from_segments

# Bucket names for UI
BUCKET_SIMPLE = "simple"
BUCKET_LPI = "lpi"
BUCKET_ALT = "alt"  # Synthetic row for alt-only driver (day off, subbing for primary)
BUCKET_EXB_SHINE = "exb_shine"  # EXB block + primary condition SHINE — include, generate segments
BUCKET_CONDITION_ALT = "condition_or_alternate"
BUCKET_EXB = "exb"
BUCKET_OTHER = "other"


def _bucket_for_packet(p: Packet) -> str:
    """Classify packet into bucket for filtering."""
    if p.exclusion_tags:
        if any(t == "EXTRABOARD" or t.startswith("EXTRABOARD") for t in p.exclusion_tags):
            return BUCKET_EXB
        if any("ALT_PRESENT" in t or "PRIMARY_CONDITION" in t for t in p.exclusion_tags):
            return BUCKET_CONDITION_ALT
        return BUCKET_OTHER
    return BUCKET_SIMPLE  # included; refined below


def _bucket_for_included(r: IncludedResult) -> str:
    """Refine bucket for included packets: simple vs LPI vs alt vs exb_shine."""
    if getattr(r.packet, "is_alt_synthetic", False):
        return BUCKET_ALT
    block = (getattr(r.packet, "block", "") or "").upper()
    cond = (r.packet.primary_condition_text or "").lower()
    if "EXB" in block and "shine" in cond:
        return BUCKET_EXB_SHINE
    # LPI bucket: computed LPI > 0, OR notes mention LPI (operator flagged it — needs review)
    has_lpi_notes = "lpi" in (r.packet.notes_text or "").lower()
    if has_lpi_notes:
        return BUCKET_LPI
    if r.lpi_minutes > 0 and r.segments and len(r.segments) > 2:
        return BUCKET_LPI  # Shape C - split OT types
    if r.lpi_minutes > 0 and r.annotation:
        return BUCKET_LPI  # LPI present, even if same type
    return BUCKET_SIMPLE


def _segment_to_dict(s: Segment) -> Dict[str, Any]:
    return {"label": s.label, "start": s.start, "end": s.end, "code": s.code or ""}


def _packet_to_dict(p: Packet) -> Dict[str, Any]:
    return {
        "emp_id": p.emp_id,
        "employee_name": p.employee_name,
        "work_date": p.work_date,
        "alternate_emp_id": getattr(p, "alternate_emp_id", "") or "",
        "alternate_name": getattr(p, "alternate_name", "") or "",
        "actual_start_time": p.actual_start_time,
        "actual_end_time": p.actual_end_time,
        "scheduled_end_time": p.scheduled_end_time,
        "scheduled_run_str": p.scheduled_run_str,
        "block": getattr(p, "block", "") or "",
        "notes_text": p.notes_text,
        "alternate_driver_present": p.alternate_driver_present,
        "primary_condition_text": p.primary_condition_text,
        "exclusion_tags": p.exclusion_tags,
        "potential_bleed": getattr(p, "potential_bleed", False),
        "is_alt_synthetic": getattr(p, "is_alt_synthetic", False),
    }


def _should_auto_flag(p: Packet) -> bool:
    """Auto-flag for review: pay-as request (OT/CTE) or possible PDF row bleed."""
    if getattr(p, "potential_bleed", False):
        return True
    notes = (p.notes_text or "").lower()
    return "paid as " in notes  # paid as ot, paid as cte, etc.


def build_api_response(
    included_results: List[IncludedResult],
    excluded_packets: List[Packet],
    summary: Dict[str, int],
    work_date: str,
    cte_ids=None,
) -> Dict[str, Any]:
    """Build JSON-serializable response for the web API."""
    rows = []

    # Included rows
    for r in included_results:
        bucket = _bucket_for_included(r)
        rows.append({
            "type": "included",
            "bucket": bucket,
            "packet": _packet_to_dict(r.packet),
            "segments": [_segment_to_dict(s) for s in r.segments],
            "annotation": r.annotation,
            "ot_pay_type": r.ot_pay_type,
            "cte_preferred": r.ot_pay_type == "CTE",
            "lpi_minutes": r.lpi_minutes,
            "lpi_pay_type": r.lpi_pay_type,
            "total_worked_str": r.total_worked_str,
            "shape": "ALT" if getattr(r.packet, "is_alt_synthetic", False) else _shape_from_segments(r.segments),
            "status": "pending",
            "flagged": _should_auto_flag(r.packet),
        })

    # Excluded rows
    cte_set = cte_ids if cte_ids is not None else set()
    for p in excluded_packets:
        bucket = _bucket_for_packet(p)
        rows.append({
            "type": "excluded",
            "bucket": bucket,
            "packet": _packet_to_dict(p),
            "segments": [],
            "annotation": None,
            "ot_pay_type": "",
            "cte_preferred": str(p.emp_id) in cte_set,
            "lpi_minutes": 0,
            "lpi_pay_type": "",
            "total_worked_str": "",
            "shape": "",
            "status": "pending",
            "flagged": _should_auto_flag(p),
        })

    return {
        "work_date": work_date,
        "summary": summary,
        "rows": rows,
    }
