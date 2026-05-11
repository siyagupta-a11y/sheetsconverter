import base64
import re
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import get_credentials
from sheets_reader import read_spreadsheet, export_spreadsheet_xlsx
from formula_converter import convert_spreadsheet_formulas
from excel_builder import build_excel, patch_workbook_formulas
from convert_utils import (
    normalize_settings,
    should_block_by_policy,
    strict_mode_error_payload,
)
from model_lint import analyze_model_risk
from parity_report import build_parity_report
from value_compare import (
    source_formula_values,
    evaluate_excel_values,
    compare_formula_values,
    apply_mismatch_highlights,
)
from excel_formula_patcher import patch_uploaded_workbook

router = APIRouter()


def _extract_sheet_id(url: str):
    for pattern in [
        r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
        r'spreadsheetId=([a-zA-Z0-9-_]+)',
    ]:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    stripped = url.strip()
    if re.match(r'^[a-zA-Z0-9-_]{20,}$', stripped):
        return stripped
    return None


def _parse_critical_cells(items):
    result = []
    seen = set()
    for raw in items or []:
        for piece in re.split(r'[\n,]+', raw or ''):
            v = piece.strip()
            if not v:
                continue
            if v not in seen:
                seen.add(v)
                result.append(v)
    return result[:200]


class ConvertRequest(BaseModel):
    url: str
    strict: bool = False
    strict_policy: str = "off"
    profile: str = "balanced"
    build_mode: str = "internal"
    critical_cells: list[str] = []
    compare_values: bool = True
    highlight_mismatches: bool = True


@router.post("/convert-file")
async def convert_file(file: UploadFile = File(...)):
    filename = file.filename or "uploaded.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload a .xlsx file.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        converted_bytes, warnings = patch_uploaded_workbook(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process workbook: {e}")

    base_name = re.sub(r"\.xlsx$", "", filename, flags=re.IGNORECASE)
    safe_name = re.sub(r"[^\w\s-]", "", base_name).strip().replace(" ", "_") or "converted"
    out_name = f"{safe_name}_patched.xlsx"

    return JSONResponse(
        {
            "title": filename,
            "mode": "file_upload",
            "warnings": warnings,
            "warning_count": len(warnings),
            "file_b64": base64.b64encode(converted_bytes).decode(),
            "filename": out_name,
        }
    )


@router.post("/convert")
async def convert(request: Request, body: ConvertRequest):
    creds = get_credentials(request)
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated. Please sign in with Google.")

    sheet_id = _extract_sheet_id(body.url)
    if not sheet_id:
        raise HTTPException(status_code=400, detail="Could not parse a spreadsheet ID from that URL.")

    settings = normalize_settings(
        profile=body.profile,
        strict_policy=body.strict_policy,
        strict_bool=body.strict,
        build_mode=body.build_mode,
    )
    critical_cells = _parse_critical_cells(body.critical_cells)

    try:
        spreadsheet_data = read_spreadsheet(sheet_id, creds)
    except Exception as e:
        msg = str(e)
        if "403" in msg:
            raise HTTPException(
                status_code=403,
                detail="Permission denied. Make sure the spreadsheet is shared with your Google account.",
            )
        if "404" in msg:
            raise HTTPException(status_code=404, detail="Spreadsheet not found.")
        raise HTTPException(status_code=500, detail=f"Could not read spreadsheet: {msg}")

    converted_data, warnings = convert_spreadsheet_formulas(spreadsheet_data)
    risk_report = analyze_model_risk(spreadsheet_data, warnings, profile=settings["profile"])
    parity_report = build_parity_report(spreadsheet_data, warnings, risk_report, critical_cells)

    title = spreadsheet_data.get('properties', {}).get('title', 'spreadsheet')
    should_block, reason = should_block_by_policy(settings["strict_policy"], warnings, risk_report)
    if should_block:
        raise HTTPException(
            status_code=422,
            detail=strict_mode_error_payload(
                title=title,
                strict_policy=settings["strict_policy"],
                reason=reason,
                warnings=warnings,
                risk_report=risk_report,
            ),
        )

    build_meta = {"mode_requested": settings["build_mode"], "mode_used": "internal", "fallback_reason": ""}
    try:
        if settings["build_mode"] == "native_patch":
            native_bytes = export_spreadsheet_xlsx(sheet_id, creds)
            excel_bytes = patch_workbook_formulas(native_bytes, converted_data, warnings)
            build_meta["mode_used"] = "native_patch"
        else:
            excel_bytes = build_excel(converted_data, warnings)
            build_meta["mode_used"] = "internal"
    except Exception as e:
        # Graceful fallback for missing Drive scope / export incompatibility.
        excel_bytes = build_excel(converted_data, warnings)
        build_meta["mode_used"] = "internal"
        build_meta["fallback_reason"] = str(e)[:300]

    value_parity = {
        "enabled": bool(body.compare_values),
        "engine": "disabled",
        "checked_formula_cells": 0,
        "mismatch_count": 0,
        "mismatches_preview": [],
        "highlighted": False,
        "note": "",
    }
    if body.compare_values:
        source_vals = source_formula_values(spreadsheet_data)
        eval_result = evaluate_excel_values(excel_bytes)
        value_parity["engine"] = eval_result.get("engine", "unavailable")
        value_parity["note"] = eval_result.get("note", "")
        if eval_result.get("ok"):
            cmp = compare_formula_values(source_vals, eval_result.get("values", {}))
            mismatches = cmp.get("mismatches", [])
            value_parity["checked_formula_cells"] = cmp.get("checked_formula_cells", 0)
            value_parity["mismatch_count"] = cmp.get("mismatch_count", 0)
            value_parity["mismatches_preview"] = mismatches[:25]
            if body.highlight_mismatches and mismatches:
                excel_bytes = apply_mismatch_highlights(excel_bytes, mismatches)
                value_parity["highlighted"] = True

    safe_name = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_') or 'converted'
    filename = f"{safe_name}.xlsx"
    sheets = spreadsheet_data.get('sheets', [])

    return JSONResponse({
        "title": title,
        "sheet_count": len(sheets),
        "sheet_names": [s['properties']['title'] for s in sheets],
        "warnings": warnings,
        "warning_count": len(warnings),
        "risk_report": risk_report,
        "parity_report": parity_report,
        "settings": settings,
        "build": build_meta,
        "value_parity": value_parity,
        "file_b64": base64.b64encode(excel_bytes).decode(),
        "filename": filename,
    })
