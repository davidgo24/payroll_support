# DOS Primary Segment Tool — Version 1 MVP

Internal payroll support tool that generates **trusted time segment suggestions** from a Daily Operator Sheet (DOS) to reduce manual data entry into TimeClock. The tool does **not** automate payroll decisions; operators still enter data manually.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
# Basic: DOS PDF only (work date inferred from filename e.g. 2.12.26_Final.pdf → 02/12/2026)
python cli.py path/to/dos.pdf

# With CTE preferred list (Excel or CSV) and output directory
python cli.py 2.12.26_Final.pdf --cte path/to/Config_Cte.xlsx --out-dir out

# Override work date
python cli.py dos.pdf --work-date 02/12/2026 --out-dir out
```

### Arguments

| Argument | Description |
|----------|-------------|
| `dos` | DOS dataset: PDF or `.txt` |
| `--cte` | CTE preferred list: `cte_preferred.csv` or `Config_Cte.xlsx` (sheet with EmpID) |
| `--work-date` | Override work date (e.g. `02/12/2026`) |
| `--out-dir` | Directory for `excluded_ledger.csv` and `worklog.csv` |
| `--worklog` | Custom worklog CSV path (append-only) |

## Outputs

1. **Run summary** (printed every run): detected count, included, excluded, row where processing stopped at `TRANSIT SUPERVISOR`.
2. **Included output**: Human-readable segments for operator to enter into TimeClock (REG / OT / CTE / LPI with HH:MM boundaries).
3. **Excluded ledger** (`excluded_ledger.csv` in `--out-dir`): All excluded packets with `emp_id`, `work_date`, `exclusion_tags`, `notes_text`, `primary_condition_text`, `status=pending`.
4. **Worklog** (`worklog.csv` in `--out-dir` or `--worklog`): Append-only `emp_id,date,shape,status,timestamp` for operator tracking.

## Safety rules

- **Stop at TRANSIT SUPERVISOR**: Rows at and below this sentinel are ignored.
- **Exclude instead of guess**: Any uncertainty (alternate driver, primary condition, missing times) → packet goes to excluded ledger; no segment generation.
- **Times**: All times in 24-hour `HH:MM`. LPI minutes computed from schedule vs actual; notes used only for LPI *pay type* (CTE/OT), not duration.

## Segment shapes

- **A**: ≤ 8 hours → single REG segment.
- **B**: > 8 hours, single OT/CTE type (or LPI same type) → REG to t8, then OT/CTE to end; optional “OT includes LPI”.
- **C**: > 8 hours, LPI minutes > 0 and LPI pay type ≠ standard OT type → REG, OT/CTE to scheduled end, then LPI segment to actual end.

## Non-goals (out of scope)

Alternate driver reconciliation, extraboard logic, leave automation, payroll decision making, editable UI, AI inference, database persistence.
