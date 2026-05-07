VALID_STRICT_POLICIES = {"off", "all", "unsupported", "financial"}
VALID_PROFILES = {"balanced", "financial"}
VALID_BUILD_MODES = {"internal", "native_patch"}


def normalize_settings(profile: str, strict_policy: str, strict_bool: bool, build_mode: str) -> dict:
    p = (profile or "balanced").strip().lower()
    sp = (strict_policy or "off").strip().lower()
    bm = (build_mode or "internal").strip().lower()

    if p not in VALID_PROFILES:
        p = "balanced"
    if sp not in VALID_STRICT_POLICIES:
        sp = "off"
    if bm not in VALID_BUILD_MODES:
        bm = "internal"

    # Backward compatibility: old strict checkbox maps to strict-all.
    if strict_bool:
        sp = "all"

    return {"profile": p, "strict_policy": sp, "build_mode": bm}


def should_block_by_policy(strict_policy: str, warnings: list, risk_report: dict) -> tuple[bool, str]:
    warning_count = len(warnings)
    unsupported_count = sum(1 for w in warnings if w.get("has_unsupported"))
    high_count = int(risk_report.get("severity_counts", {}).get("high", 0))

    if strict_policy == "off":
        return False, ""
    if strict_policy == "all":
        if warning_count > 0:
            return True, "compatibility warnings were found"
        return False, ""
    if strict_policy == "unsupported":
        if unsupported_count > 0:
            return True, "unsupported functions were found"
        return False, ""
    if strict_policy == "financial":
        if unsupported_count > 0:
            return True, "unsupported functions were found"
        if high_count > 0:
            return True, "high-risk financial model findings were found"
        return False, ""
    return False, ""


def strict_mode_error_payload(
    *,
    title: str,
    strict_policy: str,
    reason: str,
    warnings: list,
    risk_report: dict,
) -> dict:
    warning_count = len(warnings)
    preview_warnings = warnings[:10]
    findings = risk_report.get("findings", [])
    preview_findings = findings[:10]
    return {
        "message": (
            f'Policy "{strict_policy}" blocked conversion for "{title}" because {reason}.'
        ),
        "strict_policy": strict_policy,
        "reason": reason,
        "warning_count": warning_count,
        "warnings": preview_warnings,
        "risk_summary": risk_report.get("summary", {}),
        "finding_count": len(findings),
        "findings": preview_findings,
    }
