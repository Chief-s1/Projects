import argparse
import concurrent.futures as cf
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

HEADER_ROWS_TO_SNIFF = 3
MAX_ROWS_TO_SCAN_FOR_VALUES = 200
RECOGNIZED_EXTS = {".xlsx", ".xlsm"}

RE_STORY = re.compile(r"\bUS\d{5}\b", re.IGNORECASE)
RE_SPRINT = re.compile(r"\bPE[ _]\d{2}\.\d{2}\b", re.IGNORECASE)

WHITESPACE_RUN = re.compile(r"[ \t\r\f\v\u00A0\u200B]+")
NEWLINE_RUN = re.compile(r"[\n\r]+")

def setup_logging(log_file: Optional[str], jsonl_events: Optional[str]):
    logger = logging.getLogger("final_results")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    jsonl_handle = open(jsonl_events, "w", encoding="utf-8") if jsonl_events else None
    return logger, jsonl_handle

def log_event(jsonl_handle, event: Dict[str, Any]):
    if not jsonl_handle: return
    try:
        jsonl_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        jsonl_handle.flush()
    except Exception:
        pass

def normalize_spaces(s: Any) -> str:
    if s is None: return ""
    s = str(s).replace("\u00A0", " ").replace("\u200B", "")
    s = NEWLINE_RUN.sub(" ", s)
    s = WHITESPACE_RUN.sub(" ", s)
    return s.strip()

def filename_looks_like_final_results(path: Path) -> bool:
    stem = path.stem
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', stem)
    s = s.replace('_', ' ').replace('-', ' ')
    s = re.sub(r'[^0-9a-zA-Z]+', ' ', s).lower()
    s = re.sub(r'\s+', ' ', s).strip()
    tokens = s.split()
    has_final = 'final' in tokens
    has_result_token = any(t in ('result','results') for t in tokens)
    phrase_fwd = re.search(r'\bfinal\s*result(s)?\b', s) is not None
    phrase_rev = re.search(r'\bresult(s)?\s*final\b', s) is not None
    return (has_final and has_result_token) or phrase_fwd or phrase_rev

def to_abs(p: Path) -> str:
    try:
        return str(p.resolve())
    except Exception:
        return str(p.absolute())

def merged_regions(ws: Worksheet) -> List[Dict[str, int]]:
    regs = []
    if not hasattr(ws, "merged_cells"): return regs
    try:
        for r in list(ws.merged_cells.ranges):
            regs.append({
                "min_row": r.min_row, "min_col": r.min_col,
                "max_row": r.max_row, "max_col": r.max_col,
                "value": ws.cell(row=r.min_row, column=r.min_col).value
            })
    except Exception:
        return []
    return regs

def sheet_to_2d_resolved(ws: Worksheet) -> List[List[Any]]:
    regs = merged_regions(ws)
    max_row, max_col = ws.max_row, ws.max_column
    data = []
    if not regs:
        for r in range(1, max_row + 1):
            data.append([ws.cell(row=r, column=c).value for c in range(1, max_col + 1)])
        return data
    for r in range(1, max_row + 1):
        row_vals = []
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if v is None:
                for M in regs:
                    if M["min_row"] <= r <= M["max_row"] and M["min_col"] <= c <= M["max_col"]:
                        v = M["value"]; break
            row_vals.append(v)
        data.append(row_vals)
    return data

def scan_entire_grid_for_story_and_sprint(grid: List[List[Any]]) -> Tuple[Optional[str], Optional[str]]:
    story_id, sprint = None, None
    for r in range(len(grid)):
        row = grid[r]
        for c in range(len(row)):
            txt = normalize_spaces(row[c])
            if not txt: continue
            if story_id is None:
                m = RE_STORY.search(txt)
                if m: story_id = m.group(0).upper()
            if sprint is None:
                n = RE_SPRINT.search(txt)
                if n:
                    val = n.group(0)
                    val = val.upper()
                    val = val.replace("PE_", "PE ").replace("  ", " ")
                    sprint = val
            if story_id and sprint:
                return story_id, sprint
    return story_id, sprint

