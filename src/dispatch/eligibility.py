"""岗位资格校验：每个结论都附带可解释的理由。

evaluate 是系统里唯一的资格判断入口，派单、接受、候补递补、
改期复核都走这里，保证“为什么能用 / 为什么不能用”口径一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

from .enums import (
    CLEARANCE_LABELS,
    MINOR_BLOCKED_CONTENT,
    AuthorizationKind,
    Sensitivity,
)
from .models import Activity, Commitment, Person, Slot, overlaps, same_pair


@dataclass
class Eligibility:
    """校验结果：reasons 用于值守表解释，violations 用于拒绝留痕。"""

    reasons: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def evaluate(
    person: Person,
    activity: Activity,
    slot: Slot,
    commitments: tuple[Commitment, ...] | list[Commitment] = (),
    on: date | None = None,
) -> Eligibility:
    """逐项校验人员能否承担岗位。

    on 默认为活动开始日期，用于判断证书、授权与单位名单是否在有效期内。
    """
    on = on or activity.start.date()
    tz = ZoneInfo(activity.timezone)
    start, end = activity.start, activity.end

    def fmt(moment) -> str:
        return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M")

    reasons: list[str] = []
    violations: list[str] = []

    # 在库状态
    if not person.active:
        violations.append(f"人才库已停用：{person.deactivated_reason or '未说明原因'}")

    # 所属单位名单
    if person.membership_valid_until is None:
        reasons.append(f"所属单位「{person.organization}」名单长期有效")
    elif person.membership_valid_until >= on:
        reasons.append(f"所属单位「{person.organization}」名单有效（至 {person.membership_valid_until}）")
    else:
        violations.append(
            f"所属单位「{person.organization}」名单已失效（有效期至 {person.membership_valid_until}）"
        )

    # 服务类型
    if slot.service_type in person.service_types:
        reasons.append(f"已登记服务类型：{slot.service_type.value}")
    else:
        violations.append(f"未登记服务类型：{slot.service_type.value}")

    # 语种方向
    pair = slot.language_pair
    if pair is None:
        reasons.append("岗位不限语种")
    elif any(same_pair(p, pair) for p in person.language_pairs):
        reasons.append(f"语种方向匹配：{pair}")
    else:
        violations.append(f"语种方向不符：岗位需要 {pair}")

    # 能力证明：按活动日期判断是否过期，过期证明一律不可用
    usable = [
        c
        for c in person.credentials
        if c.supports(slot.service_type, pair) and c.is_valid(on)
    ]
    if usable:
        cred = max(usable, key=lambda c: c.expires_on or date.max)
        expiry = f"有效期至 {cred.expires_on}" if cred.expires_on else "长期有效"
        reasons.append(f"持有效能力证明：{cred.name}（{expiry}）")
    else:
        expired = [c for c in person.credentials if c.supports(slot.service_type, pair)]
        if expired:
            names = "、".join(f"{c.name}（{c.expires_on} 到期）" for c in expired)
            violations.append(f"能力证明已过期：{names}")
        else:
            need = slot.service_type.value + (f"／{pair}" if pair else "")
            violations.append(f"缺少有效能力证明：{need}")

    # 保密级别
    required = slot.min_clearance or activity.min_clearance
    if person.clearance >= required:
        reasons.append(
            f"保密级别{CLEARANCE_LABELS[person.clearance]}，满足岗位要求的{CLEARANCE_LABELS[required]}"
        )
    else:
        violations.append(
            f"保密级别不足：岗位要求{CLEARANCE_LABELS[required]}，本人为{CLEARANCE_LABELS[person.clearance]}"
        )

    # 可用时段（跨时区统一换算后比较）
    if any(w.covers(start, end) for w in person.availability):
        reasons.append(f"可用时段覆盖 {fmt(start)}–{fmt(end)}（{activity.timezone}）")
    else:
        violations.append(f"可用时段不覆盖活动时间 {fmt(start)}–{fmt(end)}（{activity.timezone}）")

    # 未成年志愿者：双授权缺一不可，且避开不适宜内容
    if person.is_minor(on):
        minor_block = len(violations)
        if not activity.allow_minors:
            violations.append("活动不接收未成年志愿者")
        blocked = sorted(activity.content_flags & MINOR_BLOCKED_CONTENT)
        if blocked:
            violations.append(f"活动内容不适宜未成年人：{'、'.join(blocked)}")
        if activity.sensitivity >= Sensitivity.HIGH:
            violations.append("高敏感活动不安排未成年志愿者")
        guardian = person.valid_authorization(AuthorizationKind.GUARDIAN, on)
        school = person.valid_authorization(AuthorizationKind.SCHOOL, on)
        if guardian is None:
            violations.append("缺少有效监护人授权")
        if school is None:
            violations.append("缺少有效学校授权")
        if len(violations) == minor_block:
            reasons.append(f"监护人授权有效（至 {guardian.expires_on}）")
            reasons.append(f"学校授权有效（至 {school.expires_on}）")
            reasons.append("活动内容适宜未成年人")

    # 时间、地点与职责冲突
    conflict_free = True
    for c in commitments:
        if not overlaps(start, end, c.start, c.end):
            continue
        conflict_free = False
        if c.activity_id == activity.activity_id:
            violations.append(f"职责冲突：与同一活动「{c.activity_name}」的「{c.role}」岗位时段重叠")
        elif c.venue != activity.venue:
            violations.append(
                f"地点冲突：{fmt(start)}–{fmt(end)} 无法同时在「{activity.venue}」与「{c.venue}」（{c.role}）值守"
            )
        else:
            violations.append(f"时间冲突：与「{c.activity_name}」的「{c.role}」时段重叠")
    if conflict_free:
        reasons.append("无时间、地点和职责冲突")

    return Eligibility(reasons=reasons, violations=violations)
