#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
final_results_extract.py

Recursively scan for “final results” Excel files (any naming variation),
extract required fields from a fixed template sheet, and write a single JSON file.

Required fields per file:
  - story_id           (regex from Request Description)
  - work_track         (from Work Track)
  - sprint             (regex from Result Location)
  - business_domain    (detected from Result Location or Output and Logs using your domain list)
  - file_path          (absolute path incl. filename)

Robust features:
  - Works offline; .xlsx/.xlsm (openpyxl)
  - Handles merged cells (expands merge ranges)
  - Handles headers broken by newlines / stray whitespace
  - Header normalization (snake_case)
  - Detailed logging + a text file of files that failed parsing
  - Optional JSONL event log for programmatic audits

Usage (examples):
  python final_results_extract.py "D:/reports" \
      --out-json "final_results_metadata.json" \
      --failed-list "failed_files.txt" \
      --domains "domains.json" \
      --log-file "run.log"

  # domains.json format (recommended):
  # {
  #   "domains": ["FP_Modernization","APP admin","Fee Return"],
  #   "aliases": {
  #     "fp_mod": "FP_Modernization",
  #     "fp modernization": "FP_Modernization",
  #     "application admin": "APP admin"
  #   }
  # }

Author: You + GPT-5 Thinking
"""

import argparse
import concurrent.futures as cf
import fnmatch
import json
import logging
import os
import re
import sys
import traceback
from collections import Counter
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

try:
    from openpyxl import load_workbook
    from openpyxl.worksheet.worksheet import Worksheet
except Exception as e:
    print("ERROR: openpyxl is required. Install with: pip install openpyxl", file=sys.stderr)
    raise

# -----------------------------
# Configuration defaults
# -----------------------------
FINAL_NAME_REGEX = re.compile(r"(?i).*final\W*results?.*\.(xlsx|xlsm)$")  # filename rule
HEADER_ROWS_TO_SNIFF = 3  # how many top rows to use for header consolidation
MAX_ROWS_TO_SCAN_FOR_VALUES = 200  # scan first N data rows for story_id/sprint
RECOGNIZED_EXTS = {".xlsx", ".xlsm"}  # scope to openpyxl-friendly formats

# Required columns (by normalized header names) in the fixed template:
REQ_DESC_HEADERS = ["request_description"]
WORK_TRACK_HEADERS = ["work_track", "workstream", "work_stream", "track"]
RESULT_LOC_HEADERS = ["result_location", "sprint"]  # template may label either
OUTPUT_LOGS_HEADERS = ["output_and_logs", "output_logs", "outputs_and_logs"]

# Regexes for field extraction
RE_STORY = re.compile(r"\bUS\d{3,}\b", re.IGNORECASE)
RE_SPRINTS = [
    re.compile(r"\bPE\s*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\bPI\s*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:Sprint|S|SPR)\s*\d+\b", re.IGNORECASE),
]

WHITESPACE_RUN = re.compile(r"[ \t\r\f\v\u00A0\u200B]+")
NEWLINE_RUN = re.compile(r"[\n\r]+")

# -----------------------------
# Logging setup
# -----------------------------
def setup_logging(log_file: Optional[str], jsonl_events: Optional[str]) -> Tuple[logging.Logger, Optional[Any]]:
    logger = logging.getLogger("final_results")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler (INFO+)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Rotating file handler (DEBUG+)
    if log_file:
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    # JSONL events file
    jsonl_handle = None
    if jsonl_events:
        jsonl_handle = open(jsonl_events, "w", encoding="utf-8")

    return logger, jsonl_handle


def log_event(jsonl_handle, event: Dict[str, Any]):
    if not jsonl_handle:
        return
    try:
        jsonl_handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        jsonl_handle.flush()
    except Exception:
        pass

# -----------------------------
# Helpers
# -----------------------------
def normalize_spaces(s: str) -> str:
    if s is None:
        return ""
    # convert NBSP/zero-width to normal spaces, collapse whitespace & newlines
    s = str(s)
    s = s.replace("\u00A0", " ").replace("\u200B", "")
    s = NEWLINE_RUN.sub(" ", s)
    s = WHITESPACE_RUN.sub(" ", s)
    return s.strip()

def normalize_header(s: str) -> str:
    s = normalize_spaces(s)
    s = s.lower()
    # replace any non-alphanumeric with underscore
    s = re.sub(r"[^0-9a-z]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")

def find_first_header(headers: List[str], candidates: List[str]) -> Optional[int]:
    """Return index of the first column whose normalized header matches any of candidates."""
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

# -----------------------------
# Domain resolution
# -----------------------------
class DomainResolver:
    def __init__(self, domains: List[str], aliases: Dict[str, str]):
        # Canonical set
        self.canon = {self._norm(d): d for d in domains}
        # Alias map -> canonical key string
        self.aliases = {}
        for k, v in aliases.items():
            self.aliases[self._norm(k)] = v  # v must be canonical name present in domains

    def _norm(self, s: str) -> str:
        s = normalize_spaces(s)
        s = s.lower()
        s = re.sub(r"[^0-9a-z]+", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("_")

    def resolve(self, text: str) -> Tuple[Optional[str], str]:
        """
        Try to resolve a business domain from text.
        Returns (domain_or_none, method) where method in {"exact","alias","contains","unresolved"}.
        """
        if not text:
            return None, "unresolved"
        t = self._norm(text)

        # exact canonical match
        if t in self.canon:
            return self.canon[t], "exact"
        # alias
        if t in self.aliases:
            return self.aliases[t], "alias"

        # token contains: see if any canonical domain tokens appear in text
        # (strict contains to avoid random guesses)
        for key_norm, dom in self.canon.items():
            if key_norm and key_norm in t:
                return dom, "contains"

        # alias contains
        for alias_norm, dom in self.aliases.items():
            if alias_norm and alias_norm in t:
                return dom, "contains"

        return None, "unresolved"

def load_domain_config(path: Optional[str], logger: logging.Logger) -> DomainResolver:
    if not path:
        logger.warning("No domain file provided; business_domain may be unresolved.")
        return DomainResolver(domains=[], aliases={})
    p = Path(path)
    if not p.exists():
        logger.error(f"Domain file does not exist: {path}. Using empty domain set.")
        return DomainResolver(domains=[], aliases={})

    try:
        if p.suffix.lower() in {".json"}:
            data = json.loads(p.read_text(encoding="utf-8"))
            domains = data.get("domains", []) or []
            aliases = data.get("aliases", {}) or {}
            if not isinstance(domains, list) or not isinstance(aliases, dict):
                raise ValueError("Invalid JSON schema for domains.json")
            return DomainResolver(domains=domains, aliases=aliases)
        else:
            # treat as plaintext: one canonical domain per line
            domains = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
            return DomainResolver(domains=domains, aliases={})
    except Exception as e:
        logger.error(f"Failed to load domain config: {e}")
        return DomainResolver(domains=[], aliases={})

# -----------------------------
# Excel processing
# -----------------------------
def expand_merged_cells(ws: Worksheet) -> None:
    """
    For each merged cell range, copy the top-left value into all cells in the range.
    (Modifies worksheet in-memory; does not save to disk.)
    """
    # Copy ranges to avoid iteration issues when unmerging
    ranges = list(ws.merged_cells.ranges)
    for mcr in ranges:
        min_col = mcr.min_col
        min_row = mcr.min_row
        value = ws.cell(row=min_row, column=min_col).value
        for r in range(mcr.min_row, mcr.max_row + 1):
            for c in range(mcr.min_col, mcr.max_col + 1):
                ws.cell(row=r, column=c, value=value)

def sheet_to_2d(ws: Worksheet) -> List[List[Any]]:
    max_row = ws.max_row
    max_col = ws.max_column
    data = []
    for r in range(1, max_row + 1):
        row_vals = []
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            row_vals.append(v)
        data.append(row_vals)
    return data

def consolidate_headers(grid: List[List[Any]], header_rows: int) -> Tuple[List[str], int]:
    """
    Consolidate the first `header_rows` rows into a single list of header strings.
    Returns (headers, data_start_row_index) where data_start_row_index is 0-based index
    for the first data row in `grid`.
    """
    if not grid:
        return [], 0
    rows = grid[:min(header_rows, len(grid))]
    max_cols = max((len(r) for r in rows), default=0)
    headers = []
    for c in range(max_cols):
        parts = []
        for r in rows:
            if c < len(r):
                cell = r[c]
                if cell is None:
                    continue
                txt = normalize_spaces(str(cell))
                if txt:
                    parts.append(txt)
        if parts:
            headers.append(normalize_header(" ".join(parts)))
        else:
            headers.append(f"col_{c+1}")
    return headers, len(rows)

def extract_required_fields(
    headers: List[str],
    grid: List[List[Any]],
    data_start_idx: int,
    resolver: DomainResolver,
    logger: logging.Logger,
    file_path: str,
    sheet_name: str,
    strict_domain: bool = False,
) -> Dict[str, Any]:
    """
    Extract story_id, work_track, sprint, business_domain from the given grid+headers.
    """
    event_base = {"file_path": file_path, "sheet_name": sheet_name}

    # Column indices
    req_desc_idx = find_first_header(headers, REQ_DESC_HEADERS)
    work_track_idx = find_first_header(headers, WORK_TRACK_HEADERS)
    result_loc_idx = find_first_header(headers, RESULT_LOC_HEADERS)
    output_logs_idx = find_first_header(headers, OUTPUT_LOGS_HEADERS)

    # story_id from Request Description
    story_id = None
    if req_desc_idx is not None:
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if req_desc_idx < len(row):
                cell = normalize_spaces(row[req_desc_idx])
                if not cell:
                    continue
                m = RE_STORY.search(cell)
                if m:
                    story_id = m.group(0).upper()
                    break
    # sprint from Result Location
    sprint = None
    result_loc_text = ""
    if result_loc_idx is not None:
        # Prefer first non-empty cell in the column within scanning window
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
                            # Normalize: single space after prefix
                            s = re.sub(r"(?i)^(pe|pi|s|spr)\s*", lambda m: m.group(1).upper() + " ", s)
                            s = re.sub(r"\s+", " ", s).strip()
                            # Normalize "SPR 5" → "Sprint 5" if needed
                            s = re.sub(r"(?i)^(spr)\s+(\d+)$", r"Sprint \2", s)
                            s = re.sub(r"(?i)^(s)\s+(\d+)$", r"Sprint \2", s)
                            sprint = s
                            break
                    break

    # work_track
    work_track = None
    if work_track_idx is not None:
        candidates = []
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if work_track_idx < len(row):
                t = normalize_spaces(row[work_track_idx])
                if t:
                    candidates.append(t)
        if candidates:
            # First non-empty (deterministic); change to mode() if you prefer
            work_track = candidates[0]

    # business_domain: from Result Location, else Output and Logs
    business_domain = None
    domain_method = "unresolved"
    lookup_texts = []
    if result_loc_text:
        lookup_texts.append(result_loc_text)
    if output_logs_idx is not None:
        # find first non-empty in output_logs within scan window
        for r in range(data_start_idx, min(len(grid), data_start_idx + MAX_ROWS_TO_SCAN_FOR_VALUES)):
            row = grid[r]
            if output_logs_idx < len(row):
                t = normalize_spaces(row[output_logs_idx])
                if t:
                    lookup_texts.append(t)
                    break

    for txt in lookup_texts:
        dom, method = resolver.resolve(txt)
        if dom:
            business_domain = dom
            domain_method = method
            break

    # Validate requireds
    missing = []
    if not story_id:
        missing.append("story_id")
    if not sprint:
        missing.append("sprint")
    if strict_domain and not business_domain:
        missing.append("business_domain")

    return {
        "story_id": story_id,
        "work_track": work_track,
        "sprint": sprint,
        "business_domain": business_domain,
        "domain_method": domain_method,
        "missing": missing,
        "result_location_text": result_loc_text,  # helpful if you want to keep for audits; can drop before writing
    }

# -----------------------------
# File processing
# -----------------------------
def process_file(
    path: Path,
    resolver: DomainResolver,
    sheet_name: Optional[str],
    strict_domain: bool,
    logger: logging.Logger,
    jsonl_handle: Optional[Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns (record_dict_or_None, error_reason_or_None)
    If error_reason is not None, the file is considered failed.
    """
    file_path = to_abs(path)
    t0 = datetime.now()

    try:
        logger.debug(f"[open_file] {file_path}")
        wb = load_workbook(filename=file_path, data_only=True, read_only=False)
    except Exception as e:
        logger.error(f"Failed to open workbook: {file_path} :: {e}")
        log_event(jsonl_handle, {"event": "open_file", "status": "error", "file_path": file_path, "error": str(e)})
        return None, f"open_failed: {e}"

    try:
        # Pick sheet
        ws: Worksheet
        if sheet_name:
            if sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                wb.close()
                msg = f"sheet_not_found: {sheet_name}"
                logger.error(f"{msg} in {file_path}")
                log_event(jsonl_handle, {"event": "sheet_select", "status": "error", "file_path": file_path, "sheet": sheet_name, "error": "not_found"})
                return None, msg
        else:
            # default: first visible sheet
            ws = wb[wb.sheetnames[0]]

        # Expand merges
        merges = len(ws.merged_cells.ranges)
        if merges:
            expand_merged_cells(ws)
            logger.info(f"[expand_merges] {file_path} : expanded {merges} merged ranges")

        grid = sheet_to_2d(ws)
        headers, data_start_idx = consolidate_headers(grid, HEADER_ROWS_TO_SNIFF)

        log_event(jsonl_handle, {
            "event": "headers_built", "status": "success",
            "file_path": file_path, "sheet_name": ws.title,
            "headers": headers, "data_start_idx": data_start_idx
        })

        # Extract fields
        fields = extract_required_fields(
            headers=headers,
            grid=grid,
            data_start_idx=data_start_idx,
            resolver=resolver,
            logger=logger,
            file_path=file_path,
            sheet_name=ws.title,
            strict_domain=strict_domain,
        )

        missing = fields.get("missing", [])
        if missing:
            wb.close()
            logger.error(f"[required_missing] {file_path} -> missing: {missing}")
            log_event(jsonl_handle, {
                "event": "extract_fields", "status": "error",
                "file_path": file_path, "missing": missing
            })
            return None, f"required_missing:{','.join(missing)}"

        record = {
            "file_path": file_path,
            "story_id": fields["story_id"],
            "work_track": fields["work_track"],
            "sprint": fields["sprint"],
            "business_domain": fields["business_domain"],
        }

        # Optional: drop helper
        # fields.pop("result_location_text", None)

        wb.close()
        t1 = datetime.now()
        elapsed_ms = int((t1 - t0).total_seconds() * 1000)
        logger.info(f"[processed] {file_path} in {elapsed_ms} ms")
        log_event(jsonl_handle, {
            "event": "file_processed", "status": "success",
            "file_path": file_path, "elapsed_ms": elapsed_ms,
            "record_preview": record
        })
        return record, None

    except Exception as e:
        tb = traceback.format_exc(limit=2)
        logger.error(f"[process_error] {file_path} :: {e}")
        log_event(jsonl_handle, {
            "event": "process_error", "status": "error",
            "file_path": file_path, "error": str(e), "trace": tb
        })
        try:
            wb.close()
        except Exception:
            pass
        return None, f"process_error: {e}"

