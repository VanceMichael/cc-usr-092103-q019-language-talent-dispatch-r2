import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.dispatch.eligibility import evaluate
from src.dispatch.enums import (
    AuthorizationKind,
    ClearanceLevel,
    PersonnelCategory,
    Sensitivity,
    ServiceType,
)
from src.dispatch.models import (
    Activity,
    Authorization,
    AvailabilityWindow,
    Commitment,
    Credential,
    LanguagePair,
    Person,
    Slot,
)

SH = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")

ZH_EN = LanguagePair("中文", "英语")
ZH_FR = LanguagePair("中文", "法语")
CONF = ServiceType.CONFERENCE_INTERPRETATION
YOUTH = ServiceType.YOUTH_EXCHANGE


def make_person(**overrides):
    person = Person(
        person_id="T1",
        name="测试员",
        category=PersonnelCategory.TRANSLATOR,
        organization="北辰外国语大学",
        service_types={CONF},
        language_pairs=[ZH_EN],
        credentials=[
            Credential("CATTI二级口译", frozenset({CONF}), frozenset({ZH_EN}), date(2024, 1, 1), date(2027, 1, 1))
        ],
        availability=[
            AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 18, tzinfo=SH))
        ],
        clearance=ClearanceLevel.INTERNAL,
        membership_valid_until=date(2027, 12, 31),
    )
    for key, value in overrides.items():
        setattr(person, key, value)
    return person


def make_slot(**overrides):
    slot = Slot("SL", "英语同传", CONF, ZH_EN)
    for key, value in overrides.items():
        setattr(slot, key, value)
    return slot


def make_activity(**overrides):
    activity = Activity(
        activity_id="ACT-T",
        name="测试论坛",
        scenario="国际会议",
        service_type=CONF,
        venue="主会场",
        timezone="Asia/Shanghai",
        start=datetime(2026, 10, 20, 9, tzinfo=SH),
        end=datetime(2026, 10, 20, 12, tzinfo=SH),
        sensitivity=Sensitivity.MEDIUM,
        min_clearance=ClearanceLevel.INTERNAL,
        slots=[make_slot()],
    )
    for key, value in overrides.items():
        setattr(activity, key, value)
    return activity


def make_minor(authorizations):
    return Person(
        person_id="M1",
        name="未成年志愿者",
        category=PersonnelCategory.VOLUNTEER,
        organization="东海外国语学院",
        service_types={YOUTH},
        language_pairs=[ZH_EN],
        credentials=[
            Credential("青少年志愿服务证", frozenset({YOUTH}), frozenset(), date(2025, 9, 1), date(2027, 12, 31))
        ],
        availability=[
            AvailabilityWindow(datetime(2026, 10, 21, 8, tzinfo=SH), datetime(2026, 10, 21, 18, tzinfo=SH))
        ],
        clearance=ClearanceLevel.PUBLIC,
        birth_date=date(2010, 5, 12),
        authorizations=authorizations,
        membership_valid_until=date(2027, 12, 31),
    )


def make_youth_activity(**overrides):
    activity = Activity(
        activity_id="ACT-Y",
        name="交流营",
        scenario="青少年交流营",
        service_type=YOUTH,
        venue="交流中心",
        timezone="Asia/Shanghai",
        start=datetime(2026, 10, 21, 9, tzinfo=SH),
        end=datetime(2026, 10, 21, 17, tzinfo=SH),
        sensitivity=Sensitivity.LOW,
        min_clearance=ClearanceLevel.PUBLIC,
        allow_minors=True,
        slots=[make_slot(slot_id="SL-Y", role="交流助教", service_type=YOUTH)],
    )
    for key, value in overrides.items():
        setattr(activity, key, value)
    return activity


GUARDIAN = Authorization(AuthorizationKind.GUARDIAN, "家长", date(2026, 1, 1), date(2027, 6, 30))
SCHOOL = Authorization(AuthorizationKind.SCHOOL, "学校", date(2026, 1, 1), date(2027, 6, 30))


