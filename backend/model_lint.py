import re


VOLATILE_FUNCS = {"NOW", "TODAY", "RAND", "RANDBETWEEN", "OFFSET", "INDIRECT"}
HIGH_RISK_FUNCS = {"GOOGLEFINANCE", "QUERY", "IMPORTRANGE"}


def _col_to_letter(col: int) -> str:
    s = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return s


def _cell_ref(row_1based: int, col_1based: int) -> str:
    return f"{_col_to_letter(col_1based)}{row_1based}"


def _has_hardcoded_constant(formula: str) -> bool:
    # Strip quoted strings to avoid false positives.
    scrubbed = re.sub(r'"(?:[^"]|"")*"', "", formula)
    # Match numeric literals not part of A1 refs.
    return bool(re.search(r'(?<![A-Za-z\$])\d+(?:\.\d+)?(?![A-Za-z])', scrubbed))


def analyze_model_risk(spreadsheet_data: dict, warnings: list, profile: str = "balanced") -> dict:
    findings = []
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    formula_count = 0
    cross_sheet_refs = 0
    warning_cells = len({(w.get("sheet"), w.get("cell")) for w in warnings})

    for sheet in spreadsheet_data.get("sheets", []):
        sheet_title = sheet.get("properties", {}).get("title", "Sheet")
        for data_range in sheet.get("data", []):
            start_row = data_range.get("startRow", 0)
            start_col = data_range.get("startColumn", 0)
            for row_idx, row in enumerate(data_range.get("rowData", [])):
                for col_idx, cell in enumerate(row.get("values", [])):
                    formula = cell.get("userEnteredValue", {}).get("formulaValue")
                    if not formula:
                        continue
                    formula_count += 1
                    ref = _cell_ref(start_row + row_idx + 1, start_col + col_idx + 1)
                    f_upper = formula.upper()

                    for fn in VOLATILE_FUNCS:
                        if re.search(rf"\b{fn}\s*\(", f_upper):
                            findings.append({
                                "sheet": sheet_title,
                                "cell": ref,
                                "severity": "medium",
                                "rule": "volatile_function",
                                "message": f"Volatile function {fn} can change recalc behavior in financial models.",
                            })
                            severity_counts["medium"] += 1

                    for fn in HIGH_RISK_FUNCS:
                        if re.search(rf"\b{fn}\s*\(", f_upper):
                            findings.append({
                                "sheet": sheet_title,
                                "cell": ref,
                                "severity": "high",
                                "rule": "high_risk_function",
                                "message": f"High-risk function {fn} is not reliably portable to Excel.",
                            })
                            severity_counts["high"] += 1

                    if "!" in formula:
                        cross_sheet_refs += 1

                    if _has_hardcoded_constant(formula):
                        findings.append({
                            "sheet": sheet_title,
                            "cell": ref,
                            "severity": "low",
                            "rule": "hardcoded_constant",
                            "message": "Formula appears to include hardcoded numeric constants.",
                        })
                        severity_counts["low"] += 1

                    depth = formula.count("(")
                    if depth >= 7:
                        findings.append({
                            "sheet": sheet_title,
                            "cell": ref,
                            "severity": "medium",
                            "rule": "deep_formula_nesting",
                            "message": "Deeply nested formula may be fragile across engines.",
                        })
                        severity_counts["medium"] += 1

    if profile == "financial" and warning_cells > 0:
        severity_counts["medium"] += 1
        findings.append({
            "sheet": "",
            "cell": "",
            "severity": "medium",
            "rule": "conversion_warning_cells",
            "message": f"{warning_cells} formula cells produced converter warnings.",
        })

    score = 100
    score -= severity_counts["high"] * 12
    score -= severity_counts["medium"] * 4
    score -= severity_counts["low"] * 1
    score = max(0, score)

    summary = {
        "formula_cells": formula_count,
        "conversion_warning_cells": warning_cells,
        "cross_sheet_formula_count": cross_sheet_refs,
        "risk_score": score,
        "severity_counts": severity_counts,
    }

    return {
        "summary": summary,
        "severity_counts": severity_counts,
        "findings": findings,
    }
