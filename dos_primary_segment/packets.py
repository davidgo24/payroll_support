"""
Build Employee-Day Packets from raw rows. Apply inclusion/exclusion rules.
Create synthetic packets for alternate-only drivers (not primary, not EXB).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Set

from . import time_utils
from .parser import RawRow

# Exclusion tags
TAG_ALT_PRESENT = "ALT_PRESENT"
TAG_PRIMARY_CONDITION = "PRIMARY_CONDITION"
TAG_MISSING_TIME = "MISSING_TIME"
TAG_PAST_SENTINEL = "PAST_SENTINEL"
TAG_EXTRABOARD = "EXTRABOARD"  # block is EXB (extraboard); spec non-goal, exclude from auto-process


@dataclass
class Packet:
    """One employee-day packet (normalized fields)."""
    emp_id: str
    employee_name: str
    work_date: str
    actual_start_time: str
    actual_end_time: str
    scheduled_end_time: str  # from Shift Time column (end of range); source of truth for LPI
    scheduled_run_str: str   # full Shift Time column e.g. "03:43-12:22"; original run for comparison
    notes_text: str
    alternate_driver_present: bool
    primary_condition_text: str
    # Computed (set after time validation)
    actual_start_min: Optional[int] = None
    actual_end_min: Optional[int] = None
    scheduled_end_min: Optional[int] = None
    exclusion_tags: List[str] = field(default_factory=list)
    source_row_index: int = 0
    potential_bleed: bool = False  # Notes contain another emp_id — possible PDF row merge
    alternate_emp_id: str = ""   # Alt driver emp_id when alternate_driver_present
    alternate_name: str = ""     # Alt driver name when alternate_driver_present
    is_alt_synthetic: bool = False  # True = synthetic row for alt who only appears as alternate
    block: str = ""          # Block ID (e.g. 1001, EXB) — for EXB+SHINE bucket


def _normalize_time(s: str) -> Optional[str]:
    t = time_utils.normalize_time_str(s)
    return t


def row_to_packet(raw: RawRow, work_date: str, past_sentinel: bool) -> Packet:
    """Build one packet from a raw row. Sets exclusion_tags if excluded."""
    actual_start = _normalize_time(raw.actual_start_str)
    actual_end = _normalize_time(raw.actual_end_str)
    scheduled_end = _normalize_time(raw.scheduled_end_str)

    is_exb = "EXB" in (raw.block or "").upper()
    cond_lower = (raw.primary_condition_text or "").lower()
    is_shine = "shine" in cond_lower
    # EXB + SHINE = they worked a shine run; include and generate segments.
    # EXB + other condition (vacation, sick, etc.) = exclude.
    exb_shine_include = is_exb and is_shine

    tags = []
    if past_sentinel:
        tags.append(TAG_PAST_SENTINEL)
    if is_exb and not exb_shine_include:
        tags.append(TAG_EXTRABOARD)
    if raw.alternate_driver_present:
        tags.append(TAG_ALT_PRESENT)
    if raw.primary_condition_text and not exb_shine_include:
        tags.append(f"{TAG_PRIMARY_CONDITION}:{raw.primary_condition_text}")
    if not actual_start or not actual_end:
        tags.append(TAG_MISSING_TIME)
    if not scheduled_end:
        scheduled_end = actual_end  # fallback for LPI; may still exclude if missing times

    packet = Packet(
        emp_id=raw.emp_id,
        employee_name=raw.employee_name,
        work_date=work_date,
        actual_start_time=actual_start or "",
        actual_end_time=actual_end or "",
        scheduled_end_time=scheduled_end or "",
        scheduled_run_str=raw.shift_time_str or "",
        notes_text=raw.notes_text,
        alternate_driver_present=raw.alternate_driver_present,
        primary_condition_text=raw.primary_condition_text,
        source_row_index=raw.source_line_index,
        exclusion_tags=tags,
        potential_bleed=getattr(raw, "potential_bleed", False),
        alternate_emp_id=getattr(raw, "alternate_emp_id", "") or "",
        alternate_name=getattr(raw, "alternate_name", "") or "",
        block=raw.block or "",
    )
    if not tags:
        packet.actual_start_min = time_utils.parse_time(actual_start)
        packet.actual_end_min = time_utils.parse_time(actual_end)
        packet.scheduled_end_min = time_utils.parse_time(scheduled_end)
    return packet


def build_packets(
    raw_rows: List[RawRow],
    work_date: str,
    stopped_at_1based: int,
) -> List[Packet]:
    """Build one packet per raw row. stopped_at_1based: first line number that was TRANSIT SUPERVISOR."""
    packets = []
    for r in raw_rows:
        # Rows we have are already before the sentinel (parser stops before adding that line)
        past_sentinel = False
        p = row_to_packet(r, work_date, past_sentinel)
        packets.append(p)
    return packets


def partition_packets(packets: List[Packet]) -> tuple:
    """Return (included_packets, excluded_packets)."""
    included = [p for p in packets if not p.exclusion_tags]
    excluded = [p for p in packets if p.exclusion_tags]
    return included, excluded


def build_alt_synthetic_packets(
    all_packets: List[Packet],
    cte_ids: Set[str],
) -> List[Packet]:
    """
    Create synthetic packets for alternate drivers who only appear as alternate
    (not as primary on any row, not on EXB). They are drivers working OT on day off.
    Uses primary's start/end time; one segment, all OT or CTE per notes.
    """
    primary_emp_ids = {p.emp_id for p in all_packets}
    synthetic = []
    for p in all_packets:
        if not p.alternate_emp_id or not p.alternate_driver_present:
            continue
        alt_id = p.alternate_emp_id
        if alt_id in primary_emp_ids:
            continue  # Alt appears as primary elsewhere; they get hours from that row
        # Parse times from primary packet (excluded packets still have time strings)
        start_min = time_utils.parse_time(p.actual_start_time)
        end_min = time_utils.parse_time(p.actual_end_time)
        if start_min is None or end_min is None:
            continue
        syn = Packet(
            emp_id=alt_id,
            employee_name=p.alternate_name or f"Alt {alt_id}",
            work_date=p.work_date,
            actual_start_time=p.actual_start_time,
            actual_end_time=p.actual_end_time,
            scheduled_end_time=p.actual_end_time,
            scheduled_run_str=p.scheduled_run_str,
            notes_text=f"Alt for {p.employee_name} ({p.emp_id}) — {p.notes_text or ''}",
            alternate_driver_present=False,
            primary_condition_text="",
            actual_start_min=start_min,
            actual_end_min=end_min,
            scheduled_end_min=end_min,
            exclusion_tags=[],
            source_row_index=p.source_row_index,
            potential_bleed=False,
            alternate_emp_id="",
            alternate_name="",
            is_alt_synthetic=True,
        )
        synthetic.append(syn)
    return synthetic
