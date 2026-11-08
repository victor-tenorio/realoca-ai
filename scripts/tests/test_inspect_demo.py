import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspect_demo import inspect, validate_base


class DemoInspectorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        self.data = {
            "http://127.0.0.1:8001/api/v1/cases": {
                "cases": [{"case_id": "case-real", "status": "open"}]
            },
            "http://127.0.0.1:8001/api/v1/cases/case-real": {
                "status": "open", "pending_approvals": [],
                "proposals": [{
                    "attempt_id": "att-real", "status": "notified",
                    "approval_decision": None,
                    "response_deadline_at": "2026-11-08T14:00:00Z"
                }]
            },
        }

    def test_finds_notified_real_attempt_with_time_left(self):
        report = inspect("http://127.0.0.1:8001", getter=self.data.__getitem__, now=self.now)
        self.assertEqual(report["ready_offers"], 1)
        self.assertEqual(report["shown_cases"][0]["offers"][0]["attempt_id"], "att-real")

    def test_expired_or_reserved_not_ready(self):
        offer = self.data["http://127.0.0.1:8001/api/v1/cases/case-real"]["proposals"][0]
        offer["response_deadline_at"] = "2026-11-08T11:59:00Z"
        self.assertEqual(inspect("http://127.0.0.1:8001", getter=self.data.__getitem__, now=self.now)["ready_offers"], 0)
        offer["response_deadline_at"] = "2026-11-08T14:00:00Z"
        offer["status"] = "reserved"
        self.assertEqual(inspect("http://127.0.0.1:8001", getter=self.data.__getitem__, now=self.now)["ready_offers"], 0)

    def test_no_case_safe(self):
        self.data["http://127.0.0.1:8001/api/v1/cases"]["cases"] = []
        result = inspect("http://127.0.0.1:8001", getter=self.data.__getitem__, now=self.now)
        self.assertEqual(result["shown_cases"], [])
        self.assertEqual(result["ready_offers"], 0)

    def test_reject_unsafe_base(self):
        for url in ("http://example.com", "https://user:pw@example.com", "https://example.com?token=abc"):
            with self.assertRaises(ValueError):
                validate_base(url)


if __name__ == "__main__":
    unittest.main()
