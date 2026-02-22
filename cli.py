#!/usr/bin/env python3
"""
DOS Primary Segment Tool — Version 1 MVP
CLI: process DOS (PDF or text), output segments for clean Primary employees.
"""
import argparse
import sys
from pathlib import Path

# Run from project root or with module path
try:
    from dos_primary_segment.run import run
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dos_primary_segment.run import run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DOS Primary Segment Tool — generate time segment suggestions for TimeClock entry.",
    )
    parser.add_argument(
        "dos",
        type=Path,
        help="DOS dataset (PDF, TXT, CSV, or Excel)",
    )
    parser.add_argument(
        "--cte",
        type=Path,
        default=None,
        help="CTE preferred list (cte_preferred.csv or Config_Cte.xlsx)",
    )
    parser.add_argument(
        "--work-date",
        type=str,
        default=None,
        help="Work date override (e.g. 02/12/2026)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for excluded_ledger.csv and worklog.csv",
    )
    parser.add_argument(
        "--worklog",
        type=Path,
        default=None,
        help="Worklog CSV path (append-only). Default: <out-dir>/worklog.csv",
    )
    args = parser.parse_args()

    if not args.dos.exists():
        print(f"Error: DOS file not found: {args.dos}", file=sys.stderr)
        return 1

    try:
        result = run(
            dos_path=args.dos,
            cte_path=args.cte,
            work_date_override=args.work_date,
            out_dir=args.out_dir,
            worklog_path=args.worklog,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Run summary (printed every run)
    print(result.summary_text)
    print()
    print("Included = primary vehicle drivers who worked their run (LPI if any). Enter these into TimeClock.")
    print("Excluded = everyone else (before TRANSIT SUPERVISOR row); handle manually. All listed in excluded ledger.")
    print()

    # Included output (human-readable)
    if result.included_output_text:
        print("--- INCLUDED (enter into TimeClock) ---")
        print(result.included_output_text)
    else:
        print("--- INCLUDED: none ---")

    if result.excluded_ledger_path:
        print()
        print(f"Excluded ledger: {result.excluded_ledger_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
