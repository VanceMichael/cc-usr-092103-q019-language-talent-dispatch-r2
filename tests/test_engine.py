import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.dispatch.engine import DispatchEngine
from src.dispatch.enums import (
    AssignmentState,
    AuthorizationKind,
    ClearanceLevel,
    OfferState,
    PersonnelCategory,
    Sensitivity,
    ServiceOutcome,
    ServiceType,
)
from src.dispatch.models import (
    Activity,
    Authorization,
    AvailabilityWindow,
    Credential,
    LanguagePair,
    Person,
    Slot,
    WaitlistRule,
)
from src.dispatch.pool import TalentPool

SH = ZoneInfo("Asia/Shanghai")
ZH_EN = LanguagePair("中文", "英语")
ZH_SW = LanguagePair("中文", "斯瓦希里语")
ZH_LO = LanguagePair("中文", "老挝语")
EN_LO = LanguagePair("英语", "老挝语")
CONF = ServiceType.CONFERENCE_INTERPRETATION
YOUTH = ServiceType.YOUTH_EXCHANGE

T0 = datetime(2026, 9, 26, 10, tzinfo=SH)


def make_person(pid, name, *, pairs=None, avail=None, service_types=None, **kwargs):
    return Person(
        person_id=pid,
        name=name,
        category=PersonnelCategory.TRANSLATOR,
        organization="北辰外国语大学",
        service_types=service_types or {CONF},
        language_pairs=pairs or [ZH_EN],
        credentials=[
            Credential("CATTI二级口译", frozenset({CONF, YOUTH}), frozenset(), date(2024, 1, 1), date(2028, 1, 1))
        ],
        availability=avail
        if avail is not None
        else [AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 18, tzinfo=SH))],
        clearance=ClearanceLevel.INTERNAL,
        membership_valid_until=date(2027, 12, 31),
        **kwargs,
    )


def make_activity(aid="A1", *, headcount=1, backup=0, venue="主会场", pair=ZH_EN, start_h=9, end_h=12):
    return Activity(
        activity_id=aid,
        name=f"活动{aid}",
        scenario="国际会议",
        service_type=CONF,
        venue=venue,
        timezone="Asia/Shanghai",
        start=datetime(2026, 10, 20, start_h, tzinfo=SH),
        end=datetime(2026, 10, 20, end_h, tzinfo=SH),
        sensitivity=Sensitivity.MEDIUM,
        min_clearance=ClearanceLevel.INTERNAL,
        slots=[Slot("SL", "英语同传", CONF, pair, headcount=headcount)],
        waitlist=WaitlistRule(backup_count=backup, auto_promote=True),
    )


class EngineTestBase(unittest.TestCase):
    def setUp(self):
        self.pool = TalentPool()
        self.engine = DispatchEngine(self.pool)

    def add_person(self, pid, name, **kwargs):
        person = make_person(pid, name, **kwargs)
        self.pool.register(person)
        return person

    def open(self, activity):
        self.engine.open_activity(activity, T0)
        return activity

    def offer_and_accept(self, activity, person):
        offers = self.engine.offer_to(activity.activity_id, "SL", [person.person_id], T0)
        self.engine.respond(offers[0].offer_id, True, T0)
        return self.engine, offers[0]


