import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from formula_converter import convert_formula


class FormulaConverterTests(unittest.TestCase):
    def test_array_constrain_converts_to_take(self):
        res = convert_formula("=ARRAY_CONSTRAIN(A1:D20,5,2)")
        self.assertEqual(res.formula, "=TAKE(A1:D20, 5, 2)")
        self.assertIn("ARRAY_CONSTRAIN → TAKE", " | ".join(res.warnings))

    def test_iferror_single_arg_gets_blank_fallback(self):
        res = convert_formula("=IFERROR(A1/B1)")
        self.assertEqual(res.formula, '=IFERROR(A1/B1, "")')
        self.assertIn("IFERROR: added second argument", " | ".join(res.warnings))
        self.assertFalse(res.has_unsupported)

    def test_iferror_two_args_unchanged(self):
        res = convert_formula('=IFERROR(A1/B1, "fallback")')
        self.assertEqual(res.formula, '=IFERROR(A1/B1, "fallback")')
        self.assertEqual(res.warnings, [])
        self.assertFalse(res.has_unsupported)

    def test_index_missing_row_is_preserved(self):
        res = convert_formula("=INDEX(A:C,,2)")
        self.assertEqual(res.formula, "=INDEX(A:C,,2)")
        self.assertIn("INDEX: omitted row argument detected", " | ".join(res.warnings))

    def test_index_missing_column_is_preserved(self):
        res = convert_formula("=INDEX(A:C,4,)")
        self.assertEqual(res.formula, "=INDEX(A:C,4,)")
        self.assertIn("INDEX: omitted column argument detected", " | ".join(res.warnings))

    def test_filter_single_condition_adds_if_empty_na(self):
        res = convert_formula("=FILTER(A2:A10,B2:B10>0)")
        self.assertEqual(res.formula, "=FILTER(A2:A10, B2:B10>0, NA())")
        self.assertIn("FILTER: added IF_EMPTY=NA()", " | ".join(res.warnings))

    def test_filter_multicondition_rewrite_and_if_empty_na(self):
        res = convert_formula('=FILTER(A2:C10,B2:B10>0,C2:C10="x")')
        self.assertEqual(res.formula, '=FILTER(A2:C10, (B2:B10>0)*(C2:C10="x"), NA())')
        all_warnings = " | ".join(res.warnings)
        self.assertIn("FILTER: 2 conditions combined with * (AND)", all_warnings)
        self.assertIn("FILTER: added IF_EMPTY=NA()", all_warnings)

    def test_split_defaults_preserved_for_ignore_empty(self):
        res = convert_formula('=SPLIT(A1,",")')
        self.assertEqual(res.formula, '=TEXTSPLIT(A1, ",", , TRUE)')
        self.assertIn("SPLIT → TEXTSPLIT", " | ".join(res.warnings))

    def test_split_with_remove_empty_false_maps_to_ignore_empty_false(self):
        res = convert_formula('=SPLIT(A1,",",TRUE,FALSE)')
        self.assertEqual(res.formula, '=TEXTSPLIT(A1, ",", , FALSE)')

    def test_split_multichar_delimiter_with_split_by_each_true_uses_array(self):
        res = convert_formula('=SPLIT(A1,"ab",TRUE,TRUE)')
        self.assertEqual(res.formula, '=TEXTSPLIT(A1, {"a","b"}, , TRUE)')
        self.assertIn("split_by_each=TRUE with multi-char delimiter", " | ".join(res.warnings))

    def test_sort_multi_key_converts_to_sortby(self):
        res = convert_formula("=SORT(B2:D10,2,TRUE,1,FALSE)")
        self.assertEqual(res.formula, "=SORTBY(B2:D10, C2:C10, 1, B2:B10, -1)")
        self.assertIn("SORT with 2 keys → SORTBY", " | ".join(res.warnings))

    def test_lookup_defaults_emit_compatibility_warning(self):
        res = convert_formula("=VLOOKUP(A2,Data!A:C,3)")
        self.assertEqual(res.formula, "=VLOOKUP(A2,Data!A:C,3)")
        self.assertIn("VLOOKUP: default match mode is implicit", " | ".join(res.warnings))

        res2 = convert_formula("=MATCH(A1,B:B)")
        self.assertEqual(res2.formula, "=MATCH(A1,B:B)")
        self.assertIn("MATCH: default match_type is implicit", " | ".join(res2.warnings))

    def test_unsupported_function_is_flagged_and_left_intact(self):
        res = convert_formula('=QUERY(A1:B10,"select A")')
        self.assertEqual(res.formula, '=QUERY(A1:B10,"select A")')
        self.assertTrue(res.has_unsupported)
        self.assertIn("QUERY", " | ".join(res.warnings))


if __name__ == "__main__":
    unittest.main()
