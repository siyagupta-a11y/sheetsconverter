import re
from dataclasses import dataclass, field


@dataclass
class ConversionResult:
    formula: str
    warnings: list = field(default_factory=list)
    has_unsupported: bool = False


UNSUPPORTED_FUNCTIONS = {
    'GOOGLEFINANCE': 'Fetches financial data from Google — no Excel equivalent',
    'IMPORTRANGE': 'Links to an external Google Sheet — no Excel equivalent',
    'IMPORTDATA': 'Imports CSV/TSV from a URL — no Excel equivalent',
    'IMPORTFEED': 'Imports RSS/Atom feeds — no Excel equivalent',
    'IMPORTHTML': 'Imports HTML tables from a URL — no Excel equivalent',
    'IMPORTXML': 'Imports XML data from a URL — no Excel equivalent',
    'QUERY': 'SQL-like query language — no Excel equivalent',
    'SPARKLINE': 'Inline sparkline chart — no Excel equivalent',
    'IMAGE': 'Embeds an image from a URL — no Excel equivalent',
    'DETECTLANGUAGE': 'Uses Google Translate API — no Excel equivalent',
    'GOOGLETRANSLATE': 'Uses Google Translate API — no Excel equivalent',
    'ISURL': 'Checks if value is a URL — no Excel equivalent',
    'ISEMAIL': 'Checks if value is an email address — no Excel equivalent',
    'REGEXMATCH': 'Regex matching — no Excel equivalent (consider ISNUMBER(SEARCH(...)))',
    'REGEXREPLACE': 'Regex replacement — no Excel equivalent',
    'REGEXEXTRACT': 'Regex extraction — no Excel equivalent',
}


def _find_matching_paren(s: str, open_pos: int) -> int:
    """Return index of the closing paren matching the one at open_pos."""
    depth = 1
    in_str = False
    i = open_pos + 1
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_nth_comma(s: str, open_pos: int, n: int = 1) -> int:
    """Return index of the nth top-level comma inside parens starting at open_pos."""
    depth = 1
    in_str = False
    count = 0
    i = open_pos + 1
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return -1
        elif c == ',' and depth == 1:
            count += 1
            if count == n:
                return i
        i += 1
    return -1


def _split_top_level_args(s: str, open_pos: int) -> list:
    """Return a list of top-level argument strings for the call whose '(' is at open_pos."""
    args = []
    depth = 1
    in_str = False
    start = open_pos + 1
    i = open_pos + 1
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                args.append(s[start:i])
                break
        elif c == ',' and depth == 1:
            args.append(s[start:i])
            start = i + 1
        i += 1
    return args


def _convert_arrayformula(formula: str) -> tuple:
    warnings = []
    pattern = re.compile(r'\bARRAYFORMULA\s*\(', re.IGNORECASE)

    result = formula
    found = 0
    while True:
        m = pattern.search(result)
        if not m:
            break
        open_p = m.end() - 1
        close_p = _find_matching_paren(result, open_p)
        if close_p == -1:
            break
        inner = result[m.end():close_p]
        result = result[:m.start()] + inner + result[close_p + 1:]
        found += 1

    if found:
        warnings.append(
            "ARRAYFORMULA removed — Excel 365 handles dynamic arrays natively. "
            "In older Excel, re-enter the formula with Ctrl+Shift+Enter."
        )
    return result, warnings


def _convert_continue(formula: str) -> tuple:
    if re.search(r'\bCONTINUE\s*\(', formula, re.IGNORECASE):
        return '', ["CONTINUE formula cleared — Excel 365 fills spilled array cells automatically."]
    return formula, []