class ConcurrentOfferTest(EngineTestBase):
    def test_first_accept_wins_and_pending_offer_auto_rejected(self):
        p1 = self.add_person("P1", "甲")
        p2 = self.add_person("P2", "乙")
        activity = self.open(make_activity())  # 无候补名额
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1", "P2"], T0)

        self.engine.respond(offers[0].offer_id, True, T0)

        # 名额占满后，乙的待回复派单被系统自动拒绝并留痕
        self.assertEqual(offers[0].state, OfferState.ACCEPTED)
        self.assertEqual(offers[1].state, OfferState.REJECTED)
        self.assertEqual(offers[1].response_reason, "岗位名额已满")
        kinds = [e.kind for e in self.engine.history(activity_id=activity.activity_id)]
        self.assertIn("接受", kinds)
        self.assertIn("拒绝", kinds)
        with self.assertRaises(ValueError):
            self.engine.respond(offers[1].offer_id, True, T0)

    def test_accept_after_full_rejected_when_no_room(self):
        self.add_person("P1", "甲")
        self.add_person("P2", "乙")
        activity = self.open(make_activity())  # 无候补名额
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)

        late = self.engine.offer_to(activity.activity_id, "SL", ["P2"], T0)[0]
        self.engine.respond(late.offer_id, True, T0)

        self.assertEqual(late.state, OfferState.REJECTED)
        self.assertEqual(late.response_reason, "岗位名额已满")

    def test_second_accept_becomes_standby_when_backup_allowed(self):
        self.add_person("P1", "甲")
        self.add_person("P2", "乙")
        activity = self.open(make_activity(backup=1))
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1", "P2"], T0)

        self.engine.respond(offers[0].offer_id, True, T0)
        self.engine.respond(offers[1].offer_id, True, T0)

        self.assertEqual(offers[1].state, OfferState.ACCEPTED)
        standby = [a for a in self.engine.assignments.values() if a.state is AssignmentState.STANDBY]
        self.assertEqual(len(standby), 1)
        self.assertEqual(standby[0].person_id, "P2")

    def test_third_accept_auto_rejected_when_primary_and_standby_full(self):
        for pid, name in (("P1", "甲"), ("P2", "乙"), ("P3", "丙")):
            self.add_person(pid, name)
        activity = self.open(make_activity(backup=1))
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1", "P2", "P3"], T0)

        self.engine.respond(offers[0].offer_id, True, T0)  # 正选
        self.engine.respond(offers[1].offer_id, True, T0)  # 候补

        # 正选候补都已满，丙的派单自动失效
        self.assertEqual(offers[2].state, OfferState.REJECTED)
        self.assertEqual(offers[2].response_reason, "岗位名额已满")

    def test_explicit_rejection_recorded_with_reason(self):
        self.add_person("P1", "甲")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, False, T0, "档期冲突")
        self.assertEqual(offers[0].state, OfferState.REJECTED)
        self.assertEqual(offers[0].response_reason, "档期冲突")
        events = self.engine.history(person_id="P1")
        self.assertTrue(any(e.kind == "拒绝" and "档期冲突" in e.detail for e in events))

    def test_respond_twice_raises(self):
        self.add_person("P1", "甲")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)
        with self.assertRaises(ValueError):
            self.engine.respond(offers[0].offer_id, True, T0)

    def test_accept_revalidated_against_new_conflicts(self):
        person = self.add_person("P1", "甲")
        a1 = self.open(make_activity("A1", venue="主会场"))
        a2 = self.open(make_activity("A2", venue="分会场"))
        o1 = self.engine.offer_to(a1.activity_id, "SL", [person.person_id], T0)[0]
        o2 = self.engine.offer_to(a2.activity_id, "SL", [person.person_id], T0)[0]

        self.engine.respond(o1.offer_id, True, T0)
        self.engine.respond(o2.offer_id, True, T0)

        self.assertEqual(o2.state, OfferState.REJECTED)
        self.assertIn("地点冲突", o2.response_reason)


