import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from parity_report import build_parity_report


def _sheet(title, formula, effective_number=10):
    return {
        "properties": {"title": title},
        "data": [
            {
                "startRow": 0,
                "startColumn": 0,
                "rowData": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {"formulaValue": formula},
                                "effectiveValue": {"numberValue": effective_number},
                            }
                        ]
                    }
                ],
            }
        ],
    }


class ParityReportTests(unittest.TestCase):
    def test_warning_and_blocked_cells(self):
        data = {"sheets": [_sheet("Output", "=A1+1")]}
        warnings = [
            {
                "sheet": "Output",
                "cell": "A1",
                "original": "=A1+1",
                "converted": "=A1+1",
                "warnings": ["check"],
                "has_unsupported": False,
            }
        ]
        risk = {"severity_counts": {"high": 0}, "summary": {}, "findings": []}
        report = build_parity_report(data, warnings, risk, ["Output!A1"])
        self.assertEqual(report["overall_status"], "warning")
        self.assertEqual(report["summary"]["warning"], 1)

    def test_missing_cell(self):
        data = {"sheets": [_sheet("Output", "=A1+1")]}
        risk = {"severity_counts": {"high": 0}, "summary": {}, "findings": []}
        report = build_parity_report(data, [], risk, ["Output!B2"])
        self.assertEqual(report["summary"]["missing"], 1)


if __name__ == "__main__":
    unittest.main()