class EligibilityTest(unittest.TestCase):
    def test_all_checks_pass_with_full_reasons(self):
        result = evaluate(make_person(), make_activity(), make_slot())
        self.assertTrue(result.ok)
        text = "；".join(result.reasons)
        for keyword in ("语种方向匹配", "持有效能力证明", "保密级别", "可用时段覆盖", "无时间、地点和职责冲突"):
            self.assertIn(keyword, text)

    def test_expired_credential_rejected(self):
        person = make_person(
            credentials=[Credential("CATTI二级口译", frozenset({CONF}), frozenset({ZH_EN}), date(2020, 1, 1), date(2025, 12, 31))]
        )
        result = evaluate(person, make_activity(), make_slot())
        self.assertFalse(result.ok)
        self.assertTrue(any("能力证明已过期" in v for v in result.violations))

    def test_language_mismatch(self):
        result = evaluate(make_person(), make_activity(), make_slot(language_pair=ZH_FR))
        self.assertFalse(result.ok)
        self.assertTrue(any("语种方向不符" in v for v in result.violations))

    def test_clearance_insufficient(self):
        person = make_person(clearance=ClearanceLevel.PUBLIC)
        result = evaluate(person, make_activity(), make_slot())
        self.assertFalse(result.ok)
        self.assertTrue(any("保密级别不足" in v for v in result.violations))

    def test_availability_not_covering(self):
        person = make_person(
            availability=[AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 10, tzinfo=SH))]
        )
        result = evaluate(person, make_activity(), make_slot())
        self.assertFalse(result.ok)
        self.assertTrue(any("可用时段不覆盖" in v for v in result.violations))

    def test_availability_across_timezones(self):
        # 巴黎 09:00–11:00（UTC+2）即 UTC 07:00–09:00，UTC 06:00–10:00 的窗口应覆盖
        activity = make_activity(
            timezone="Europe/Paris",
            start=datetime(2026, 10, 20, 9, tzinfo=ZoneInfo("Europe/Paris")),
            end=datetime(2026, 10, 20, 11, tzinfo=ZoneInfo("Europe/Paris")),
        )
        person = make_person(
            availability=[AvailabilityWindow(datetime(2026, 10, 20, 6, tzinfo=UTC), datetime(2026, 10, 20, 10, tzinfo=UTC))]
        )
        self.assertTrue(evaluate(person, activity, make_slot()).ok)

    def test_service_type_not_registered(self):
        person = make_person(service_types={ServiceType.PUBLIC_DOCENT})
        result = evaluate(person, make_activity(), make_slot())
        self.assertFalse(result.ok)
        self.assertTrue(any("未登记服务类型" in v for v in result.violations))

    def test_expired_membership(self):
        person = make_person(membership_valid_until=date(2026, 9, 30))
        result = evaluate(person, make_activity(), make_slot())
        self.assertFalse(result.ok)
        self.assertTrue(any("名单已失效" in v for v in result.violations))

    def test_inactive_person(self):
        person = make_person(active=False, deactivated_reason="名单失效")
        result = evaluate(person, make_activity(), make_slot())
        self.assertFalse(result.ok)
        self.assertTrue(any("已停用" in v for v in result.violations))

    def test_minor_with_dual_authorization_passes(self):
        minor = make_minor([GUARDIAN, SCHOOL])
        activity = make_youth_activity()
        result = evaluate(minor, activity, activity.slots[0])
        self.assertTrue(result.ok)
        text = "；".join(result.reasons)
        self.assertIn("监护人授权有效", text)
        self.assertIn("学校授权有效", text)

    def test_minor_missing_school_authorization(self):
        minor = make_minor([GUARDIAN])
        activity = make_youth_activity()
        result = evaluate(minor, activity, activity.slots[0])
        self.assertFalse(result.ok)
        self.assertTrue(any("缺少有效学校授权" in v for v in result.violations))

    def test_minor_missing_guardian_authorization(self):
        minor = make_minor([SCHOOL])
        activity = make_youth_activity()
        result = evaluate(minor, activity, activity.slots[0])
        self.assertFalse(result.ok)
        self.assertTrue(any("缺少有效监护人授权" in v for v in result.violations))

    def test_minor_blocked_when_activity_disallows(self):
        minor = make_minor([GUARDIAN, SCHOOL])
        activity = make_youth_activity(allow_minors=False)
        result = evaluate(minor, activity, activity.slots[0])
        self.assertFalse(result.ok)
        self.assertTrue(any("不接收未成年志愿者" in v for v in result.violations))

    def test_minor_blocked_from_unsuitable_content(self):
        minor = make_minor([GUARDIAN, SCHOOL])
        activity = make_youth_activity(content_flags=frozenset({"政治敏感"}))
        result = evaluate(minor, activity, activity.slots[0])
        self.assertFalse(result.ok)
        self.assertTrue(any("不适宜未成年人" in v for v in result.violations))

    def test_minor_blocked_from_high_sensitivity(self):
        minor = make_minor([GUARDIAN, SCHOOL])
        activity = make_youth_activity(sensitivity=Sensitivity.HIGH)
        result = evaluate(minor, activity, activity.slots[0])
        self.assertFalse(result.ok)
        self.assertTrue(any("高敏感活动" in v for v in result.violations))

    def _commitment(self, activity_id="ACT-X", venue="主会场"):
        return Commitment(
            activity_id=activity_id,
            activity_name="另一场活动",
            role="英语同传",
            venue=venue,
            start=datetime(2026, 10, 20, 10, tzinfo=SH),
            end=datetime(2026, 10, 20, 11, tzinfo=SH),
        )

    def test_responsibility_conflict_same_activity(self):
        result = evaluate(make_person(), make_activity(), make_slot(), [self._commitment(activity_id="ACT-T")])
        self.assertFalse(result.ok)
        self.assertTrue(any("职责冲突" in v for v in result.violations))

    def test_location_conflict_different_venue(self):
        result = evaluate(make_person(), make_activity(), make_slot(), [self._commitment(venue="分会场")])
        self.assertFalse(result.ok)
        self.assertTrue(any("地点冲突" in v for v in result.violations))

    def test_time_conflict_same_venue(self):
        result = evaluate(make_person(), make_activity(), make_slot(), [self._commitment()])
        self.assertFalse(result.ok)
        self.assertTrue(any("时间冲突" in v for v in result.violations))


if __name__ == "__main__":
    unittest.main()
