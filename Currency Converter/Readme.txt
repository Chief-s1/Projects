import openpyxl
from datetime import datetime
import os

# === CONFIGURATION ===
input_file = 'input.xlsx'                  # Original Excel file
sheet_name = 'Sheet1'                      # Sheet name to update
cells_to_update = ['B2', 'C4', 'D6']       # List of specific cells to change
output_folder = '.'                        # Folder where updated file will be saved

# === MAIN LOGIC ===
# Load workbook and select sheet
wb = openpyxl.load_workbook(input_file)
sheet = wb[sheet_name]

# Format today's date as 22-Jun-2025
today_date = datetime.today().strftime('%d-%b-%Y')

# Update all specified cells
for cell in cells_to_update:
    sheet[cell] = today_date

# Save updated workbook with today's date in the filename
file_date = datetime.today().strftime('%d-%b-%Y')
new_filename = f"updated_{file_date}.xlsx"
new_path = os.path.join(output_folder, new_filename)
wb.save(new_path)

print(f"✅ Updated cells: {cells_to_update}")
print(f"📁 File saved as: {new_path}")