"""值守表：汇总最终安排，并在导出前独立复核冲突。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Mapping

from .models import Activity, overlaps


@dataclass
class RosterEntry:
    """值守表中的一行：谁在何时何地承担哪个岗位，以及完整理由。"""

    activity_id: str
    activity_name: str
    slot_id: str
    role: str
    person_id: str
    person_name: str
    organization: str
    venue: str
    timezone: str
    start: datetime
    end: datetime
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "activity_id": self.activity_id,
            "activity_name": self.activity_name,
            "slot_id": self.slot_id,
            "role": self.role,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "organization": self.organization,
            "venue": self.venue,
            "timezone": self.timezone,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "reasons": list(self.reasons),
        }


@dataclass
class SlotGap:
    """尚未排满的岗位；缺口必须提前摆到桌面上，而不是到现场才发现。"""

    activity_id: str
    activity_name: str
    slot_id: str
    role: str
    missing: int
    standby_count: int

    def to_dict(self) -> dict:
        return {
            "activity_id": self.activity_id,
            "activity_name": self.activity_name,
            "slot_id": self.slot_id,
            "role": self.role,
            "missing": self.missing,
            "standby_count": self.standby_count,
        }


@dataclass
class Conflict:
    kind: str  # 时间冲突 / 地点冲突 / 职责冲突
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


def validate_roster(
    entries: list[RosterEntry], activities: Mapping[str, Activity] | None = None
) -> list[Conflict]:
    """独立复核值守表：同一人时段重叠、跨地点重叠、同活动多岗、岗位超编。"""
    conflicts: list[Conflict] = []

    by_person: dict[str, list[RosterEntry]] = {}
    for e in entries:
        by_person.setdefault(e.person_id, []).append(e)
    for person_entries in by_person.values():
        for e1, e2 in combinations(person_entries, 2):
            if not overlaps(e1.start, e1.end, e2.start, e2.end):
                continue
            if e1.activity_id == e2.activity_id:
                conflicts.append(
                    Conflict("职责冲突", f"{e1.person_name} 在同一活动「{e1.activity_name}」同时承担「{e1.role}」与「{e2.role}」")
                )
            elif e1.venue != e2.venue:
                conflicts.append(
                    Conflict("地点冲突", f"{e1.person_name} 时段重叠却分处「{e1.venue}」与「{e2.venue}」")
                )
            else:
                conflicts.append(
                    Conflict("时间冲突", f"{e1.person_name} 在「{e1.venue}」的「{e1.role}」与「{e2.role}」时段重叠")
                )

    if activities:
        by_slot: dict[tuple[str, str], list[RosterEntry]] = {}
        for e in entries:
            by_slot.setdefault((e.activity_id, e.slot_id), []).append(e)
        for (activity_id, slot_id), slot_entries in by_slot.items():
            activity = activities.get(activity_id)
            if activity is None:
                continue
            slot = activity.slot(slot_id)
            if len(slot_entries) > slot.headcount:
                conflicts.append(
                    Conflict(
                        "职责冲突",
                        f"「{activity.name} / {slot.role}」岗位超编：{len(slot_entries)}/{slot.headcount}",
                    )
                )
    return conflicts


@dataclass
class Roster:
    """最终值守表：每个岗位都有入选理由，且通过冲突复核。"""

    entries: list[RosterEntry] = field(default_factory=list)
    standbys: dict[str, list[str]] = field(default_factory=dict)
    gaps: list[SlotGap] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "standbys": {k: list(v) for k, v in self.standbys.items()},
            "gaps": [g.to_dict() for g in self.gaps],
            "conflicts": [c.to_dict() for c in self.conflicts],
        }

    def render(self) -> str:
        lines = ["========== 值守表 =========="]
        current_activity = None
        for e in self.entries:
            if e.activity_name != current_activity:
                current_activity = e.activity_name
                lines.append(
                    f"【{e.activity_name}】{e.venue}｜"
                    f"{e.start.strftime('%Y-%m-%d %H:%M')}–{e.end.strftime('%H:%M')}（{e.timezone}）"
                )
            lines.append(f"  · {e.role} — {e.person_name}（{e.organization}）")
            lines.append(f"      依据：{'；'.join(e.reasons)}")
        if self.standbys:
            lines.append("—— 候补 ——")
            for key, names in self.standbys.items():
                lines.append(f"  · {key}：{'、'.join(names)}")
        if self.gaps:
            lines.append("—— 缺口 ——")
            for g in self.gaps:
                lines.append(f"  · 「{g.activity_name}」{g.role} 缺 {g.missing} 人（候补 {g.standby_count} 人）")
        if self.conflicts:
            lines.append("—— 冲突 ——")
            for c in self.conflicts:
                lines.append(f"  ✗ {c.kind}：{c.detail}")
        else:
            lines.append("冲突校验：无时间、地点和职责冲突 ✔")
        return "\n".join(lines)