def _convert_join(formula: str) -> tuple:
    """JOIN(delim, ...) → TEXTJOIN(delim, TRUE, ...)"""
    warnings = []
    pattern = re.compile(r'\bJOIN\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        if m.start() < pos:
            continue
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        comma1 = _find_nth_comma(formula, open_p, 1)
        close_p = _find_matching_paren(formula, open_p)

        if comma1 != -1 and close_p != -1:
            delim = formula[m.end():comma1]
            rest = formula[comma1 + 1:close_p].strip()
            parts.append(f'TEXTJOIN({delim}, TRUE, {rest})')
            pos = close_p + 1
        elif close_p != -1:
            arg = formula[m.end():close_p]
            parts.append(f'TEXTJOIN({arg}, TRUE)')
            pos = close_p + 1
        else:
            parts.append('TEXTJOIN(')
            pos = m.end()

        warnings.append("JOIN → TEXTJOIN (TRUE inserted as ignore_empty argument)")

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _convert_split(formula: str) -> tuple:
    """
    Google: SPLIT(text, delimiter, [split_by_each], [remove_empty_text])
    Excel:  TEXTSPLIT(text, col_delimiter, [row_delimiter], [ignore_empty], ...)

    Notes:
    - Sheets defaults remove_empty_text=TRUE, while Excel defaults ignore_empty=FALSE.
      We always pass ignore_empty to preserve Sheets behavior.
    - split_by_each=TRUE with a multi-char string delimiter is approximated by turning
      the delimiter into a character array constant for TEXTSPLIT.
    """
    warnings = []
    pattern = re.compile(r'\bSPLIT\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    def _is_true_literal(s: str) -> bool:
        v = s.strip().upper()
        return v in ('TRUE', '1')

    def _is_false_literal(s: str) -> bool:
        v = s.strip().upper()
        return v in ('FALSE', '0')

    def _chars_array_constant(s: str) -> str:
        inner = s[1:-1]  # remove outer quotes
        chars = []
        i = 0
        while i < len(inner):
            c = inner[i]
            if c == '"' and i + 1 < len(inner) and inner[i + 1] == '"':
                chars.append('"')
                i += 2
            else:
                chars.append(c)
                i += 1
        return "{" + ",".join(f'"{ch.replace(chr(34), chr(34) * 2)}"' for ch in chars) + "}"

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        if m.start() < pos:
            continue
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)

        if close_p == -1:
            parts.append(formula[m.start():])
            pos = len(formula)
            continue

        args = _split_top_level_args(formula, open_p)
        if len(args) < 2:
            parts.append(formula[m.start():close_p + 1])
            warnings.append("SPLIT: unexpected argument count — verify manually")
            pos = close_p + 1
            continue

        text_arg = args[0].strip()
        delim_arg = args[1].strip()
        split_by_each_arg = args[2].strip() if len(args) >= 3 else 'TRUE'
        remove_empty_arg = args[3].strip() if len(args) >= 4 else 'TRUE'

        if _is_true_literal(split_by_each_arg):
            # If delimiter is a multi-char string literal, emulate character-wise split.
            if re.match(r'^".*"$', delim_arg) and len(delim_arg) >= 4:
                delim_arg = _chars_array_constant(delim_arg)
                warnings.append(
                    "SPLIT: split_by_each=TRUE with multi-char delimiter mapped to TEXTSPLIT delimiter array"
                )
        elif not _is_false_literal(split_by_each_arg):
            warnings.append(
                "SPLIT: dynamic split_by_each expression may not map exactly to TEXTSPLIT semantics"
            )

        # Preserve Sheets default remove_empty_text=TRUE by passing ignore_empty explicitly.
        parts.append(f'TEXTSPLIT({text_arg}, {delim_arg}, , {remove_empty_arg})')
        warnings.append("SPLIT → TEXTSPLIT — mapped remove_empty_text to ignore_empty (Excel 365 required)")

        pos = close_p + 1

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _convert_countunique(formula: str) -> tuple:
    """COUNTUNIQUE(range) → COUNTA(UNIQUE(range))"""
    warnings = []
    pattern = re.compile(r'\bCOUNTUNIQUE\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        if m.start() < pos:
            continue
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)
        if close_p != -1:
            inner = formula[m.end():close_p]
            parts.append(f'COUNTA(UNIQUE({inner}))')
            pos = close_p + 1
            warnings.append("COUNTUNIQUE → COUNTA(UNIQUE(...)) — requires Excel 365")
        else:
            parts.append(formula[m.end():])
            pos = len(formula)

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _convert_array_constrain(formula: str) -> tuple:
    """
    ARRAY_CONSTRAIN(range, rows, cols) → TAKE(range, rows, cols)
    (Excel 365 required)
    """
    warnings = []
    pattern = re.compile(r'\bARRAY_CONSTRAIN\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)
        if close_p == -1:
            parts.append(formula[m.start():])
            pos = len(formula)
            continue

        args = _split_top_level_args(formula, open_p)
        if len(args) == 3:
            range_arg = args[0].strip()
            rows_arg = args[1].strip()
            cols_arg = args[2].strip()
            parts.append(f'TAKE({range_arg}, {rows_arg}, {cols_arg})')
            warnings.append("ARRAY_CONSTRAIN → TAKE (Excel 365 required)")
        else:
            parts.append(formula[m.start():close_p + 1])
            warnings.append("ARRAY_CONSTRAIN: unexpected argument count — verify manually")

        pos = close_p + 1

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _convert_filter_multicondition(formula: str) -> tuple:
    """
    FILTER(range, cond1, cond2, ...) → FILTER(range, (cond1)*(cond2)*..., NA())

    In Google Sheets multiple conditions are implicitly ANDed.
    In Excel, FILTER takes a single boolean array — conditions must be multiplied together.
    Also append IF_EMPTY=NA() so empty results match Sheets (#N/A instead of #CALC!).
    Rewrites all FILTER calls.
    """
    warnings = []
    pattern = re.compile(r'\bFILTER\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)

        if close_p == -1:
            parts.append(formula[m.start():])
            pos = len(formula)
            continue

        args = _split_top_level_args(formula, open_p)

        if len(args) >= 3:
            range_arg = args[0].strip()
            conditions = [a.strip() for a in args[1:]]
            combined = '*'.join(f'({c})' for c in conditions)
            parts.append(f'FILTER({range_arg}, {combined}, NA())')
            warnings.append(
                f"FILTER: {len(conditions)} conditions combined with * (AND) — "
                "Excel FILTER requires a single boolean array; use * for AND, + for OR"
            )
            warnings.append(
                "FILTER: added IF_EMPTY=NA() so empty results stay #N/A (Sheets-compatible)"
            )
        elif len(args) == 2:
            range_arg = args[0].strip()
            condition = args[1].strip()
            parts.append(f'FILTER({range_arg}, {condition}, NA())')
            warnings.append(
                "FILTER: added IF_EMPTY=NA() so empty results stay #N/A (Sheets-compatible)"
            )
        else:
            parts.append(formula[m.start():close_p + 1])

        pos = close_p + 1

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _col_letter_to_num(col: str) -> int:
    n = 0
    for c in col.upper():
        n = n * 26 + (ord(c) - 64)
    return n


def _num_to_col_letter(n: int) -> str:
    result = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _parse_a1_range(range_str: str):
    """
    Parse an A1-notation range into components.
    Handles Sheet1!A1:C10, 'My Sheet'!A:C, $A$1:$C$10, etc.
    Returns None if the string doesn't look like a plain cell range.
    """
    s = range_str.strip()

    # Optional sheet prefix:  Sheet1!  or  'Sheet Name'!
    sheet_prefix = ''
    m = re.match(r"^(?:'[^']+'|[\w\\.]+)!", s)
    if m:
        sheet_prefix = m.group(0)
        s = s[len(sheet_prefix):]

    # COL[ROW]:COL[ROW]  (with optional $ anchors)
    m = re.match(r'^(\$?[A-Za-z]{1,3})(\$?\d+)?:(\$?[A-Za-z]{1,3})(\$?\d+)?$', s)
    if not m:
        return None

    return {
        'prefix': sheet_prefix,
        'start_col': m.group(1).replace('$', '').upper(),
        'start_row': m.group(2).replace('$', '') if m.group(2) else None,
        'end_col': m.group(3).replace('$', '').upper(),
        'end_row': m.group(4).replace('$', '') if m.group(4) else None,
    }


def _nth_col_of_range(range_str: str, n: int):
    """
    Return the nth column (1-based, relative to the range) as a single-column range.
    E.g. _nth_col_of_range("B2:D10", 2) → "C2:C10"
    Returns None if range_str can't be parsed as A1 notation.
    """
    p = _parse_a1_range(range_str)
    if p is None:
        return None
    col_num = _col_letter_to_num(p['start_col']) + n - 1
    col = _num_to_col_letter(col_num)
    pfx = p['prefix']
    if p['start_row'] and p['end_row']:
        return f"{pfx}{col}{p['start_row']}:{col}{p['end_row']}"
    else:
        return f"{pfx}{col}:{col}"


def _to_excel_sort_order(val: str) -> str:
    """Convert Google Sheets is_ascending (TRUE/FALSE/1/0) to Excel sort_order (1/-1)."""
    v = val.strip().upper()
    if v in ('TRUE', '1'):
        return '1'
    if v in ('FALSE', '0'):
        return '-1'
    return val  # cell reference or expression — leave as-is


def _convert_sort(formula: str) -> tuple:
    """
    Single-key SORT: fix TRUE/FALSE sort order → 1/-1 for Excel.
    Multi-key SORT: convert to SORTBY with explicit column ranges when the
    first argument is a parseable A1-notation range; warn otherwise.

    Google:  SORT(range, col1, asc1, col2, asc2, ...)
    Excel:   SORTBY(range, col1_range, order1, col2_range, order2, ...)
    """
    warnings = []
    pattern = re.compile(r'\bSORT\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)

        if close_p == -1:
            parts.append(formula[m.start():])
            pos = len(formula)
            continue

        args = _split_top_level_args(formula, open_p)

        if len(args) <= 2:
            # SORT(range) or SORT(range, col) — compatible as-is
            parts.append(formula[m.start():close_p + 1])

        elif len(args) == 3:
            # Single key: fix order arg
            range_arg, col_arg, order_arg = args
            order = _to_excel_sort_order(order_arg)
            if order != order_arg.strip():
                parts.append(f'SORT({range_arg}, {col_arg}, {order})')
                warnings.append("SORT: is_ascending TRUE/FALSE converted to 1/-1 for Excel")
            else:
                parts.append(formula[m.start():close_p + 1])

        elif (len(args) - 1) % 2 == 0:
            # Multi-key: args = [range, col1, asc1, col2, asc2, ...]
            range_arg = args[0].strip()
            pairs = [(args[i].strip(), args[i + 1].strip()) for i in range(1, len(args), 2)]

            sortby_parts = [range_arg]
            failed = False
            for col_idx_str, order_str in pairs:
                try:
                    n = int(col_idx_str)
                except ValueError:
                    # col index is an expression, not a literal — can't auto-convert
                    failed = True
                    break
                col_range = _nth_col_of_range(range_arg, n)
                if col_range is None:
                    failed = True
                    break
                sortby_parts.append(col_range)
                sortby_parts.append(_to_excel_sort_order(order_str))

            if not failed:
                parts.append(f'SORTBY({", ".join(sortby_parts)})')
                warnings.append(
                    f"SORT with {len(pairs)} keys → SORTBY — "
                    "column indices resolved to explicit column ranges"
                )
            else:
                parts.append(formula[m.start():close_p + 1])
                warnings.append(
                    "SORT with multiple sort keys: range could not be parsed automatically "
                    "(named range or expression). Replace manually with "
                    "SORTBY(array, by_col1, order1, by_col2, order2, ...)"
                )

        else:
            parts.append(formula[m.start():close_p + 1])
            warnings.append("SORT: unexpected argument count — verify manually")

        pos = close_p + 1

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _convert_to_text(formula: str) -> tuple:
    warnings = []
    if re.search(r'\bTO_PURE_TEXT\s*\(', formula, re.IGNORECASE):
        formula = re.sub(r'\bTO_PURE_TEXT\s*\(', 'TEXT(', formula, flags=re.IGNORECASE)
        warnings.append('TO_PURE_TEXT → TEXT — add a format string as the second argument (e.g. TEXT(A1,"@"))')
    if re.search(r'\bTO_TEXT\s*\(', formula, re.IGNORECASE):
        formula = re.sub(r'\bTO_TEXT\s*\(', 'TEXT(', formula, flags=re.IGNORECASE)
        warnings.append('TO_TEXT → TEXT — add a format string as the second argument (e.g. TEXT(A1,"@"))')
    return formula, warnings


def _strip_implicit_intersection_prefix(formula: str) -> tuple:
    """
    Remove explicit implicit-intersection prefixes like @IF(...).
    These can appear in modern Excel displays but are not needed for scalar
    functions and can trigger #NAME? in some interoperability scenarios.
    """
    warnings = []
    pattern = re.compile(r'@([A-Za-z_][A-Za-z0-9_]*)\s*\(')
    if not pattern.search(formula):
        return formula, warnings

    removed = 0
    def repl(m):
        nonlocal removed
        removed += 1
        return f'{m.group(1)}('

    out = pattern.sub(repl, formula)
    if removed:
        warnings.append("Removed @ implicit-intersection prefixes for compatibility")
    return out, warnings


def _convert_iferror(formula: str) -> tuple:
    """
    Google Sheets: IFERROR(value) defaults value_if_error to blank.
    Excel: IFERROR(value, value_if_error) requires the second argument.
    """
    warnings = []
    pattern = re.compile(r'\bIFERROR\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)

        if close_p == -1:
            parts.append(formula[m.start():])
            pos = len(formula)
            continue

        args = _split_top_level_args(formula, open_p)
        if len(args) == 1:
            value = args[0].strip()
            parts.append(f'IFERROR({value}, "")')
            warnings.append('IFERROR: added second argument "" for Excel compatibility')
        else:
            parts.append(formula[m.start():close_p + 1])

        pos = close_p + 1

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _convert_index_defaults(formula: str) -> tuple:
    """
    Normalize INDEX for Sheets-vs-Excel argument semantics.

    Key drift we handle:
    - Sheets models often use INDEX(ref, n) against a horizontal/single-row ref
      (treating n as column offset). In Excel this is interpreted as row_num and
      can return #REF! when n > 1.
    - For references that look like single-row ranges, rewrite:
        INDEX(ref, n) -> INDEX(ref, 1, n)

    For omitted-position cases (",," or trailing comma), keep unchanged and warn.
    """
    warnings = []
    pattern = re.compile(r'\bINDEX\s*\(', re.IGNORECASE)
    if not pattern.search(formula):
        return formula, warnings

    def _looks_like_single_row_ref(ref_arg: str) -> bool:
        s = ref_arg.strip()

        # Explicit row-range references, e.g. 9:9 or Sheet!9:9.
        if re.search(r'(^|[^A-Za-z0-9_])\$?\d+\s*:\s*\$?\d+($|[^A-Za-z0-9_])', s):
            return True

        # Dynamic right-bound built from a row-range INDEX(..., 9:9, ...).
        if re.search(r':\s*INDEX\([^)]*\$?\d+\s*:\s*\$?\d+', s, re.IGNORECASE):
            return True

        # Simple A1-style one-row ranges, e.g. B9:J9 or 'P&L'!$B$9:$J$9.
        m = re.match(
            r"^(?:'[^']+'!|[\w\\.]+!)?\$?[A-Za-z]{1,3}\$?(\d+)\s*:\s*"
            r"(?:'[^']+'!|[\w\\.]+!)?\$?[A-Za-z]{1,3}\$?(\d+)$",
            s,
        )
        if m and m.group(1) == m.group(2):
            return True

        return False

    def _looks_like_single_col_ref(ref_arg: str) -> bool:
        s = ref_arg.strip()

        # Explicit column-range references, e.g. B:B or Sheet!$B:$B.
        if re.search(r'(^|[^A-Za-z0-9_])\$?[A-Za-z]{1,3}\s*:\s*\$?[A-Za-z]{1,3}($|[^A-Za-z0-9_])', s):
            return True

        # Simple A1-style one-column ranges, e.g. B2:B100.
        m = re.match(
            r"^(?:'[^']+'!|[\w\\.]+!)?\$?([A-Za-z]{1,3})\$?\d*\s*:\s*"
            r"(?:'[^']+'!|[\w\\.]+!)?\$?([A-Za-z]{1,3})\$?\d*$",
            s,
        )
        if m and m.group(1).upper() == m.group(2).upper():
            return True

        return False
    parts = []
    pos = 0
    for m in pattern.finditer(formula):
        if m.start() < pos:
            continue
        parts.append(formula[pos:m.start()])
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)
        if close_p == -1:
            parts.append(formula[m.start():])
            pos = len(formula)
            continue

        args = _split_top_level_args(formula, open_p)
        if len(args) == 2:
            ref = args[0].strip()
            idx = args[1].strip()

            # Recursively normalize nested INDEX calls inside arguments first.
            ref_conv, ref_w = _convert_index_defaults(ref)
            idx_conv, idx_w = _convert_index_defaults(idx)
            warnings.extend(ref_w)
            warnings.extend(idx_w)
            ref = ref_conv
            idx = idx_conv

            if _looks_like_single_row_ref(ref):
                parts.append(f'INDEX({ref}, 1, {idx})')
                warnings.append(
                    "INDEX: two-arg call over single-row reference rewritten to INDEX(ref,1,col)"
                )
            elif _looks_like_single_col_ref(ref):
                parts.append(formula[m.start():close_p + 1])
            else:
                parts.append(formula[m.start():close_p + 1])
                warnings.append(
                    "INDEX: two-arg call left unchanged (reference orientation ambiguous)"
                )
        else:
            if len(args) >= 2 and args[1].strip() == '':
                warnings.append(
                    "INDEX: omitted row argument detected; kept unchanged to preserve Sheets behavior"
                )
            if len(args) >= 3 and args[2].strip() == '':
                warnings.append(
                    "INDEX: omitted column argument detected; kept unchanged to preserve Sheets behavior"
                )
            parts.append(formula[m.start():close_p + 1])

        pos = close_p + 1

    parts.append(formula[pos:])
    return ''.join(parts), warnings


def _warn_lookup_defaults(formula: str) -> tuple:
    """
    Warn when lookup defaults are implicit, because these are high-risk for
    semantic drift after migration.
    """
    warnings = []
    pattern = re.compile(r'\b(VLOOKUP|HLOOKUP|MATCH)\s*\(', re.IGNORECASE)
    for m in pattern.finditer(formula):
        fn = m.group(1).upper()
        open_p = m.end() - 1
        close_p = _find_matching_paren(formula, open_p)
        if close_p == -1:
            continue

        args = _split_top_level_args(formula, open_p)
        if fn in ('VLOOKUP', 'HLOOKUP') and len(args) == 3:
            warnings.append(
                f"{fn}: default match mode is implicit; set the last argument explicitly (FALSE for exact, TRUE for approximate)"
            )
        elif fn == 'MATCH' and len(args) == 2:
            warnings.append(
                "MATCH: default match_type is implicit; set it explicitly (0 exact, 1/-1 approximate)"
            )

    return formula, warnings


def convert_formula(formula: str) -> ConversionResult:
    if not formula or not formula.startswith('='):
        return ConversionResult(formula=formula)

    # CONTINUE cells should be cleared entirely
    result, w = _convert_continue(formula)
    if w:
        return ConversionResult(formula=result, warnings=w, has_unsupported=False)

    warnings = []
    has_unsupported = False

    # Flag unsupported functions (keep formula as a visible stub)
    for func, reason in UNSUPPORTED_FUNCTIONS.items():
        if re.search(rf'\b{func}\s*\(', formula, re.IGNORECASE):
            warnings.append(f"⚠ {func}: {reason}")
            has_unsupported = True

    if has_unsupported:
        return ConversionResult(formula=formula, warnings=warnings, has_unsupported=True)

    result = formula
    for converter in [
        _convert_arrayformula,
        _convert_array_constrain,
        _strip_implicit_intersection_prefix,
        _convert_iferror,
        _convert_join,
        _convert_split,
        _convert_countunique,
        _convert_to_text,
        _convert_index_defaults,
        _convert_filter_multicondition,
        _convert_sort,
        _warn_lookup_defaults,
    ]:
        result, w = converter(result)
        warnings.extend(w)

    return ConversionResult(formula=result, warnings=warnings, has_unsupported=False)


def col_to_letter(col: int) -> str:
    result = ''
    while col > 0:
        col, rem = divmod(col - 1, 26)
        result = chr(65 + rem) + result
    return result


def convert_spreadsheet_formulas(spreadsheet_data: dict) -> tuple:
    """Convert all formulas in-place (on a deep copy). Returns (data, warnings)."""
    import copy
    data = copy.deepcopy(spreadsheet_data)
    all_warnings = []

    for sheet in data.get('sheets', []):
        sheet_title = sheet['properties']['title']

        for data_range in sheet.get('data', []):
            start_row = data_range.get('startRow', 0)
            start_col = data_range.get('startColumn', 0)

            for row_idx, row in enumerate(data_range.get('rowData', [])):
                for col_idx, cell in enumerate(row.get('values', [])):
                    uev = cell.get('userEnteredValue', {})
                    if 'formulaValue' not in uev:
                        continue

                    original = uev['formulaValue']
                    res = convert_formula(original)

                    abs_row = start_row + row_idx + 1
                    abs_col = start_col + col_idx + 1
                    cell_ref = f"{col_to_letter(abs_col)}{abs_row}"

                    if res.formula == '':
                        cell['userEnteredValue'] = {}
                    else:
                        uev['formulaValue'] = res.formula

                    if res.warnings:
                        all_warnings.append({
                            'sheet': sheet_title,
                            'cell': cell_ref,
                            'original': original,
                            'converted': res.formula,
                            'warnings': res.warnings,
                            'has_unsupported': res.has_unsupported,
                        })

    return data, all_warnings
