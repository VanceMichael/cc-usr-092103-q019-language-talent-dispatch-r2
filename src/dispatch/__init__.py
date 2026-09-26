"""语言服务调度后台。

- 人员侧：语种方向、能力证明、服务类型、可用时段、所属单位、保密级别、历史反馈
- 活动侧：场景、地点、时区、敏感程度、候补规则
- 派单留痕：每次接受与拒绝都写入事件日志
- 影响重算：缺席、改期、临时小语种需求即时重排
- 人才库：只依据真实服务更新，定期清理过期证明与失效名单
"""

from .eligibility import Eligibility, evaluate
from .engine import CandidateView, DispatchEngine, Event, ImpactReport
from .enums import (
    ADULT_AGE,
    CLEARANCE_LABELS,
    MINOR_BLOCKED_CONTENT,
    SENSITIVITY_LABELS,
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
from .models import (
    Activity,
    Assignment,
    Authorization,
    AvailabilityWindow,
    Commitment,
    Credential,
    Feedback,
    LanguagePair,
    Offer,
    Person,
    ServiceRecord,
    Slot,
    WaitlistRule,
    overlaps,
    same_pair,
)
from .pool import PruneReport, TalentPool
from .roster import Conflict, Roster, RosterEntry, SlotGap, validate_roster

__all__ = [
    "ADULT_AGE",
    "CLEARANCE_LABELS",
    "MINOR_BLOCKED_CONTENT",
    "SENSITIVITY_LABELS",
    "Activity",
    "Assignment",
    "AssignmentState",
    "Authorization",
    "AuthorizationKind",
    "AvailabilityWindow",
    "CandidateView",
    "ClearanceLevel",
    "Commitment",
    "Conflict",
    "Credential",
    "DispatchEngine",
    "Eligibility",
    "Event",
    "Feedback",
    "ImpactReport",
    "LanguagePair",
    "Offer",
    "OfferKind",
    "OfferState",
    "Person",
    "PersonnelCategory",
    "PruneReport",
    "Roster",
    "RosterEntry",
    "Sensitivity",
    "ServiceOutcome",
    "ServiceRecord",
    "ServiceType",
    "Slot",
    "SlotGap",
    "TalentPool",
    "WaitlistRule",
    "evaluate",
    "overlaps",
    "same_pair",
    "validate_roster",
]