class AbsenceTest(EngineTestBase):
    def test_absence_promotes_standby_and_records_real_service(self):
        p1 = self.add_person("P1", "甲")
        p2 = self.add_person("P2", "乙")
        activity = self.open(make_activity(backup=1))
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1", "P2"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)
        self.engine.respond(offers[1].offer_id, True, T0)
        confirmed = next(a for a in self.engine.assignments.values() if a.state is AssignmentState.CONFIRMED)

        report = self.engine.report_absence(confirmed.assignment_id, datetime(2026, 10, 20, 8, 30, tzinfo=SH), "临场失联")

        self.assertEqual(len(report.promoted), 1)
        self.assertEqual(report.promoted[0].person_id, "P2")
        # 缺席写入真实服务记录：反馈最低分
        self.assertEqual(p1.service_history[-1].outcome, ServiceOutcome.NO_SHOW)
        self.assertEqual(p1.feedback[-1].rating, 1)
        kinds = [e.kind for e in self.engine.history(person_id="P2")]
        self.assertIn("候补递补", kinds)

    def test_absence_dispatches_fresh_offer_and_excludes_absent_person(self):
        p1 = self.add_person("P1", "甲")
        self.add_person("P2", "乙")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)
        confirmed = next(a for a in self.engine.assignments.values() if a.state is AssignmentState.CONFIRMED)

        report = self.engine.report_absence(confirmed.assignment_id, datetime(2026, 10, 20, 8, 30, tzinfo=SH))

        self.assertEqual(len(report.new_offers), 1)
        self.assertEqual(report.new_offers[0].person_id, "P2")
        self.assertNotEqual(report.new_offers[0].person_id, p1.person_id)


class RescheduleTest(EngineTestBase):
    def test_reschedule_revokes_ineligible_and_refills(self):
        morning_only = [AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 12, tzinfo=SH))]
        self.add_person("P1", "甲", avail=morning_only)
        self.add_person("P2", "乙")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)

        report = self.engine.reschedule(
            activity.activity_id,
            datetime(2026, 10, 20, 13, tzinfo=SH),
            datetime(2026, 10, 20, 16, tzinfo=SH),
            datetime(2026, 10, 19, 9, tzinfo=SH),
        )

        self.assertEqual(len(report.revoked), 1)
        self.assertIn("可用时段不覆盖", report.revoked[0].note)
        self.assertEqual(len(report.new_offers), 1)
        self.assertEqual(report.new_offers[0].person_id, "P2")
        kinds = [e.kind for e in self.engine.history(activity_id=activity.activity_id)]
        self.assertIn("改期", kinds)
        self.assertIn("撤销", kinds)

    def test_reschedule_refreshes_reasons_of_survivors(self):
        self.add_person("P1", "甲")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)

        self.engine.reschedule(
            activity.activity_id,
            datetime(2026, 10, 20, 13, tzinfo=SH),
            datetime(2026, 10, 20, 16, tzinfo=SH),
            datetime(2026, 10, 19, 9, tzinfo=SH),
        )

        assignment = next(a for a in self.engine.assignments.values() if a.state is AssignmentState.CONFIRMED)
        self.assertTrue(any("13:00" in r for r in assignment.reasons))

    def test_pending_offers_expire_on_reschedule(self):
        self.add_person("P1", "甲")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)

        self.engine.reschedule(
            activity.activity_id,
            datetime(2026, 10, 20, 13, tzinfo=SH),
            datetime(2026, 10, 20, 16, tzinfo=SH),
            datetime(2026, 10, 19, 9, tzinfo=SH),
        )

        self.assertEqual(offers[0].state, OfferState.EXPIRED)
        kinds = [e.kind for e in self.engine.history(activity_id=activity.activity_id)]
        self.assertIn("派单失效", kinds)


