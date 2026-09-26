import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.dispatch.enums import (
    AuthorizationKind,
    ClearanceLevel,
    PersonnelCategory,
    ServiceOutcome,
    ServiceType,
)
from src.dispatch.models import (
    Authorization,
    AvailabilityWindow,
    Credential,
    LanguagePair,
    Person,
)
from src.dispatch.pool import TalentPool

SH = ZoneInfo("Asia/Shanghai")
ZH_EN = LanguagePair("中文", "英语")
CONF = ServiceType.CONFERENCE_INTERPRETATION


def make_person(pid="P1", **overrides):
    person = Person(
        person_id=pid,
        name=f"人员{pid}",
        category=PersonnelCategory.TRANSLATOR,
        organization="北辰外国语大学",
        service_types={CONF},
        language_pairs=[ZH_EN],
        credentials=[
            Credential("CATTI二级口译", frozenset({CONF}), frozenset(), date(2020, 1, 1), date(2025, 12, 31)),
            Credential("长期有效证明", frozenset({CONF}), frozenset(), date(2020, 1, 1), None),
        ],
        availability=[
            AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 18, tzinfo=SH))
        ],
        clearance=ClearanceLevel.INTERNAL,
        authorizations=[
            Authorization(AuthorizationKind.GUARDIAN, "家长", date(2025, 1, 1), date(2025, 12, 31)),
            Authorization(AuthorizationKind.SCHOOL, "学校", date(2026, 1, 1), date(2027, 6, 30)),
        ],
        membership_valid_until=date(2027, 12, 31),
    )
    for key, value in overrides.items():
        setattr(person, key, value)
    return person


class RecordServiceTest(unittest.TestCase):
    def test_completed_service_appends_feedback(self):
        pool = TalentPool()
        person = make_person()
        pool.register(person)
        pool.record_service("P1", "ACT-1", "英语同传", ServiceOutcome.COMPLETED, datetime(2026, 9, 1, 12, tzinfo=SH), rating=5)
        self.assertEqual(len(person.feedback), 1)
        self.assertEqual(person.feedback[0].rating, 5)
        self.assertEqual(person.average_rating(), 5.0)
        self.assertEqual(person.completed_count(), 1)

    def test_no_show_forces_lowest_rating(self):
        pool = TalentPool()
        person = make_person()
        pool.register(person)
        pool.record_service("P1", "ACT-1", "英语同传", ServiceOutcome.NO_SHOW, datetime(2026, 9, 1, 12, tzinfo=SH), comment="临场失联")
        self.assertEqual(person.feedback[0].rating, 1)
        self.assertIn("临场失联", person.feedback[0].comment)
        self.assertEqual(person.completed_count(), 0)

    def test_invalid_rating_rejected(self):
        pool = TalentPool()
        pool.register(make_person())
        with self.assertRaises(ValueError):
            pool.record_service("P1", "ACT-1", "英语同传", ServiceOutcome.COMPLETED, datetime(2026, 9, 1, 12, tzinfo=SH), rating=6)

    def test_duplicate_registration_rejected(self):
        pool = TalentPool()
        pool.register(make_person())
        with self.assertRaises(ValueError):
            pool.register(make_person())


class PruneTest(unittest.TestCase):
    def test_prune_removes_expired_credentials_and_authorizations(self):
        pool = TalentPool()
        person = make_person()
        pool.register(person)
        report = pool.prune(date(2026, 10, 22))

        remaining = [c.name for c in person.credentials]
        self.assertEqual(remaining, ["长期有效证明"])
        self.assertEqual(len(report.removed_credentials), 1)

        remaining_auth = [a.kind for a in person.authorizations]
        self.assertEqual(remaining_auth, [AuthorizationKind.SCHOOL])
        self.assertEqual(len(report.removed_authorizations), 1)
        self.assertTrue(pool.prune_log)

    def test_prune_deactivates_stale_member(self):
        pool = TalentPool()
        stale = make_person("P-STALE", membership_valid_until=date(2026, 9, 30))
        pool.register(stale)
        report = pool.prune(date(2026, 10, 22))
        self.assertFalse(stale.active)
        self.assertEqual(len(report.deactivated), 1)

    def test_prune_keeps_member_with_recent_service(self):
        pool = TalentPool()
        person = make_person("P-ACTIVE", membership_valid_until=date(2026, 9, 30))
        pool.register(person)
        pool.record_service(
            "P-ACTIVE", "ACT-1", "英语同传", ServiceOutcome.COMPLETED, datetime(2026, 10, 1, 12, tzinfo=SH), rating=4
        )
        report = pool.prune(date(2026, 10, 22))
        self.assertTrue(person.active)
        self.assertEqual(report.deactivated, [])

    def test_prune_keeps_valid_membership(self):
        pool = TalentPool()
        person = make_person()
        pool.register(person)
        pool.prune(date(2026, 10, 22))
        self.assertTrue(person.active)


if __name__ == "__main__":
    unittest.main()
