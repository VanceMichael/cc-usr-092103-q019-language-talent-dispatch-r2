"""人员、活动与派遣记录的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .enums import (
    ADULT_AGE,
    AssignmentState,
    AuthorizationKind,
    ClearanceLevel,
    OfferKind,
    OfferState,
    PersonnelCategory,
    Sensitivity,
    ServiceOutcome,
    ServiceType,
)


def as_utc(moment: datetime) -> datetime:
    """统一换算到 UTC；所有进入系统的时间都必须自带时区。"""
    if moment.tzinfo is None:
        raise ValueError("时间必须携带时区信息")
    return moment.astimezone(timezone.utc)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """两个半开区间 [start, end) 是否相交（按 UTC 比较，跨时区安全）。"""
    return as_utc(a_start) < as_utc(b_end) and as_utc(b_start) < as_utc(a_end)


@dataclass(frozen=True)
class LanguagePair:
    """语种方向；口译按双向处理，匹配时不受 source/target 顺序影响。"""

    source: str
    target: str

    def __str__(self) -> str:
        return f"{self.source}↔{self.target}"


def same_pair(a: LanguagePair, b: LanguagePair) -> bool:
    """双向语种匹配：中↔法 与 法↔中 视为同一方向。"""
    return (a.source, a.target) == (b.source, b.target) or (a.source, a.target) == (
        b.target,
        b.source,
    )


@dataclass(frozen=True)
class AvailabilityWindow:
    """一段可用时段，起止时间均带时区。"""

    start: datetime
    end: datetime

    def covers(self, start: datetime, end: datetime) -> bool:
        return as_utc(self.start) <= as_utc(start) and as_utc(end) <= as_utc(self.end)


@dataclass
class Credential:
    """能力证明；expires_on 为 None 表示长期有效。过期证明不得用于派单。"""

    name: str
    service_types: frozenset[ServiceType]
    language_pairs: frozenset[LanguagePair]  # 空集表示不限语种
    issued_on: date
    expires_on: date | None

    def is_valid(self, on: date) -> bool:
        return self.issued_on <= on and (self.expires_on is None or on <= self.expires_on)

    def supports(self, service_type: ServiceType, pair: LanguagePair | None) -> bool:
        if service_type not in self.service_types:
            return False
        if pair is None:
            return True
        return not self.language_pairs or any(same_pair(p, pair) for p in self.language_pairs)


@dataclass
class Authorization:
    """监护人或学校出具的授权，带有效期。"""

    kind: AuthorizationKind
    granted_by: str
    granted_on: date
    expires_on: date
    note: str = ""

    def is_valid(self, on: date) -> bool:
        return self.granted_on <= on <= self.expires_on


@dataclass
class Feedback:
    """一次真实服务产生的反馈；只能由 TalentPool.record_service 写入。"""

    activity_id: str
    rating: int  # 1..5
    comment: str
    recorded_at: datetime
    service_record_id: str


@dataclass
class ServiceRecord:
    """真实服务台账，是更新人才库的唯一依据。"""

    record_id: str
    activity_id: str
    slot_role: str
    outcome: ServiceOutcome
    recorded_at: datetime


@dataclass
class Person:
    """人才库成员。

    feedback 与 service_history 不允许直接改写，
    只能由 TalentPool.record_service 依据真实服务追加。
    """

    person_id: str
    name: str
    category: PersonnelCategory
    organization: str  # 所属单位（五所合作高校之一或外部）
    service_types: set[ServiceType]
    language_pairs: list[LanguagePair]
    credentials: list[Credential]
    availability: list[AvailabilityWindow]
    clearance: ClearanceLevel
    birth_date: date | None = None
    authorizations: list[Authorization] = field(default_factory=list)
    membership_valid_until: date | None = None  # 所属单位名单有效期，None 表示长期
    feedback: list[Feedback] = field(default_factory=list)
    service_history: list[ServiceRecord] = field(default_factory=list)
    active: bool = True
    deactivated_reason: str | None = None

    def is_minor(self, on: date) -> bool:
        if self.birth_date is None:
            return False
        age = (
            on.year
            - self.birth_date.year
            - ((on.month, on.day) < (self.birth_date.month, self.birth_date.day))
        )
        return age < ADULT_AGE

    def valid_authorization(self, kind: AuthorizationKind, on: date) -> Authorization | None:
        for auth in self.authorizations:
            if auth.kind == kind and auth.is_valid(on):
                return auth
        return None

    def average_rating(self) -> float | None:
        if not self.feedback:
            return None
        return sum(f.rating for f in self.feedback) / len(self.feedback)

    def completed_count(self) -> int:
        return sum(1 for r in self.service_history if r.outcome is ServiceOutcome.COMPLETED)


@dataclass
class Slot:
    """活动下的一个岗位；时间沿用所属活动的起止时间。"""

    slot_id: str
    role: str
    service_type: ServiceType
    language_pair: LanguagePair | None = None  # None 表示不限语种
    headcount: int = 1
    min_clearance: ClearanceLevel | None = None  # None 沿用活动要求


@dataclass
class WaitlistRule:
    """候补规则：每个岗位保留多少候补名额，缺席时是否自动递补。"""

    backup_count: int = 1
    auto_promote: bool = True


@dataclass
class Activity:
    """一场涉外活动。"""

    activity_id: str
    name: str
    scenario: str  # 场景，如 国际会议 / 展馆讲解 / 青少年交流营
    service_type: ServiceType
    venue: str  # 地点
    timezone: str  # IANA 时区名
    start: datetime
    end: datetime
    sensitivity: Sensitivity
    min_clearance: ClearanceLevel
    slots: list[Slot] = field(default_factory=list)
    waitlist: WaitlistRule = field(default_factory=WaitlistRule)
    allow_minors: bool = False
    content_flags: frozenset[str] = frozenset()
    status: str = "开放"

    def slot(self, slot_id: str) -> Slot:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        raise KeyError(f"活动 {self.activity_id} 中不存在岗位 {slot_id}")


@dataclass(frozen=True)
class Commitment:
    """已确认或候补的值守承诺，用于冲突检查。"""

    activity_id: str
    activity_name: str
    role: str
    venue: str
    start: datetime
    end: datetime


@dataclass
class Offer:
    """一次派单；接受与拒绝都会留痕。"""

    offer_id: str
    activity_id: str
    slot_id: str
    person_id: str
    kind: OfferKind
    state: OfferState
    created_at: datetime
    responded_at: datetime | None = None
    response_reason: str = ""


@dataclass
class Assignment:
    """一份值守安排；reasons 记录该人员入选的完整理由。"""

    assignment_id: str
    activity_id: str
    slot_id: str
    person_id: str
    state: AssignmentState
    reasons: list[str]
    created_at: datetime
    note: str = ""
