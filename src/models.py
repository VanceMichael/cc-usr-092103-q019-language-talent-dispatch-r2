"""涉外语言服务调度的领域模型。

人员侧维护语种方向、能力证明、服务类型、可用时段、所属单位、
保密级别和历史反馈；活动侧记录场景、地点、时区、敏感程度与候补规则。
未成年志愿者须同时持有监护人与学校授权，并避开不适合内容。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum


def parse_dt(value: str) -> datetime:
    """解析 ISO 8601 时间并统一为 UTC，便于跨时区比较。"""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"时间缺少时区信息: {value}")
    return dt.astimezone(timezone.utc)


class ServiceType(str, Enum):
    """服务类型（岗位职责）。"""

    CONFERENCE_INTERPRETING = "会议口译"
    PUBLIC_GUIDING = "公共讲解"
    YOUTH_EXCHANGE = "青少年交流"


class Clearance(IntEnum):
    """保密级别，数值越大级别越高。"""

    PUBLIC = 1  # 公开
    INTERNAL = 2  # 内部
    CONFIDENTIAL = 3  # 机密


class ContentRating(str, Enum):
    """活动内容适宜性。"""

    ALL_AGES = "适宜全体"
    ADULT = "成人议题"
    SENSITIVE = "敏感议题"


# 未成年人不得参与的内容级别
MINOR_FORBIDDEN_RATINGS = {ContentRating.ADULT, ContentRating.SENSITIVE}


class AssignmentState(str, Enum):
    OFFERED = "已邀约"
    ACCEPTED = "已接受"
    REJECTED = "已拒绝"
    CONFIRMED = "已确认"
    REVOKED = "已撤销"
    CANCELLED = "已取消"


@dataclass
class Certification:
    """能力证明，带有效期；过期证书不得作为派单依据。"""

    cert_id: str
    name: str
    language_pair: str  # 如 "zh-en"
    issued: str
    expires: str
    verified: bool = True

    def valid_at(self, moment: datetime) -> bool:
        return self.verified and parse_dt(self.issued) <= moment < parse_dt(self.expires)


@dataclass
class Authorization:
    """授权书（监护人或学校），带有效期。"""

    kind: str  # "guardian" 或 "school"
    issuer: str
    expires: str

    def valid_at(self, moment: datetime) -> bool:
        return moment < parse_dt(self.expires)


@dataclass
class AvailabilityWindow:
    """可用时段，start/end 为带时区的 ISO 时间。"""

    start: str
    end: str

    def covers(self, start: datetime, end: datetime) -> bool:
        return parse_dt(self.start) <= start and end <= parse_dt(self.end)


@dataclass
class Feedback:
    """历史反馈，只能由真实完成的服务写入。"""

    event_id: str
    rating: int  # 1-5
    comment: str
    recorded_at: str


@dataclass
class Person:
    """人才库成员：专家、翻译人员或志愿者。"""

    person_id: str
    name: str
    organization: str  # 所属单位（五所合作高校之一或外部机构）
    category: str  # 专家 / 翻译人员 / 志愿者
    language_pairs: list[str]
    service_types: list[ServiceType]
    clearance: Clearance
    is_minor: bool = False
    certifications: list[Certification] = field(default_factory=list)
    availability: list[AvailabilityWindow] = field(default_factory=list)
    authorizations: list[Authorization] = field(default_factory=list)
    feedback: list[Feedback] = field(default_factory=list)
    active: bool = True

    def has_valid_cert_for(self, language_pair: str, moment: datetime) -> Certification | None:
        for cert in self.certifications:
            if cert.language_pair == language_pair and cert.valid_at(moment):
                return cert
        return None

    def is_available(self, start: datetime, end: datetime) -> bool:
        return any(w.covers(start, end) for w in self.availability)

    def minor_cleared(self, moment: datetime) -> bool:
        """未成年人须同时持有有效的监护人与学校授权。"""
        kinds = {a.kind for a in self.authorizations if a.valid_at(moment)}
        return {"guardian", "school"}.issubset(kinds)

    def average_rating(self) -> float:
        if not self.feedback:
            return 0.0
        return sum(f.rating for f in self.feedback) / len(self.feedback)


@dataclass
class WaitlistRule:
    """候补规则：同时邀约人数上限与候补排序方式。"""

    max_concurrent_offers: int = 3
    rank_by: str = "rating"  # rating / seniority


@dataclass
class Post:
    """活动中的一个值守岗位。"""

    post_id: str
    event_id: str
    scenario: str  # 场景，如 开幕式 / 展厅讲解 / 校园结对
    service_type: ServiceType
    language_pair: str
    location: str
    timezone: str  # 活动当地时区，如 Asia/Shanghai
    start: str
    end: str
    sensitivity: Clearance
    content_rating: ContentRating = ContentRating.ALL_AGES
    waitlist_rule: WaitlistRule = field(default_factory=WaitlistRule)

    def window_utc(self) -> tuple[datetime, datetime]:
        return parse_dt(self.start), parse_dt(self.end)


@dataclass
class Assignment:
    """一次派单及其全生命周期状态。"""

    assignment_id: str
    post_id: str
    person_id: str
    state: AssignmentState
    reasons: list[str] = field(default_factory=list)  # 可解释：为何由该人员承担
    offered_at: str = ""
    decided_at: str = ""
    note: str = ""
