import re


def _col_to_letter(col: int) -> str:
    s = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return s


def _build_cell_map(spreadsheet_data: dict) -> dict:
    cell_map = {}
    for sheet in spreadsheet_data.get("sheets", []):
        sheet_title = sheet.get("properties", {}).get("title", "Sheet")
        for data_range in sheet.get("data", []):
            start_row = data_range.get("startRow", 0)
            start_col = data_range.get("startColumn", 0)
            for row_idx, row in enumerate(data_range.get("rowData", [])):
                for col_idx, cell in enumerate(row.get("values", [])):
                    row_1 = start_row + row_idx + 1
                    col_1 = start_col + col_idx + 1
                    ref = f"{_col_to_letter(col_1)}{row_1}"
                    key = f"{sheet_title}!{ref}"
                    cell_map[key] = cell
    return cell_map


def _normalize_ref(raw: str, default_sheet: str):
    s = (raw or "").strip()
    if not s:
        return None
    if "!" in s:
        left, right = s.split("!", 1)
        sheet = left.strip().strip("'")
        cell = right.strip().replace("$", "").upper()
        return f"{sheet}!{cell}"
    cell = s.replace("$", "").upper()
    if not re.match(r"^[A-Z]{1,3}\d+$", cell):
        return None
    return f"{default_sheet}!{cell}"


def _value_from_effective(effective: dict):
    if not effective:
        return None
    for k in ("numberValue", "stringValue", "boolValue", "errorValue"):
        if k in effective:
            return effective[k]
    return None


def build_parity_report(
    spreadsheet_data: dict,
    warnings: list,
    risk_report: dict,
    critical_cells,
) -> dict:
    sheets = spreadsheet_data.get("sheets", [])
    default_sheet = sheets[0].get("properties", {}).get("title", "Sheet1") if sheets else "Sheet1"
    refs = [_normalize_ref(c, default_sheet) for c in (critical_cells or [])]
    refs = [r for r in refs if r]

    warning_map = {(w.get("sheet"), w.get("cell")): w for w in warnings}
    cells = _build_cell_map(spreadsheet_data)

    checks = []
    counts = {"ok": 0, "warning": 0, "blocked": 0, "missing": 0}
    for ref in refs:
        sheet, cell_ref = ref.split("!", 1)
        row = {
            "ref": ref,
            "status": "ok",
            "reason": "",
            "original_formula": None,
            "converted_formula": None,
            "source_value": None,
        }
        cell = cells.get(ref)
        if not cell:
            row["status"] = "missing"
            row["reason"] = "Cell was not found in fetched grid data."
            counts["missing"] += 1
            checks.append(row)
            continue

        uev = cell.get("userEnteredValue", {})
        original_formula = uev.get("formulaValue")
        effective_value = _value_from_effective(cell.get("effectiveValue", {}))
        row["original_formula"] = original_formula
        row["source_value"] = effective_value

        w = warning_map.get((sheet, cell_ref))
        if w:
            row["converted_formula"] = w.get("converted")
            if w.get("has_unsupported"):
                row["status"] = "blocked"
                row["reason"] = "Unsupported function in critical cell."
            else:
                row["status"] = "warning"
                row["reason"] = "; ".join(w.get("warnings", []))
        else:
            row["converted_formula"] = original_formula

        if row["status"] == "ok":
            counts["ok"] += 1
        elif row["status"] == "warning":
            counts["warning"] += 1
        elif row["status"] == "blocked":
            counts["blocked"] += 1
        checks.append(row)

    high_findings = int(risk_report.get("severity_counts", {}).get("high", 0))
    overall = "pass"
    if counts["blocked"] > 0:
        overall = "blocked"
    elif counts["warning"] > 0 or high_findings > 0:
        overall = "warning"

    return {
        "overall_status": overall,
        "engine": "static-source-parity",
        "summary": {
            "critical_count": len(refs),
            "ok": counts["ok"],
            "warning": counts["warning"],
            "blocked": counts["blocked"],
            "missing": counts["missing"],
            "high_risk_findings": high_findings,
        },
        "checks": checks,
    }
