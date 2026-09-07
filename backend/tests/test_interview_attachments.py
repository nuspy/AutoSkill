"""Files attached to an interview: stored once, summarised so the model can read them."""

import io

from autoskill.services.interview.attachments import preview_of, store_attachment
from tests.conftest import auth, register


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Invoices"
    sheet.append(["List 1", "List 2"])
    for value in (10, 20, 30):
        sheet.append([value, None])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_spreadsheet_preview_shows_sheets_headers_and_rows():
    preview = preview_of("AutoSkillTest.xlsx", "", xlsx_bytes())
    assert "sheet 'Invoices'" in preview
    assert "List 1 | List 2" in preview
    assert "10" in preview


def test_csv_preview_counts_rows_and_columns():
    data = b"name,amount\nacme,10\nbeta,20\n"
    preview = preview_of("data.csv", "text/csv", data)
    assert "3 rows, 2 columns" in preview
    assert "name, amount" in preview


def test_unreadable_types_say_so_instead_of_pretending():
    assert "not extracted" in preview_of("scan.pdf", "application/pdf", b"%PDF-1.4 ...")
    assert "not read" in preview_of("photo.png", "image/png", b"\x89PNG\r\n")
    assert "save it as .xlsx" in preview_of("old.xls", "application/vnd.ms-excel", b"\xd0\xcf")


def test_a_broken_spreadsheet_does_not_raise():
    preview = preview_of("broken.xlsx", "", b"not really a workbook")
    assert "could not be read" in preview


def test_store_deduplicates_by_content():
    data = xlsx_bytes()
    first = store_attachment("a.xlsx", "", data)
    second = store_attachment("copy-of-a.xlsx", "", data)
    assert first["hash"] == second["hash"]  # same bytes, one copy
    assert first["name"] != second["name"]
    assert first["size"] == len(data)


async def test_upload_endpoint_returns_a_usable_descriptor(app_client):
    user = await register(app_client, "uploader@example.com")
    headers = auth(user["access_token"])
    project = (await app_client.post("/api/v1/projects", json={"name": "Ops"}, headers=headers)).json()

    res = await app_client.post(
        f"/api/v1/projects/{project['id']}/attachments",
        files={"file": ("AutoSkillTest.xlsx", xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "AutoSkillTest.xlsx"
    assert "sheet 'Invoices'" in body["preview"]

    empty = await app_client.post(
        f"/api/v1/projects/{project['id']}/attachments",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=headers,
    )
    assert empty.status_code == 422
