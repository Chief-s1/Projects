import sys, re, json
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

def iter_excel_files_recursive(root: Path):
    patterns = ["*.xlsx","*.xlsm","*.xls"]
    for pat in patterns:
        yield from root.rglob(pat)

def main():
    if len(sys.argv) < 2:
        print("Usage: python find_story_id.py <folder1> [<folder2> ...]")
        sys.exit(1)

    roots = [Path(p) for p in sys.argv[1:]]
    results=[]
    for root in roots:
        if not root.exists() or not root.is_dir():
            print(f"[skip] not a folder or missing: {root}")
            continue
        for fp in iter_excel_files_recursive(root):
            sid = find_story_id_in_file(fp)
            if sid:
                results.append({"file_path": str(fp.resolve()), "story_id": sid})
                print(f"[✓] {sid} :: {fp}")
            else:
                print(f"[x] no story_id :: {fp}")

    Path("story_id_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n✅ Saved results to story_id_results.json")

if __name__ == "__main__":
    main()