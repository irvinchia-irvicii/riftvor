"""export.py — xlsx export of a comparison table (openpyxl, export shape
ported from 3vor Fetch)."""
from __future__ import annotations

import io
import time

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from config import STORE_BY_KEY, STORE_ORDER

_HEADER_FILL = PatternFill("solid", fgColor="1F2430")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_BEST_FILL = PatternFill("solid", fgColor="C6EFCE")
_OOS_FONT = Font(color="999999", italic=True)


def comparison_xlsx(result: dict) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Comparison"
    headers = (["Card", "Set", "No.", "Finish", "Qty", "Best (SGD)"]
               + [STORE_BY_KEY[k]["name"] for k in STORE_ORDER])
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    for row in result.get("rows", []):
        values = [row["name"], row["set_code"], row["number"], row["finish"],
                  row["qty"], row["best_price"]]
        for key in STORE_ORDER:
            cell = row["stores"].get(key)
            values.append(cell["price"] if cell else None)
        ws.append(values)
        excel_row = ws.max_row
        for i, key in enumerate(STORE_ORDER):
            cell_data = row["stores"].get(key)
            cell = ws.cell(row=excel_row, column=7 + i)
            if cell_data:
                cell.hyperlink = cell_data["url"]
                cell.number_format = "0.00"
                if not cell_data["in_stock"]:
                    cell.font = _OOS_FONT
                elif (row["best_price"] is not None
                      and cell_data["price"] == row["best_price"]):
                    cell.fill = _BEST_FILL
        ws.cell(row=excel_row, column=6).number_format = "0.00"
    if result.get("unmatched"):
        ws2 = wb.create_sheet("Unmatched")
        ws2.append(["Query"])
        for entry in result["unmatched"]:
            ws2.append([entry["raw"]])
    widths = [32, 6, 8, 8, 5, 10] + [14] * len(STORE_ORDER)
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def filename() -> str:
    return f"riftvor_comparison_{time.strftime('%Y%m%d_%H%M')}.xlsx"
