"""
FastAPI backend for DOS Primary Segment web app.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Import from parent - run from project root
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dos_primary_segment.parser import load_dos, load_preliminary_dos
from dos_primary_segment.packets import build_packets, partition_packets, build_alt_synthetic_packets
from dos_primary_segment.cte import load_cte_preferred
from dos_primary_segment.outputs import build_included_results
from dos_primary_segment.api_data import build_api_response

app = FastAPI(title="DOS Primary Segment Tool", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _work_date_from_filename(path: Path) -> str:
    stem = path.stem
    parts = stem.replace("_", " ").split()
    if not parts:
        return ""
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
    return ""


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/process")
async def process_dos(
    dos_file: UploadFile = File(...),
    dos_type: str = Form(default="final"),
    cte_file: UploadFile | None = File(default=None),
    work_date_override: str = Form(default=""),
):
    """Upload DOS (Final or Preliminary) + optional CTE config."""
    use_preliminary = (dos_type or "final").lower() == "preliminary"
    suffix = Path(dos_file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".txt", ".xlsx", ".csv"):
        raise HTTPException(400, "DOS file must be PDF, TXT, Excel, or CSV")

    with tempfile.TemporaryDirectory() as tmp:
        dos_path = Path(tmp) / (dos_file.filename or "dos.pdf")
        with open(dos_path, "wb") as f:
            f.write(await dos_file.read())

        cte_ids = set()
        if cte_file and cte_file.filename:
            cte_path = Path(tmp) / (cte_file.filename or "cte.xlsx")
            with open(cte_path, "wb") as f:
                f.write(await cte_file.read())
            cte_ids = load_cte_preferred(cte_path)
            if not cte_ids and cte_path.suffix.lower() == ".xlsx":
                from dos_primary_segment.cte import load_cte_preferred_xlsx
                try:
                    cte_ids = load_cte_preferred_xlsx(cte_path, sheet_name="in")
                except Exception:
                    cte_ids = load_cte_preferred(cte_path)

        if use_preliminary:
            raw_rows, stopped_at_1based, work_date_from_doc = load_preliminary_dos(dos_path)
        else:
            raw_rows, stopped_at_1based, work_date_from_doc = load_dos(dos_path)
        work_date = (
            work_date_override
            or work_date_from_doc
            or _work_date_from_filename(dos_path)
            or ""
        )

        packets = build_packets(raw_rows, work_date, stopped_at_1based)
        included_list, excluded_list = partition_packets(packets)
        alt_synthetic = build_alt_synthetic_packets(packets, cte_ids)
        included_list = included_list + alt_synthetic
        included_results = build_included_results(included_list, cte_ids)

        summary = {
            "detected": len(packets),
            "included": len(included_list),
            "excluded": len(excluded_list),
            "stopped_at_row": stopped_at_1based,
        }

        response = build_api_response(
            included_results,
            excluded_list,
            summary,
            work_date,
            cte_ids=cte_ids,
        )
        response["is_preliminary"] = use_preliminary
        return response
