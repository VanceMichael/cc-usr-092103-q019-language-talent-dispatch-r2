"""调度后台使用的枚举与常量。"""

from __future__ import annotations

from enum import Enum, IntEnum


class ServiceType(str, Enum):
    """语言服务的三种岗位类型。"""

    CONFERENCE_INTERPRETATION = "会议口译"
    PUBLIC_DOCENT = "公共讲解"
    YOUTH_EXCHANGE = "青少年交流"


class PersonnelCategory(str, Enum):
    """人才库中的三类人员。"""

    EXPERT = "专家"
    TRANSLATOR = "翻译人员"
    VOLUNTEER = "志愿者"


class ClearanceLevel(IntEnum):
    """人员保密级别，数值越大可承接越敏感的活动。"""

    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3


class Sensitivity(IntEnum):
    """活动敏感程度。"""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


class AuthorizationKind(str, Enum):
    """未成年志愿者需要的两类授权。"""

    GUARDIAN = "监护人授权"
    SCHOOL = "学校授权"


class ServiceOutcome(str, Enum):
    """一次真实服务的结果。"""

    COMPLETED = "已完成"
    NO_SHOW = "缺席"


class OfferKind(str, Enum):
    """派单类型：正选或候补。"""

    PRIMARY = "正选"
    STANDBY = "候补"


class OfferState(str, Enum):
    PENDING = "待回复"
    ACCEPTED = "已接受"
    REJECTED = "已拒绝"
    EXPIRED = "已过期"


class AssignmentState(str, Enum):
    STANDBY = "候补待岗"
    CONFIRMED = "已确认"
    COMPLETED = "已完成"
    NO_SHOW = "缺席"
    REVOKED = "已撤销"


ADULT_AGE = 18

# 含以下任一内容标签的活动不安排未成年志愿者。
MINOR_BLOCKED_CONTENT = frozenset({"成人议题", "政治敏感", "高风险环节"})

CLEARANCE_LABELS = {
    ClearanceLevel.PUBLIC: "公开",
    ClearanceLevel.INTERNAL: "内部",
    ClearanceLevel.CONFIDENTIAL: "机密",
}

SENSITIVITY_LABELS = {
    Sensitivity.LOW: "低",
    Sensitivity.MEDIUM: "中",
    Sensitivity.HIGH: "高",
}