class RareLanguageTest(EngineTestBase):
    def test_add_requirement_finds_rare_language_speaker(self):
        self.add_person("P1", "甲", pairs=[ZH_SW])
        activity = self.open(make_activity())
        slot = Slot("S-SW", "斯瓦希里语联络", CONF, ZH_SW)
        report = self.engine.add_requirement(activity.activity_id, slot, T0)
        self.assertEqual(len(report.new_offers), 1)
        self.assertEqual(report.new_offers[0].person_id, "P1")
        self.assertFalse(report.gaps)

    def test_add_requirement_reports_gap_and_relay_suggestion(self):
        self.add_person("P1", "甲", pairs=[ZH_EN])
        self.add_person("P2", "乙", pairs=[EN_LO])
        activity = self.open(make_activity())
        slot = Slot("S-LO", "老挝语联络", CONF, ZH_LO)
        report = self.engine.add_requirement(activity.activity_id, slot, T0)
        self.assertTrue(any("暂无可用人选" in g for g in report.gaps))
        relay = next((g for g in report.gaps if "接力口译建议" in g), None)
        self.assertIsNotNone(relay)
        self.assertIn("甲", relay)
        self.assertIn("乙", relay)

    def test_add_requirement_gap_without_relay(self):
        self.add_person("P1", "甲", pairs=[ZH_EN])
        activity = self.open(make_activity())
        slot = Slot("S-LO", "老挝语联络", CONF, ZH_LO)
        report = self.engine.add_requirement(activity.activity_id, slot, T0)
        self.assertTrue(any("暂无方案" in g for g in report.gaps))


class MinorProtectionTest(EngineTestBase):
    def test_offer_to_minor_without_school_authorization_blocked(self):
        minor = Person(
            person_id="M1",
            name="未成年",
            category=PersonnelCategory.VOLUNTEER,
            organization="东海外国语学院",
            service_types={YOUTH},
            language_pairs=[ZH_EN],
            credentials=[Credential("青少年志愿服务证", frozenset({YOUTH}), frozenset(), date(2025, 9, 1), date(2027, 12, 31))],
            availability=[AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 18, tzinfo=SH))],
            clearance=ClearanceLevel.PUBLIC,
            birth_date=date(2010, 5, 12),
            authorizations=[
                Authorization(AuthorizationKind.GUARDIAN, "家长", date(2026, 1, 1), date(2027, 6, 30))
            ],
            membership_valid_until=date(2027, 12, 31),
        )
        self.pool.register(minor)
        activity = make_activity("A9")
        activity.service_type = YOUTH
        activity.allow_minors = True
        activity.min_clearance = ClearanceLevel.PUBLIC
        activity.slots = [Slot("SL", "交流助教", YOUTH, ZH_EN)]
        self.open(activity)

        offers = self.engine.offer_to(activity.activity_id, "SL", ["M1"], T0)

        self.assertEqual(offers, [])
        events = self.engine.history(person_id="M1")
        self.assertTrue(any(e.kind == "派单校验未通过" and "学校授权" in e.detail for e in events))


class HistoryAndCompletionTest(EngineTestBase):
    def test_history_filters_by_person_and_activity(self):
        self.add_person("P1", "甲")
        self.add_person("P2", "乙")
        a1 = self.open(make_activity("A1"))
        a2 = self.open(make_activity("A2", venue="分会场", start_h=14, end_h=17))
        for pid, act in (("P1", a1), ("P2", a2)):
            offers = self.engine.offer_to(act.activity_id, "SL", [pid], T0)
            self.engine.respond(offers[0].offer_id, True, T0)

        self.assertTrue(all(e.person_id == "P1" for e in self.engine.history(person_id="P1")))
        self.assertTrue(all(e.activity_id == "A2" for e in self.engine.history(activity_id="A2")))
        self.assertGreater(len(self.engine.history()), 0)

    def test_complete_activity_writes_real_service_to_pool(self):
        p1 = self.add_person("P1", "甲")
        activity = self.open(make_activity())
        offers = self.engine.offer_to(activity.activity_id, "SL", ["P1"], T0)
        self.engine.respond(offers[0].offer_id, True, T0)

        self.engine.complete_activity(activity.activity_id, datetime(2026, 10, 20, 12, 30, tzinfo=SH), {"P1": 5})

        self.assertEqual(p1.feedback[-1].rating, 5)
        self.assertEqual(p1.service_history[-1].outcome, ServiceOutcome.COMPLETED)
        assignment = next(iter(self.engine.assignments.values()))
        self.assertEqual(assignment.state, AssignmentState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
