import os, re, json
from pathlib import Path
from openpyxl import load_workbook

# 🧩 Change this to the absolute path of your folders.txt file
FOLDERS_FILE = Path(r"C:\Users\Swayam\Desktop\folders.txt")

RE_STORY = re.compile(r"\bUS\d{5}\b", re.IGNORECASE)

def normalize_spaces(s):
    if s is None:
        return ""
    return str(s).replace("\u00A0", " ").replace("\u200B", "").strip()

def merged_regions(ws):
    regs = []
    if not hasattr(ws, "merged_cells"):
        return regs
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

def sheet_to_2d_resolved(ws):
    regs = merged_regions(ws)
    R, C = ws.max_row, ws.max_column
    out = []
    if not regs:
        for r in range(1, R + 1):
            out.append([ws.cell(row=r, column=c).value for c in range(1, C + 1)])
        return out
    for r in range(1, R + 1):
        row_vals = []
        for c in range(1, C + 1):
            v = ws.cell(row=r, column=c).value
            if v is None:
                for M in regs:
                    if M["min_row"] <= r <= M["max_row"] and M["min_col"] <= c <= M["max_col"]:
                        v = M["value"]
                        break
            row_vals.append(v)
        out.append(row_vals)
    return out

def find_story_id_in_file(p: Path):
    try:
        wb = load_workbook(filename=str(p), data_only=True, read_only=False, keep_links=False)
    except PermissionError:
        print(f"[skip:locked] Permission denied: {p}")
        return None
    except Exception:
        return None
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            grid = sheet_to_2d_resolved(ws)
            for row in grid:
                for cell in row:
                    m = RE_STORY.search(normalize_spaces(cell))
                    if m:
                        wb.close()
                        return m.group(0).upper()
        wb.close()
        return None
    except Exception:
        try:
            wb.close()
        except Exception:
            pass
        return None

def read_roots_from_file(file_path: Path):
    try:
        text = file_path.read_text(encoding="utf-8-sig").splitlines()
    except PermissionError:
        print(f"[error] Permission denied reading {file_path}. Run as admin or move file.")
        return []
    except FileNotFoundError:
        print(f"[error] folders.txt not found: {file_path}")
        return []
    roots = []
    for line in text:
        s = line.strip().strip('"').strip("'")
        if not s or s.startswith("#"):
            continue
        p = Path(s)
        if p.is_dir():
            roots.append(p)
        else:
            print(f"[skip] Not a valid folder: {s}")
    return roots

def iter_excel_files_recursive(root: Path):
    exts = (".xlsx", ".xlsm", ".xls")
    for base, _, files in os.walk(root):
        for name in files:
            if name.lower().endswith(exts):
                yield Path(base) / name

def main():
    if not FOLDERS_FILE.exists():
        print(f"[error] folders.txt not found: {FOLDERS_FILE}")
        return
    roots = read_roots_from_file(FOLDERS_FILE)
    if not roots:
        print("[error] No valid folders found in folders.txt")
        return

    results = []
    for root in roots:
        for fp in iter_excel_files_recursive(root):
            sid = find_story_id_in_file(fp)
            if sid:
                results.append({
                    "root_folder": str(root.resolve()),
                    "file_path": str(fp.resolve()),
                    "story_id": sid
                })
                print(f"[✓] {sid} :: {fp}")
            else:
                print(f"[x] no story_id :: {fp}")

    output_path = Path("all_folders_story_ids.json")
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Saved {len(results)} entries to {output_path}")

if __name__ == "__main__":
    main()