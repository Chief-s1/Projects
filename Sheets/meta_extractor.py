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

FINAL_NAME_REGEX = re.compile(r"(?i).*final\W*results?.*\.(xlsx|xlsm)$")
HEADER_ROWS_TO_SNIFF = 3
MAX_ROWS_TO_SCAN_FOR_VALUES = 200
RECOGNIZED_EXTS = {".xlsx", ".xlsm"}

REQ_DESC_HEADERS = ["request_description"]
WORK_TRACK_HEADERS = ["work_track", "workstream", "work_stream", "track"]
RESULT_LOC_HEADERS = ["result_location", "sprint"]
OUTPUT_LOGS_HEADERS = ["output_and_logs", "output_logs", "outputs_and_logs"]

RE_STORY = re.compile(r"\bUS\d{3,}\b", re.IGNORECASE)
RE_SPRINTS = [
    re.compile(r"\bPE\s*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\bPI\s*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:Sprint|S|SPR)\s*\d+\b", re.IGNORECASE),
]

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

def normalize_header(s: str) -> str:
    s = normalize_spaces(s).lower()
    s = re.sub(r"[^0-9a-z]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def find_first_header(headers: List[str], candidates: List[str]) -> Optional[int]:
    norm = [normalize_header(h) for h in headers]
    cand_norm = set(candidates)
    for idx, h in enumerate(norm):
        if h in cand_norm:
            return idx
    return None

def filename_looks_like_final_results(path: Path) -> bool:
    return bool(FINAL_NAME_REGEX.match(path.name))

def to_abs(p: Path) -> str:
    try:
        return str(p.resolve())
    except Exception:
        return str(p.absolute())

class DomainResolver:
    def __init__(self, domains: List[str], aliases: Dict[str, str]):
        self.canon = {self._norm(d): d for d in domains}
        self.aliases = {self._norm(k): v for k, v in aliases.items()} if aliases else {}
    def _norm(self, s: str) -> str:
        s = normalize_spaces(s).lower()
        s = re.sub(r"[^0-9a-z]+", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("_")
    def resolve(self, text: str) -> Tuple[Optional[str], str]:
        if not text: return None, "unresolved"
        t = self._norm(text)
        if t in self.canon: return self.canon[t], "exact"
        if t in self.aliases: return self.aliases[t], "alias"
        for k_norm, dom in self.canon.items():
            if k_norm and k_norm in t: return dom, "contains"
        for a_norm, dom in self.aliases.items():
            if a_norm and a_norm in t: return dom, "contains"
        return None, "unresolved"

def load_domain_config(path: Optional[str], logger: logging.Logger) -> DomainResolver:
    if not path:
        logger.warning("No domain file provided; business_domain may be unresolved.")
        return DomainResolver([], {})
    p = Path(path)
    if not p.exists():
        logger.error(f"Domain file missing: {path}")
        return DomainResolver([], {})
    try:
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            return DomainResolver(data.get("domains", []), data.get("aliases", {}))
        else:
            domains = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
            return DomainResolver(domains, {})
    except Exception as e:
        logger.error(f"Failed to load domain config: {e}")
        return DomainResolver([], {})

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

def consolidate_headers(grid: List[List[Any]], header_rows: int) -> Tuple[List[str], int]:
    if not grid: return [], 0
    rows = grid[:min(header_rows, len(grid))]
    max_cols = max((len(r) for r in rows), default=0)
    headers = []
    for c in range(max_cols):
        parts = []
        for r in rows:
            if c < len(r):
                cell = r[c]
                if cell:
                    txt = normalize_spaces(str(cell))
                    if txt: parts.append(txt)
        headers.append(normalize_header(" ".join(parts)) if parts else f"col_{c+1}")
    return headers, len(rows)

def extract_required_fields(headers, grid, data_start_idx, resolver, logger, file_path, sheet_name, strict_domain=False):
    req_desc_idx = find_first_header(headers, REQ_DESC_HEADERS)
    work_track_idx = find_first_header(headers, WORK_TRACK_HEADERS)
    result_loc_idx = find_first_header(headers, RESULT_LOC_HEADERS)
    output_logs_idx = find_first_header(headers, OUTPUT_LOGS_HEADERS)
    story_id = None
    if req_desc_idx is not None:
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if req_desc_idx < len(row):
                cell = normalize_spaces(row[req_desc_idx])
                if not cell: continue
                m = RE_STORY.search(cell)
                if m: story_id = m.group(0).upper(); break
    sprint, result_loc_text = None, ""
    if result_loc_idx is not None:
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if result_loc_idx < len(row):
                t = normalize_spaces(row[result_loc_idx])
                if t:
                    result_loc_text = t
                    for rx in RE_SPRINTS:
                        mm = rx.search(t)
                        if mm:
                            s = mm.group(0)
                            s = re.sub(r"(?i)^(pe|pi|s|spr)\s*", lambda m: m.group(1).upper() + " ", s)
                            s = re.sub(r"\s+", " ", s).strip()
                            s = re.sub(r"(?i)^(spr)\s+(\d+)$", r"Sprint \2", s)
                            s = re.sub(r"(?i)^(s)\s+(\d+)$", r"Sprint \2", s)
                            sprint = s; break
                    break
    work_track = None
    if work_track_idx is not None:
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if work_track_idx < len(row):
                t = normalize_spaces(row[work_track_idx])
                if t: work_track = t; break
    business_domain, domain_method = None, "unresolved"
    lookup_texts = []
    if result_loc_text: lookup_texts.append(result_loc_text)
    if output_logs_idx is not None:
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if output_logs_idx < len(row):
                t = normalize_spaces(row[output_logs_idx])
                if t: lookup_texts.append(t); break
    for txt in lookup_texts:
        dom, method = resolver.resolve(txt)
        if dom: business_domain, domain_method = dom, method; break
    missing = []
    if not story_id: missing.append("story_id")
    if not sprint: missing.append("sprint")
    if strict_domain and not business_domain: missing.append("business_domain")
    return {
        "story_id": story_id, "work_track": work_track,
        "sprint": sprint, "business_domain": business_domain,
        "domain_method": domain_method, "missing": missing
    }

def process_file(path, resolver, sheet_name, strict_domain, logger, jsonl_handle):
    file_path = to_abs(path)
    t0 = datetime.now()
    try:
        wb = load_workbook(filename=file_path, data_only=True, read_only=False, keep_links=False)
    except Exception as e:
        logger.error(f"Failed to open workbook: {file_path} :: {e}")
        log_event(jsonl_handle, {"event": "open_file", "status": "error", "file_path": file_path, "error": str(e)})
        return None, f"open_failed:{e}"
    try:
        ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb[wb.sheetnames[0]]
        merge_count = 0
        if hasattr(ws, "merged_cells") and ws.merged_cells:
            try: merge_count = len(ws.merged_cells.ranges)
            except Exception: merge_count = 0
        logger.info(f"[merge_info] {file_path} : {merge_count} merged ranges")
        grid = sheet_to_2d_resolved(ws)
        headers, data_start_idx = consolidate_headers(grid, HEADER_ROWS_TO_SNIFF)
        fields = extract_required_fields(headers, grid, data_start_idx, resolver, logger, file_path, ws.title, strict_domain)
        missing = fields.get("missing", [])
        if missing:
            wb.close()
            logger.error(f"[required_missing] {file_path} -> {missing}")
            return None, f"required_missing:{','.join(missing)}"
        record = {
            "file_path": file_path,
            "story_id": fields["story_id"],
            "work_track": fields["work_track"],
            "sprint": fields["sprint"],
            "business_domain": fields["business_domain"]
        }
        wb.close()
        elapsed = int((datetime.now() - t0).total_seconds() * 1000)
        logger.info(f"[processed] {file_path} in {elapsed} ms")
        log_event(jsonl_handle, {"event": "processed", "status": "success", "file_path": file_path})
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
    ap.add_argument("--domains", default=None)
    ap.add_argument("--log-file", default="run.log")
    ap.add_argument("--events-jsonl", default=None)
    ap.add_argument("--sheet-name", default=None)
    ap.add_argument("--strict-domain", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    logger, jsonl_handle = setup_logging(a.log_file, a.events_jsonl)
    resolver = load_domain_config(a.domains, logger)
    root = Path(a.root)
    if not root.exists(): logger.error("Root path missing."); sys.exit(2)
    files = discover_files(root, logger)
    results, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        futs = [ex.submit(process_file, p, resolver, a.sheet_name, a.strict_domain, logger, jsonl_handle) for p in files]
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
    except Exception as e:
        logger.error(f"Write failed list failed: {e}")
    logger.info(f"[summary] ok={len(results)} failed={len(failed)} total={len(files)}")
    if jsonl_handle:
        try: jsonl_handle.close()
        except Exception: pass

if __name__ == "__main__":
    main()