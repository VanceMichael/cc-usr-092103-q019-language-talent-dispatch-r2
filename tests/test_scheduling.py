import unittest
from pathlib import Path

from src.models import (
    Clearance,
    ContentRating,
    Post,
    ServiceType,
    WaitlistRule,
)
from src.scheduling import check_eligibility, find_conflicts
from src.seed import load_seed

SEED = Path("fixtures/seed.json")


def make_post(**overrides) -> Post:
    base = dict(
        post_id="PX",
        event_id="EV-X",
        scenario="测试",
        service_type=ServiceType.CONFERENCE_INTERPRETING,
        language_pair="zh-en",
        location="会场",
        timezone="Asia/Shanghai",
        start="2026-10-15T09:00:00+08:00",
        end="2026-10-15T11:00:00+08:00",
        sensitivity=Clearance.INTERNAL,
        content_rating=ContentRating.ALL_AGES,
        waitlist_rule=WaitlistRule(),
    )
    base.update(overrides)
    return Post(**base)


class EligibilityTest(unittest.TestCase):
    def setUp(self):
        self.pool, self.dispatcher = load_seed(SEED)

    def test_eligible_person_carries_reasons(self):
        ok, reasons = check_eligibility(self.pool.people["P001"], self.dispatcher.posts["POST-01"])
        self.assertTrue(ok)
        text = "；".join(reasons)
        self.assertIn("会议口译", text)
        self.assertIn("zh-en", text)
        self.assertIn("C-E1", text)  # 有效能力证明
        self.assertIn("保密级别", text)
        self.assertIn("可用时段", text)

    def test_clearance_below_sensitivity_rejected(self):
        # POST-01 敏感程度为机密(3)，P004 仅公开(1)
        ok, reasons = check_eligibility(self.pool.people["P004"], self.dispatcher.posts["POST-01"])
        self.assertFalse(ok)
        self.assertTrue(any("保密级别" in r for r in reasons))

    def test_expired_cert_rejected(self):
        # P002 的 zh-en 证书 2026-06 已过期，活动时间为 2026-10
        ok, reasons = check_eligibility(self.pool.people["P002"], self.dispatcher.posts["POST-02"])
        self.assertFalse(ok)
        self.assertTrue(any("能力证明" in r for r in reasons))

    def test_minor_needs_both_authorizations(self):
        post = make_post(service_type=ServiceType.YOUTH_EXCHANGE, sensitivity=Clearance.PUBLIC)
        person = self.pool.people["P005"]
        ok, reasons = check_eligibility(person, post)
        self.assertTrue(ok)
        self.assertTrue(any("监护人" in r and "学校" in r for r in reasons))
        # 去掉学校授权后不合格
        person.authorizations = [a for a in person.authorizations if a.kind != "school"]
        ok, reasons = check_eligibility(person, post)
        self.assertFalse(ok)
        self.assertTrue(any("授权" in r for r in reasons))

    def test_minor_blocked_from_unsuitable_content(self):
        post = make_post(
            service_type=ServiceType.YOUTH_EXCHANGE,
            sensitivity=Clearance.PUBLIC,
            content_rating=ContentRating.ADULT,
        )
        ok, reasons = check_eligibility(self.pool.people["P005"], post)
        self.assertFalse(ok)
        self.assertTrue(any("未成年人不得参与" in r for r in reasons))

    def test_cross_timezone_availability(self):
        # 同一时刻用不同时区表示，可用性判断应一致
        post = make_post(start="2026-10-15T09:00:00+05:00", end="2026-10-15T11:00:00+05:00")
        ok, _ = check_eligibility(self.pool.people["P001"], post)
        self.assertTrue(ok)


class ConflictTest(unittest.TestCase):
    def setUp(self):
        self.pool, self.dispatcher = load_seed(SEED)

    def test_time_location_and_duty_conflicts(self):
        d = self.dispatcher
        offers = d.dispatch("POST-01")
        self.assertEqual(len(offers), 1)
        d.respond(offers[0].assignment_id, accept=True)

        # 时间重叠且异地 → 地点冲突
        other = make_post(post_id="PY", start="2026-10-15T10:00:00+08:00", end="2026-10-15T12:00:00+08:00")
        d.add_post(other)
        conflicts = find_conflicts("P001", other, list(d.assignments.values()), d.posts)
        self.assertTrue(any("地点冲突" in c for c in conflicts))

        # 同一岗位 → 职责冲突
        conflicts = find_conflicts("P001", d.posts["POST-01"], list(d.assignments.values()), d.posts)
        self.assertTrue(any("职责冲突" in c for c in conflicts))

        # 时间不重叠 → 无冲突
        later = make_post(post_id="PZ", start="2026-10-15T14:00:00+08:00", end="2026-10-15T16:00:00+08:00")
        d.add_post(later)
        self.assertEqual(find_conflicts("P001", later, list(d.assignments.values()), d.posts), [])


if __name__ == "__main__":
    unittest.main()