def process_file(path, logger, jsonl_handle):
    file_path = to_abs(path)
    t0 = datetime.now()
    try:
        wb = load_workbook(filename=file_path, data_only=True, read_only=False, keep_links=False)
    except Exception as e:
        logger.error(f"Failed to open workbook: {file_path} :: {e}")
        log_event(jsonl_handle, {"event": "open_file", "status": "error", "file_path": file_path, "error": str(e)})
        return None, f"open_failed:{e}"

    try:
        story_id, sprint = None, None
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            try:
                merge_count = 0
                if hasattr(ws, "merged_cells") and ws.merged_cells:
                    try: merge_count = len(ws.merged_cells.ranges)
                    except Exception: merge_count = 0
                logger.debug(f"[merge_info] {file_path} :: {sheet_name} -> {merge_count} merges")
                grid = sheet_to_2d_resolved(ws)
                s_id, spr = scan_entire_grid_for_story_and_sprint(grid)
                if s_id and not story_id: story_id = s_id
                if spr and not sprint: sprint = spr
                if story_id and sprint: break
            except Exception as e:
                logger.warning(f"[sheet_skip] {file_path} :: {sheet_name} :: {e}")

        wb.close()

        missing = []
        if not story_id: missing.append("story_id")
        if not sprint: missing.append("sprint")
        if missing:
            logger.error(f"[required_missing] {file_path} -> {missing}")
            log_event(jsonl_handle, {"event": "extract_fields", "status": "error", "file_path": file_path, "missing": missing})
            return None, f"required_missing:{','.join(missing)}"

        record = {
            "file_path": file_path,
            "story_id": story_id,
            "sprint": sprint,
            "work_track": None,
            "business_domain": None
        }

        elapsed = int((datetime.now() - t0).total_seconds() * 1000)
        logger.info(f"[processed] {file_path} in {elapsed} ms")
        log_event(jsonl_handle, {"event": "processed", "status": "success", "file_path": file_path, "elapsed_ms": elapsed, "record_preview": record})
        return record, None

    except Exception as e:
        tb = traceback.format_exc(limit=2)
        logger.error(f"[process_error] {file_path} :: {e}")
        log_event(jsonl_handle, {"event": "process_error", "status": "error", "file_path": file_path, "error": str(e), "trace": tb})
        try: wb.close()
        except Exception: pass
        return None, f"process_error:{e}"

def discover_files(root: Path, logger: logging.Logger) -> List[Path]:
    files = []
    for base, _, names in os.walk(root):
        for n in names:
            p = Path(base) / n
            if p.suffix.lower() in RECOGNIZED_EXTS and filename_looks_like_final_results(p):
                files.append(p)
    files.sort(key=lambda x: str(x).lower())
    logger.info(f"[discovery] found {len(files)} under {to_abs(root)}")
    return files

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out-json", default="final_results_metadata.json")
    ap.add_argument("--failed-list", default="failed_files.txt")
    ap.add_argument("--log-file", default="run.log")
    ap.add_argument("--events-jsonl", default=None)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    logger, jsonl_handle = setup_logging(a.log_file, a.events_jsonl)
    root = Path(a.root)
    if not root.exists(): logger.error("Root path missing."); sys.exit(2)

    files = discover_files(root, logger)
    results, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = [ex.submit(process_file, p, logger, jsonl_handle) for p in files]
        for fut, p in zip(futs, files):
            rec, err = fut.result()
            if rec: results.append(rec)
            else: failed.append((to_abs(p), err or "unknown_error"))

    try:
        Path(a.out_json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[output_json] {len(results)} -> {a.out_json}")
    except Exception as e:
        logger.error(f"Write output failed: {e}")

    try:
        uniq = sorted({p for p, _ in failed})
        Path(a.failed_list).write_text("\n".join(uniq), encoding="utf-8")
        logger.info(f"[failed_list] {len(uniq)} -> {a.failed_list}")
        if failed:
            reasons_path = str(Path(a.failed_list).with_suffix(".jsonl"))
            with open(reasons_path, "w", encoding="utf-8") as fh:
                for p, reason in failed:
                    fh.write(json.dumps({"file_path": p, "reason": reason}, ensure_ascii=False) + "\n")
            logger.info(f"[failed_reasons] {len(failed)} -> {reasons_path}")
    except Exception as e:
        logger.error(f"Write failed list failed: {e}")

    logger.info(f"[summary] ok={len(results)} failed={len(failed)} total={len(files)}")
    if jsonl_handle:
        try: jsonl_handle.close()
        except Exception: pass

if __name__ == "__main__":
    main()