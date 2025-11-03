import streamlit as st
import base64
import os

st.set_page_config(page_title="Offline Excel Viewer", layout="wide")

# ---- Embedded CSS ----
custom_css = """
<style>
body {
  font-family: 'Segoe UI', sans-serif;
  background-color: #f9fafc;
}
#excel-container {
  margin: 10px auto;
  max-width: 98%;
  overflow: auto;
  box-shadow: 0 2px 6px rgba(0,0,0,0.1);
  border-radius: 6px;
  background: white;
  border: 1px solid #ddd;
}
.sheet-tabs {
  display: flex;
  gap: 6px;
  background: #f0f0f0;
  padding: 8px;
  border-radius: 6px 6px 0 0;
  border: 1px solid #ddd;
  border-bottom: none;
}
.sheet-tab {
  padding: 6px 12px;
  border-radius: 4px;
  background: #e0e0e0;
  cursor: pointer;
  transition: background 0.2s;
  font-weight: 500;
}
.sheet-tab:hover { background: #c8e6c9; }
.sheet-tab.active { background: #4CAF50; color: white; }
table {
  width: 100%;
  border-collapse: collapse;
  border-radius: 6px;
  font-size: 13px;
}
th, td {
  border: 1px solid #e0e0e0;
  padding: 6px 10px;
  text-align: left;
  white-space: nowrap;
}
thead {
  background-color: #4CAF50;
  color: white;
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 2;
}
tr:nth-child(even) { background-color: #f7f7f7; }
tr:hover { background-color: #e8f5e9; }
</style>
"""

# ---- Load local SheetJS ----
sheetjs_path = os.path.join("libs", r"C:\Users\Chief\Desktop\Excel Parser\excell-viewer-master\xlsx.full.min.js")
with open(sheetjs_path, "r", encoding="utf-8") as f:
    sheetjs_code = f.read()

# ---- Streamlit UI ----
st.title("📊 Offline Excel Viewer (All-in-One)")
uploaded_file = st.file_uploader("Upload a local Excel file", type=["xls", "xlsx"])

if uploaded_file:
    b64_excel = base64.b64encode(uploaded_file.read()).decode('utf-8')

    html_code = f"""
    {custom_css}
    <div class="sheet-tabs" id="sheet-tabs"></div>
    <div id="excel-container"></div>

    <script>
    {sheetjs_code}
    </script>

    <script>
    document.addEventListener("DOMContentLoaded", function() {{
        const base64Data = `{b64_excel}`;
        const binary = atob(base64Data);
        const workbook = XLSX.read(binary, {{ type: 'binary' }});
        const sheetNames = workbook.SheetNames;

        const tabContainer = document.getElementById("sheet-tabs");
        const excelContainer = document.getElementById("excel-container");

        sheetNames.forEach((name, i) => {{
            const btn = document.createElement("div");
            btn.className = "sheet-tab" + (i === 0 ? " active" : "");
            btn.innerText = name;
            btn.onclick = () => showSheet(name, btn);
            tabContainer.appendChild(btn);
        }});

        function showSheet(name, btn) {{
            document.querySelectorAll(".sheet-tab").forEach(tab => tab.classList.remove("active"));
            btn.classList.add("active");
            const sheet = workbook.Sheets[name];
            const html = XLSX.utils.sheet_to_html(sheet);
            excelContainer.innerHTML = html;
        }}

        // Show first sheet by default
        showSheet(sheetNames[0], document.querySelector(".sheet-tab"));
    }});
    </script>
    """

    st.components.v1.html(html_code, height=800, scrolling=True)
else:
    st.info("👆 Upload a local Excel file to view it.")