# -----------------------------
# Discovery
# -----------------------------
def discover_files(root: Path, logger: logging.Logger) -> List[Path]:
    files = []
    for base, dirs, filenames in os.walk(root):
        # skip some common noise dirs if you want to:
        # dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
        for name in filenames:
            p = Path(base) / name
            if p.suffix.lower() in RECOGNIZED_EXTS and filename_looks_like_final_results(p):
                files.append(p)
    files.sort(key=lambda x: str(x).lower())
    logger.info(f"[discovery] found {len(files)} candidate files under {to_abs(root)}")
    return files

# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser(description="Extract metadata from 'final results' Excel files into JSON.")
    ap.add_argument("root", help="Root directory to scan recursively")
    ap.add_argument("--out-json", default="final_results_metadata.json", help="Output JSON file (array)")
    ap.add_argument("--failed-list", default="failed_files.txt", help="Path to write list of failed files")
    ap.add_argument("--domains", default=None, help="Domain config file (JSON recommended, or plaintext one-per-line)")
    ap.add_argument("--log-file", default="run.log", help="Path to rotating log file")
    ap.add_argument("--events-jsonl", default=None, help="Optional JSONL structured events log")
    ap.add_argument("--sheet-name", default=None, help="Exact sheet name if fixed by template (default: first sheet)")
    ap.add_argument("--strict-domain", action="store_true", help="Treat unresolved business_domain as a hard failure")
    ap.add_argument("--workers", type=int, default=4, help="Concurrency (number of worker threads)")
    args = ap.parse_args()

    logger, jsonl_handle = setup_logging(args.log_file, args.events_jsonl)
    resolver = load_domain_config(args.domains, logger)

    root = Path(args.root)
    if not root.exists():
        logger.error(f"Root path does not exist: {args.root}")
        sys.exit(2)

    files = discover_files(root, logger)
    results: List[Dict[str, Any]] = []
    failed: List[Tuple[str, str]] = []  # (path, reason)

    # Process files (concurrently)
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = []
        for p in files:
            futures.append(ex.submit(
                process_file, p, resolver, args.sheet_name, args.strict_domain, logger, jsonl_handle
            ))
        for fut, p in zip(futures, files):
            rec, err = fut.result()
            if rec:
                results.append(rec)
            else:
                failed.append((to_abs(p), err or "unknown_error"))

    # Write outputs
    try:
        Path(args.out_json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[output_json] Wrote {len(results)} records to {args.out_json}")
        log_event(jsonl_handle, {"event": "write_output", "status": "success", "out_json": args.out_json, "records": len(results)})
    except Exception as e:
        logger.error(f"Failed to write output JSON: {e}")
        log_event(jsonl_handle, {"event": "write_output", "status": "error", "error": str(e)})
        # do not exit; still write failed list below

    # Write failed files list (unique, sorted)
    try:
        unique_sorted = sorted({p for p, _ in failed})
        Path(args.failed_list).write_text("\n".join(unique_sorted), encoding="utf-8")
        logger.info(f"[failed_list] Wrote {len(unique_sorted)} failed files to {args.failed_list}")
        if failed:
            # also write reasons alongside (optional companion file)
            reasons_path = str(Path(args.failed_list).with_suffix(".jsonl"))
            with open(reasons_path, "w", encoding="utf-8") as fh:
                for p, reason in failed:
                    fh.write(json.dumps({"file_path": p, "reason": reason}, ensure_ascii=False) + "\n")
            logger.info(f"[failed_reasons] Wrote reasons to {reasons_path}")
    except Exception as e:
        logger.error(f"Failed to write failed files list: {e}")

    # Summary
    logger.info(
        "[summary] discovered=%d ok=%d failed=%d out=%s failed_list=%s",
        len(files), len(results), len({p for p, _ in failed}), args.out_json, args.failed_list
    )

    if jsonl_handle:
        try:
            jsonl_handle.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
