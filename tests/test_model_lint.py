import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from model_lint import analyze_model_risk


def _sheet_with_formula(sheet_title: str, formula: str):
    return {
        "properties": {"title": sheet_title},
        "data": [
            {
                "startRow": 0,
                "startColumn": 0,
                "rowData": [{"values": [{"userEnteredValue": {"formulaValue": formula}}]}],
            }
        ],
    }


class ModelLintTests(unittest.TestCase):
    def test_flags_volatile_and_constants(self):
        data = {"sheets": [_sheet_with_formula("Model", "=NOW()+100")]}
        report = analyze_model_risk(data, [], profile="financial")
        self.assertGreaterEqual(report["summary"]["formula_cells"], 1)
        self.assertGreaterEqual(report["severity_counts"]["medium"], 1)
        self.assertGreaterEqual(report["severity_counts"]["low"], 1)

    def test_high_risk_function(self):
        data = {"sheets": [_sheet_with_formula("Model", '=QUERY(A1:B10,"select A")')]}
        report = analyze_model_risk(data, [], profile="balanced")
        self.assertGreaterEqual(report["severity_counts"]["high"], 1)


if __name__ == "__main__":
    unittest.main()
