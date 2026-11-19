"""Write spreadsheet rows whose cells are always data, never formulas.

openpyxl stores any string that starts with ``=`` as a formula. Exports carry
text people typed (feedback comments, search queries, document titles), so a
comment such as ``=HYPERLINK(...)`` would run in Excel when an administrator
opens the file. None of the exports writes a formula on purpose.
"""

from typing import Any, Iterable

from openpyxl.worksheet.worksheet import Worksheet


def append_text_row(sheet: Worksheet, values: Iterable[Any]) -> None:
    """Append *values* as a row, keeping any formula-looking string as text."""
    sheet.append(list(values))
    for cell in sheet[sheet.max_row]:
        if cell.data_type == "f":
            cell.data_type = "s"
