import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.models import Feedback, parse_dt
from src.pool import TalentPool
from src.seed import load_seed

SEED = Path("fixtures/seed.json")
AS_OF = datetime(2026, 9, 26, tzinfo=timezone.utc)


class PoolTest(unittest.TestCase):
    def setUp(self):
        self.pool, _ = load_seed(SEED)

    def test_seed_has_five_universities_and_categories(self):
        import json

        data = json.loads(SEED.read_text(encoding="utf-8"))
        self.assertEqual(len(data["universities"]), 5)
        self.assertEqual(data["expert_categories"], ["专家", "翻译人员", "志愿者"])

    def test_record_service_is_the_only_feedback_channel(self):
        self.pool.record_service(
            "P004", Feedback(event_id="EV-100", rating=5, comment="讲解出色", recorded_at="2026-10-15T18:00:00+08:00")
        )
        self.assertEqual(self.pool.people["P004"].average_rating(), 5.0)
        with self.assertRaises(ValueError):
            self.pool.record_service(
                "P004", Feedback(event_id="EV-100", rating=9, comment="", recorded_at="2026-10-15T18:00:00+08:00")
            )

    def test_purge_removes_expired_certs_and_stale_members(self):
        report = self.pool.purge(AS_OF)
        # P006 的证书 2022 年过期，且 2021 年后无服务记录 → 失效名单
        self.assertIn(("P006", "C-E5"), report["expired_certs"])
        self.assertIn("P006", report["deactivated"])
        self.assertFalse(self.pool.people["P006"].active)
        # P002 证书 2026-06 过期也被清出，但近期反馈有效保留待议
        self.assertIn(("P002", "C-E2"), report["expired_certs"])
        # 有效成员不受影响
        self.assertIn("P001", [p.person_id for p in self.pool.active_members()])

    def test_parse_dt_normalizes_timezones(self):
        a = parse_dt("2026-10-15T09:00:00+05:00")
        b = parse_dt("2026-10-15T12:00:00+08:00")
        self.assertEqual(a, b)  # 同一时刻，均为 UTC 04:00


if __name__ == "__main__":
    unittest.main()
