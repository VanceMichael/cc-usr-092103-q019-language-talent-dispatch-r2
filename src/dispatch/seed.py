"""种子数据：五所合作高校、三类人才与三场服务样例。

全部为虚构数据，不含真实个人信息。历史评分一律通过
TalentPool.record_service 依据真实服务记录写入。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .enums import (
    AuthorizationKind,
    ClearanceLevel,
    PersonnelCategory,
    Sensitivity,
    ServiceOutcome,
    ServiceType,
)
from .models import (
    Activity,
    Authorization,
    AvailabilityWindow,
    Credential,
    LanguagePair,
    Person,
    Slot,
    WaitlistRule,
)
from .pool import TalentPool

SH = ZoneInfo("Asia/Shanghai")

# 五所长期合作高校
UNIVERSITIES = [
    "北辰外国语大学",
    "松江国际关系学院",
    "岭南翻译学院",
    "西京语言大学",
    "东海外国语学院",
]

# 语种方向
ZH_EN = LanguagePair("中文", "英语")
ZH_FR = LanguagePair("中文", "法语")
ZH_JA = LanguagePair("中文", "日语")
ZH_RU = LanguagePair("中文", "俄语")
ZH_DE = LanguagePair("中文", "德语")
ZH_SW = LanguagePair("中文", "斯瓦希里语")
ZH_LO = LanguagePair("中文", "老挝语")

CONFERENCE = ServiceType.CONFERENCE_INTERPRETATION
DOCENT = ServiceType.PUBLIC_DOCENT
YOUTH = ServiceType.YOUTH_EXCHANGE

MEMBERSHIP_VALID = date(2027, 12, 31)


def _dt(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=SH)


def _avail(*windows: tuple[int, int, int, int]) -> list[AvailabilityWindow]:
    return [AvailabilityWindow(_dt(m, d, h), _dt(m, d, h2)) for m, d, h, h2 in windows]


def build_pool() -> TalentPool:
    """登记五所高校的专家、翻译人员与志愿者，并写入历史真实服务。"""
    pool = TalentPool()

    def add(person: Person) -> Person:
        pool.register(person)
        return person

    chen_shu = add(
        Person(
            person_id="P01",
            name="陈述",
            category=PersonnelCategory.EXPERT,
            organization="北辰外国语大学",
            service_types={CONFERENCE},
            language_pairs=[ZH_EN, ZH_FR],
            credentials=[
                Credential("CATTI一级口译", frozenset({CONFERENCE}), frozenset({ZH_EN, ZH_FR}), date(2020, 6, 1), None)
            ],
            availability=_avail((10, 20, 8, 18)),
            clearance=ClearanceLevel.CONFIDENTIAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    add(
        Person(
            person_id="P02",
            name="林澜",
            category=PersonnelCategory.TRANSLATOR,
            organization="松江国际关系学院",
            service_types={CONFERENCE},
            language_pairs=[ZH_FR],
            credentials=[
                Credential("CATTI二级口译", frozenset({CONFERENCE}), frozenset({ZH_FR}), date(2022, 7, 1), date(2027, 6, 30))
            ],
            availability=_avail((10, 20, 8, 12)),  # 只有上午有空，改期到下午会被复核出来
            clearance=ClearanceLevel.INTERNAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    add(
        Person(
            person_id="P03",
            name="韩露",
            category=PersonnelCategory.TRANSLATOR,
            organization="岭南翻译学院",
            service_types={CONFERENCE},
            language_pairs=[ZH_FR],
            credentials=[
                Credential("CATTI二级口译", frozenset({CONFERENCE}), frozenset({ZH_FR}), date(2023, 4, 1), date(2028, 3, 31))
            ],
            availability=_avail((10, 20, 12, 18)),
            clearance=ClearanceLevel.INTERNAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    add(
        Person(
            person_id="P04",
            name="周译",
            category=PersonnelCategory.TRANSLATOR,
            organization="岭南翻译学院",
            service_types={CONFERENCE},
            language_pairs=[ZH_EN],
            credentials=[
                # 已过期：派单时不得使用，清理时应被清出
                Credential("CATTI二级口译", frozenset({CONFERENCE}), frozenset({ZH_EN}), date(2020, 1, 1), date(2025, 12, 31))
            ],
            availability=_avail((10, 20, 8, 18)),
            clearance=ClearanceLevel.INTERNAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    ayguli = add(
        Person(
            person_id="P05",
            name="阿依古丽",
            category=PersonnelCategory.TRANSLATOR,
            organization="西京语言大学",
            service_types={CONFERENCE},
            language_pairs=[ZH_SW, ZH_EN],
            credentials=[
                Credential("稀缺语种服务证明", frozenset({CONFERENCE}), frozenset({ZH_SW, ZH_EN}), date(2024, 1, 1), date(2029, 12, 31))
            ],
            availability=_avail((10, 20, 8, 18)),
            clearance=ClearanceLevel.INTERNAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    gao_ran = add(
        Person(
            person_id="P06",
            name="高然",
            category=PersonnelCategory.EXPERT,
            organization="东海外国语学院",
            service_types={DOCENT},
            language_pairs=[ZH_EN, ZH_JA],
            credentials=[
                Credential("高级讲解员证", frozenset({DOCENT}), frozenset(), date(2023, 1, 1), date(2028, 12, 31))
            ],
            availability=_avail((10, 20, 13, 18)),
            clearance=ClearanceLevel.INTERNAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    sun_qian = add(
        Person(
            person_id="P07",
            name="孙倩",
            category=PersonnelCategory.VOLUNTEER,
            organization="岭南翻译学院",
            service_types={DOCENT, YOUTH},
            language_pairs=[ZH_EN, ZH_JA],
            credentials=[
                Credential("志愿服务培训证书", frozenset({DOCENT, YOUTH}), frozenset(), date(2024, 3, 1), date(2027, 12, 31))
            ],
            availability=_avail((10, 20, 12, 18), (10, 21, 8, 18)),
            clearance=ClearanceLevel.PUBLIC,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    zheng_chuan = add(
        Person(
            person_id="P08",
            name="郑川",
            category=PersonnelCategory.TRANSLATOR,
            organization="西京语言大学",
            service_types={DOCENT},
            language_pairs=[ZH_JA],
            credentials=[
                Credential("讲解员证", frozenset({DOCENT}), frozenset(), date(2023, 7, 1), date(2028, 6, 30))
            ],
            availability=_avail((10, 20, 13, 18)),
            clearance=ClearanceLevel.PUBLIC,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    wu_fan = add(
        Person(
            person_id="P09",
            name="吴帆",
            category=PersonnelCategory.VOLUNTEER,
            organization="松江国际关系学院",
            service_types={YOUTH},
            language_pairs=[ZH_FR],
            credentials=[
                Credential("志愿服务培训证书", frozenset({YOUTH}), frozenset(), date(2024, 3, 1), date(2027, 12, 31))
            ],
            availability=_avail((10, 21, 8, 18)),
            clearance=ClearanceLevel.PUBLIC,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    li_xiaoman = add(
        Person(
            person_id="P10",
            name="李小满",
            category=PersonnelCategory.VOLUNTEER,
            organization="东海外国语学院",
            service_types={YOUTH},
            language_pairs=[ZH_FR],
            credentials=[
                Credential("青少年志愿服务证", frozenset({YOUTH}), frozenset(), date(2025, 9, 1), date(2027, 12, 31))
            ],
            availability=_avail((10, 21, 8, 18)),
            clearance=ClearanceLevel.PUBLIC,
            birth_date=date(2010, 5, 12),  # 活动当天 16 岁
            authorizations=[
                Authorization(AuthorizationKind.GUARDIAN, "李父", date(2026, 1, 1), date(2027, 6, 30)),
                Authorization(AuthorizationKind.SCHOOL, "东海学院附属中学", date(2026, 1, 5), date(2027, 6, 30)),
            ],
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    add(
        Person(
            person_id="P11",
            name="张小禾",
            category=PersonnelCategory.VOLUNTEER,
            organization="东海外国语学院",
            service_types={YOUTH},
            language_pairs=[ZH_FR],
            credentials=[
                Credential("青少年志愿服务证", frozenset({YOUTH}), frozenset(), date(2025, 9, 1), date(2027, 12, 31))
            ],
            availability=_avail((10, 21, 8, 18)),
            clearance=ClearanceLevel.PUBLIC,
            birth_date=date(2009, 11, 3),  # 活动当天 16 岁
            authorizations=[
                # 只有监护人授权，缺学校授权，不得上岗
                Authorization(AuthorizationKind.GUARDIAN, "张母", date(2026, 1, 1), date(2027, 6, 30)),
            ],
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    add(
        Person(
            person_id="P12",
            name="何同",
            category=PersonnelCategory.EXPERT,
            organization="东海外国语学院",
            service_types={CONFERENCE},
            language_pairs=[ZH_DE],
            credentials=[
                Credential("CATTI一级口译", frozenset({CONFERENCE}), frozenset({ZH_DE}), date(2019, 6, 1), None)
            ],
            availability=_avail((10, 20, 8, 18)),
            clearance=ClearanceLevel.CONFIDENTIAL,
            membership_valid_until=date(2026, 9, 30),  # 单位名单已失效
        )
    )
    add(
        Person(
            person_id="P13",
            name="苏杭",
            category=PersonnelCategory.VOLUNTEER,
            organization="西京语言大学",
            service_types={YOUTH},
            language_pairs=[ZH_FR],
            credentials=[
                Credential("志愿服务培训证书", frozenset({YOUTH}), frozenset(), date(2024, 3, 1), date(2027, 12, 31))
            ],
            availability=_avail((10, 21, 8, 18)),
            clearance=ClearanceLevel.PUBLIC,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )
    add(
        Person(
            person_id="P14",
            name="赵博",
            category=PersonnelCategory.EXPERT,
            organization="北辰外国语大学",
            service_types={CONFERENCE},
            language_pairs=[ZH_RU],
            credentials=[
                Credential("CATTI一级口译", frozenset({CONFERENCE}), frozenset({ZH_RU}), date(2018, 6, 1), None)
            ],
            availability=_avail((10, 20, 8, 18)),
            clearance=ClearanceLevel.CONFIDENTIAL,
            membership_valid_until=MEMBERSHIP_VALID,
        )
    )

    # 历史真实服务：反馈只能由此进入人才库
    def served(person: Person, activity_id: str, role: str, at: datetime, rating: int) -> None:
        pool.record_service(person.person_id, activity_id, role, ServiceOutcome.COMPLETED, at, rating=rating)

    served(chen_shu, "HIST-01", "英语同传", _dt(9, 5, 12), 5)
    served(chen_shu, "HIST-02", "法语同传", _dt(9, 12, 12), 5)
    served(chen_shu, "HIST-03", "英语同传", _dt(9, 19, 12), 4)
    served(gao_ran, "HIST-04", "英语讲解", _dt(9, 6, 17), 5)
    served(gao_ran, "HIST-05", "日语讲解", _dt(9, 13, 17), 4)
    served(wu_fan, "HIST-06", "法语交流助教", _dt(9, 7, 18), 5)
    served(wu_fan, "HIST-07", "法语交流助教", _dt(9, 14, 18), 5)
    served(li_xiaoman, "HIST-08", "法语交流助教", _dt(9, 15, 18), 5)
    served(pool.get("P13"), "HIST-09", "法语交流助教", _dt(9, 15, 18), 4)
    served(pool.get("P02"), "HIST-10", "法语同传", _dt(9, 8, 12), 4)
    served(sun_qian, "HIST-11", "英语讲解", _dt(9, 9, 17), 4)
    served(zheng_chuan, "HIST-12", "日语讲解", _dt(9, 2, 17), 5)
    served(zheng_chuan, "HIST-13", "日语讲解", _dt(9, 9, 17), 5)
    served(zheng_chuan, "HIST-14", "日语讲解", _dt(9, 16, 17), 5)
    served(pool.get("P14"), "HIST-15", "俄语同传", _dt(9, 10, 12), 5)
    return pool


def build_activities() -> list[Activity]:
    """三场服务样例：会议口译、公共讲解、青少年交流。"""
    forum = Activity(
        activity_id="ACT-01",
        name="国际智慧城市论坛",
        scenario="国际会议",
        service_type=CONFERENCE,
        venue="北辰国际会议中心",
        timezone="Asia/Shanghai",
        start=_dt(10, 20, 9),
        end=_dt(10, 20, 12),
        sensitivity=Sensitivity.MEDIUM,
        min_clearance=ClearanceLevel.INTERNAL,
        slots=[
            Slot("S1", "英语同传", CONFERENCE, ZH_EN, headcount=1),
            Slot("S2", "法语同传", CONFERENCE, ZH_FR, headcount=1),
        ],
        waitlist=WaitlistRule(backup_count=1, auto_promote=True),
    )
    museum = Activity(
        activity_id="ACT-02",
        name="城市博物馆外宾开放日",
        scenario="展馆讲解",
        service_type=DOCENT,
        venue="城市博物馆",
        timezone="Asia/Shanghai",
        start=_dt(10, 20, 14),
        end=_dt(10, 20, 17),
        sensitivity=Sensitivity.LOW,
        min_clearance=ClearanceLevel.PUBLIC,
        slots=[
            Slot("S3", "英语讲解", DOCENT, ZH_EN, headcount=1),
            Slot("S4", "日语讲解", DOCENT, ZH_JA, headcount=1),
        ],
        waitlist=WaitlistRule(backup_count=0, auto_promote=True),
    )
    camp = Activity(
        activity_id="ACT-03",
        name="中法青少年交流营",
        scenario="青少年交流营",
        service_type=YOUTH,
        venue="松江校区国际交流中心",
        timezone="Asia/Shanghai",
        start=_dt(10, 21, 9),
        end=_dt(10, 21, 17),
        sensitivity=Sensitivity.LOW,
        min_clearance=ClearanceLevel.PUBLIC,
        allow_minors=True,
        slots=[
            Slot("S5", "法语交流助教", YOUTH, ZH_FR, headcount=2),
        ],
        waitlist=WaitlistRule(backup_count=1, auto_promote=True),
    )
    return [forum, museum, camp]
