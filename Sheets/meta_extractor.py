import json, re
from pathlib import Path
from openpyxl import load_workbook

RE_STORY = re.compile(r"\bUS\d{5}\b", re.IGNORECASE)

def normalize_spaces(s):
    if s is None: return ""
    return str(s).replace("\u00A0"," ").replace("\u200B","").strip()

def merged_regions(ws):
    regs=[]
    if not hasattr(ws,"merged_cells"): return regs
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
    out=[]
    if not regs:
        for r in range(1,R+1):
            out.append([ws.cell(row=r,column=c).value for c in range(1,C+1)])
        return out
    for r in range(1,R+1):
        row=[]
        for c in range(1,C+1):
            v = ws.cell(row=r,column=c).value
            if v is None:
                for M in regs:
                    if M["min_row"]<=r<=M["max_row"] and M["min_col"]<=c<=M["max_col"]:
                        v = M["value"]; break
            row.append(v)
        out.append(row)
    return out

def find_story_id_in_file(p: Path):
    try:
        wb = load_workbook(filename=str(p), data_only=True, read_only=False, keep_links=False)
    except Exception:
        return None
    try:
        for name in wb.sheetnames:
            ws = wb[name]
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
        return None

def read_folders_list(list_file: Path):
    items=[]
    for line in list_file.read_text(encoding="utf-8").splitlines():
        s=line.strip().strip('"').strip("'")
        if not s or s.startswith("#"): continue
        p=Path(s)
        if p.is_dir(): items.append(p)
    return items

def iter_excel_files_recursive(roots, follow_symlinks=False):
    patterns = ["*.xlsx","*.xlsm","*.xls"]
    for root in roots:
        for pat in patterns:
            # rglob is recursive
            yield from root.rglob(pat) if follow_symlinks else (p for p in root.rglob(pat) if not p.is_symlink())

def main():
    list_path = Path(input("Path to folders list (one folder per line): ").strip('" '))
    out_json = Path("story_id_results.json")

    roots = read_folders_list(list_path)
    results=[]
    for fp in iter_excel_files_recursive(roots, follow_symlinks=False):
        sid = find_story_id_in_file(fp)
        if sid:
            results.append({"file_path": str(fp.resolve()), "story_id": sid})
            print(f"[✓] {sid} :: {fp}")
        else:
            print(f"[x] no story_id :: {fp}")

    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_json}")

if __name__ == "__main__":
    main()