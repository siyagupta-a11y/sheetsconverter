from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession


def read_spreadsheet(spreadsheet_id: str, creds: Credentials) -> dict:
    """Fetch all spreadsheet data including formulas and formatting in one request."""
    service = build('sheets', 'v4', credentials=creds)
    result = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=True,
    ).execute()
    return result


def export_spreadsheet_xlsx(spreadsheet_id: str, creds: Credentials) -> bytes:
    """Export Google Sheet as native XLSX bytes through Drive API."""
    session = AuthorizedSession(creds)
    url = (
        f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}/export"
        "?mimeType=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    res = session.get(url, timeout=60)
    if res.status_code >= 400:
        raise RuntimeError(f"Drive export failed ({res.status_code}): {res.text[:300]}")
    return res.content
