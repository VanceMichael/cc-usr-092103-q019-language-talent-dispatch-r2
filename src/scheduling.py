"""排班：资格校验、冲突检测与可解释匹配。

每个岗位的派单都必须能说明"为何由该人员承担"，
并保证同一人员不存在时间、地点和职责冲突。
"""

from __future__ import annotations

from datetime import datetime

from .models import (
    MINOR_FORBIDDEN_RATINGS,
    Assignment,
    AssignmentState,
    Person,
    Post,
)

# 处于这些状态的派单占用人员的时间与职责
BLOCKING_STATES = {AssignmentState.ACCEPTED, AssignmentState.CONFIRMED}


def check_eligibility(person: Person, post: Post) -> tuple[bool, list[str]]:
    """逐项校验人员能否承担岗位，返回 (是否合格, 理由列表)。

    理由同时记录通过项与否决项，用于值守表的可解释说明。
    """
    start, end = post.window_utc()
    reasons: list[str] = []
    ok = True

    if not person.active:
        return False, [f"{person.name} 已不在有效人才库中"]

    if post.service_type in person.service_types:
        reasons.append(f"具备服务类型「{post.service_type.value}」")
    else:
        reasons.append(f"缺少服务类型「{post.service_type.value}」")
        ok = False

    if post.language_pair in person.language_pairs:
        reasons.append(f"语种方向 {post.language_pair} 匹配")
    else:
        reasons.append(f"语种方向不含 {post.language_pair}")
        ok = False

    cert = person.has_valid_cert_for(post.language_pair, start)
    if cert:
        reasons.append(f"持有效能力证明 {cert.cert_id}（{cert.name}）")
    else:
        reasons.append(f"无 {post.language_pair} 的有效能力证明（或已过期）")
        ok = False

    if person.clearance >= post.sensitivity:
        reasons.append(f"保密级别 {person.clearance.name} 满足活动敏感程度 {post.sensitivity.name}")
    else:
        reasons.append(f"保密级别 {person.clearance.name} 低于活动要求 {post.sensitivity.name}")
        ok = False

    if person.is_available(start, end):
        reasons.append("可用时段覆盖活动全程")
    else:
        reasons.append("可用时段不覆盖活动全程")
        ok = False

    if person.is_minor:
        if post.content_rating in MINOR_FORBIDDEN_RATINGS:
            reasons.append(f"未成年人不得参与「{post.content_rating.value}」内容")
            ok = False
        elif person.minor_cleared(start):
            reasons.append("未成年人监护人与学校授权均有效")
        else:
            reasons.append("未成年人缺少有效的监护人和/或学校授权")
            ok = False

    return ok, reasons


def find_conflicts(
    person_id: str,
    post: Post,
    assignments: list[Assignment],
    posts: dict[str, Post],
    exclude_assignment_id: str = "",
) -> list[str]:
    """检查该人员已有的占用性派单与新岗位是否冲突（时间重叠/异地/职责重复）。"""
    start, end = post.window_utc()
    conflicts: list[str] = []
    for a in assignments:
        if a.person_id != person_id or a.state not in BLOCKING_STATES:
            continue
        if a.assignment_id == exclude_assignment_id:
            continue
        other = posts[a.post_id]
        o_start, o_end = other.window_utc()
        if start < o_end and o_start < end:
            if other.post_id == post.post_id:
                conflicts.append(f"职责冲突：已承担同一岗位 {post.post_id}")
            elif other.location != post.location:
                conflicts.append(
                    f"地点冲突：{other.event_id}（{other.location}）与 {post.event_id}（{post.location}）时间重叠"
                )
            else:
                conflicts.append(f"时间冲突：与岗位 {other.post_id} 时段重叠")
    return conflicts


def rank_candidates(candidates: list[tuple[Person, list[str]]], rank_by: str = "rating") -> list[tuple[Person, list[str]]]:
    """按候补规则排序：默认历史反馈均分高者优先，其次服务次数。"""
    if rank_by == "seniority":
        key = lambda item: (len(item[0].feedback), item[0].average_rating())
    else:
        key = lambda item: (item[0].average_rating(), len(item[0].feedback))
    return sorted(candidates, key=key, reverse=True)
