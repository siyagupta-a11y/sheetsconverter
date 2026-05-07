import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from convert_utils import (
    normalize_settings,
    should_block_by_policy,
    strict_mode_error_payload,
)


class ConvertUtilsTests(unittest.TestCase):
    def test_normalize_settings_legacy_strict_overrides_policy(self):
        s = normalize_settings("balanced", "off", True, "internal")
        self.assertEqual(s["strict_policy"], "all")
        self.assertEqual(s["profile"], "balanced")

    def test_policy_off_never_blocks(self):
        block, reason = should_block_by_policy("off", [{"a": 1}], {"severity_counts": {"high": 5}})
        self.assertFalse(block)
        self.assertEqual(reason, "")

    def test_policy_unsupported_blocks_only_unsupported(self):
        block, _ = should_block_by_policy("unsupported", [{"has_unsupported": False}], {"severity_counts": {"high": 0}})
        self.assertFalse(block)
        block2, reason2 = should_block_by_policy(
            "unsupported",
            [{"has_unsupported": True}],
            {"severity_counts": {"high": 0}},
        )
        self.assertTrue(block2)
        self.assertIn("unsupported", reason2)

    def test_policy_financial_blocks_high_risk(self):
        block, reason = should_block_by_policy("financial", [], {"severity_counts": {"high": 1}})
        self.assertTrue(block)
        self.assertIn("high-risk", reason)

    def test_strict_mode_payload_shapes(self):
        payload = strict_mode_error_payload(
            title="Budget",
            strict_policy="financial",
            reason="high-risk findings were found",
            warnings=[{"cell": "A1"} for _ in range(12)],
            risk_report={"summary": {"risk_score": 42}, "findings": [{"rule": "x"} for _ in range(11)]},
        )
        self.assertIn('Policy "financial" blocked conversion for "Budget"', payload["message"])
        self.assertEqual(payload["warning_count"], 12)
        self.assertEqual(len(payload["warnings"]), 10)
        self.assertEqual(payload["finding_count"], 11)
        self.assertEqual(len(payload["findings"]), 10)


if __name__ == "__main__":
    unittest.main()
