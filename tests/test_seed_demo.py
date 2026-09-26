import contextlib
import io
import unittest
from datetime import date

from src.dispatch import demo
from src.dispatch.enums import AssignmentState, PersonnelCategory, ServiceOutcome, ServiceType
from src.dispatch.seed import UNIVERSITIES, build_activities, build_pool


class SeedTest(unittest.TestCase):
    def test_five_universities_represented(self):
        pool = build_pool()
        organizations = {p.organization for p in pool.all()}
        for university in UNIVERSITIES:
            self.assertIn(university, organizations)
        self.assertEqual(len(UNIVERSITIES), 5)

    def test_three_personnel_categories(self):
        pool = build_pool()
        categories = {p.category for p in pool.all()}
        self.assertEqual(
            categories,
            {PersonnelCategory.EXPERT, PersonnelCategory.TRANSLATOR, PersonnelCategory.VOLUNTEER},
        )

    def test_activities_cover_three_service_types(self):
        activities = build_activities()
        self.assertEqual(len(activities), 3)
        self.assertEqual(
            {a.service_type for a in activities},
            {ServiceType.CONFERENCE_INTERPRETATION, ServiceType.PUBLIC_DOCENT, ServiceType.YOUTH_EXCHANGE},
        )
        for activity in activities:
            self.assertTrue(activity.venue)
            self.assertTrue(activity.timezone)
            self.assertIsNotNone(activity.waitlist)

    def test_pool_has_minors_and_expired_credential_samples(self):
        pool = build_pool()
        self.assertTrue(any(p.is_minor(date(2026, 10, 21)) for p in pool.all()))
        self.assertTrue(
            any(
                not c.is_valid(date(2026, 10, 1))
                for p in pool.all()
                for c in p.credentials
            )
        )


class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.engine = demo.main()
        cls.roster = cls.engine.roster()

    def test_final_roster_has_no_conflicts(self):
        self.assertTrue(self.roster.is_clean)

    def test_every_entry_is_explained(self):
        self.assertGreater(len(self.roster.entries), 0)
        for entry in self.roster.entries:
            self.assertGreater(len(entry.reasons), 3, f"{entry.person_name} 缺少入选理由")

    def test_minor_on_roster_has_dual_authorization_reasons(self):
        entry = next(e for e in self.roster.entries if e.person_name == "李小满")
        text = "；".join(entry.reasons)
        self.assertIn("监护人授权有效", text)
        self.assertIn("学校授权有效", text)

    def test_minor_without_school_authorization_never_assigned(self):
        assigned = {a.person_id for a in self.engine.assignments.values()}
        self.assertNotIn("P11", assigned)

    def test_absent_person_not_reassigned(self):
        # 郑川缺席后不得再次被派同一岗位
        zheng = [a for a in self.engine.assignments.values() if a.person_id == "P08"]
        self.assertTrue(zheng)
        self.assertTrue(all(a.state is AssignmentState.NO_SHOW for a in zheng))
        person = self.engine.pool.get("P08")
        self.assertEqual(person.service_history[-1].outcome, ServiceOutcome.NO_SHOW)
        self.assertEqual(person.feedback[-1].rating, 1)

    def test_pool_pruned_after_demo(self):
        pool = self.engine.pool
        self.assertEqual(pool.get("P04").credentials, [])
        self.assertFalse(pool.get("P12").active)

    def test_accepts_and_rejections_all_logged(self):
        kinds = {e.kind for e in self.engine.events}
        for expected in ("派单", "接受", "拒绝", "缺席", "撤销", "改期", "新增需求", "活动完成"):
            self.assertIn(expected, kinds)

    def test_rare_language_gap_reported(self):
        gap_text = "；".join(g.role for g in self.roster.gaps)
        self.assertIn("老挝语联络", gap_text)


if __name__ == "__main__":
    unittest.main()
