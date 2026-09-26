"""调度引擎：派单、接受/拒绝留痕，以及缺席、改期、临时需求后的影响重算。

设计要点：
- 每次接受与拒绝都写入 append-only 事件日志，可随时按人/按活动回溯；
- 接受派单时重新校验资格，防止派单后情况变化（证书过期、时段被占）；
- 缺席、改期、临时小语种需求都会触发 _refill 重算：先递补候补，再重新派单，
  找不到人就把缺口和影响明确报出来，而不是等到现场才暴露。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .eligibility import evaluate
from .enums import AssignmentState, OfferKind, OfferState, ServiceOutcome
from .models import (
    Activity,
    Assignment,
    Commitment,
    LanguagePair,
    Offer,
    Person,
    Slot,
    same_pair,
)
from .pool import TalentPool
from .roster import Roster, RosterEntry, SlotGap, validate_roster


@dataclass
class Event:
    """一条调度事件；seq 单调递增，日志只追加不修改。"""

    seq: int
    at: datetime
    kind: str
    detail: str
    person_id: str | None = None
    activity_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "at": self.at.isoformat(),
            "kind": self.kind,
            "detail": self.detail,
            "person_id": self.person_id,
            "activity_id": self.activity_id,
        }


@dataclass
class CandidateView:
    person: Person
    reasons: list[str]
    score: tuple


@dataclass
class ImpactReport:
    """一次变动重算后的影响：谁被撤销、谁被递补、新发了哪些派单、还有哪些缺口。"""

    trigger: str
    revoked: list[Assignment] = field(default_factory=list)
    promoted: list[Assignment] = field(default_factory=list)
    new_offers: list[Offer] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def merge(self, other: "ImpactReport") -> "ImpactReport":
        self.revoked.extend(other.revoked)
        self.promoted.extend(other.promoted)
        self.new_offers.extend(other.new_offers)
        self.gaps.extend(other.gaps)
        return self

    def summary(self) -> str:
        parts = [f"触发：{self.trigger}"]
        if self.revoked:
            parts.append(f"撤销 {len(self.revoked)} 人")
        if self.promoted:
            parts.append(f"递补 {len(self.promoted)} 人")
        if self.new_offers:
            parts.append(f"新派单 {len(self.new_offers)} 份")
        if self.gaps:
            parts.append("缺口：" + "；".join(self.gaps))
        return "，".join(parts)


class DispatchEngine:
    """语言服务调度引擎。"""

    def __init__(self, pool: TalentPool) -> None:
        self.pool = pool
        self.activities: dict[str, Activity] = {}
        self.offers: dict[str, Offer] = {}
        self.assignments: dict[str, Assignment] = {}
        self.events: list[Event] = []
        self._offer_seq = 0
        self._assignment_seq = 0

    # ---------- 事件留痕 ----------

    def _log(
        self,
        at: datetime,
        kind: str,
        detail: str,
        person_id: str | None = None,
        activity_id: str | None = None,
    ) -> None:
        self.events.append(Event(len(self.events) + 1, at, kind, detail, person_id, activity_id))

    def history(
        self, person_id: str | None = None, activity_id: str | None = None
    ) -> list[Event]:
        """按人员或活动回溯全部接受与拒绝等事件。"""
        return [
            e
            for e in self.events
            if (person_id is None or e.person_id == person_id)
            and (activity_id is None or e.activity_id == activity_id)
        ]

    def export_history(self, path: str | Path) -> None:
        lines = [json.dumps(e.to_dict(), ensure_ascii=False) for e in self.events]
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------- 活动 ----------

    def open_activity(self, activity: Activity, at: datetime) -> None:
        if activity.activity_id in self.activities:
            raise ValueError(f"活动编号重复：{activity.activity_id}")
        self.activities[activity.activity_id] = activity
        self._log(
            at,
            "活动开放",
            f"「{activity.name}」{activity.scenario}，{activity.venue}，{activity.timezone}",
            activity_id=activity.activity_id,
        )

    # ---------- 候选与派单 ----------

    def _score(self, person: Person) -> tuple:
        """排序分：历史平均评分、完成次数，全部来自真实服务记录。"""
        return (person.average_rating() or 0.0, person.completed_count(), person.person_id)

    def _commitments(self, person_id: str, exclude_assignment_id: str | None = None) -> list[Commitment]:
        result = []
        for a in self.assignments.values():
            if a.person_id != person_id or a.assignment_id == exclude_assignment_id:
                continue
            if a.state not in (AssignmentState.CONFIRMED, AssignmentState.STANDBY):
                continue
            activity = self.activities[a.activity_id]
            slot = activity.slot(a.slot_id)
            result.append(
                Commitment(activity.activity_id, activity.name, slot.role, activity.venue, activity.start, activity.end)
            )
        return result

    def candidates(
        self, activity_id: str, slot_id: str, exclude: frozenset[str] = frozenset()
    ) -> list[CandidateView]:
        """当前时刻能承担该岗位的人选，按历史表现排序；exclude 用于排除缺席者等。"""
        activity = self.activities[activity_id]
        slot = activity.slot(slot_id)
        views = []
        for person in self.pool.all_active():
            if person.person_id in exclude:
                continue
            elig = evaluate(person, activity, slot, self._commitments(person.person_id))
            if elig.ok:
                views.append(CandidateView(person, elig.reasons, self._score(person)))
        views.sort(key=lambda v: v.score, reverse=True)
        return views

    def _slot_assignments(self, activity: Activity, slot: Slot) -> list[Assignment]:
        return [
            a
            for a in self.assignments.values()
            if a.activity_id == activity.activity_id and a.slot_id == slot.slot_id
        ]

    def _confirmed_count(self, activity: Activity, slot: Slot) -> int:
        return sum(
            1 for a in self._slot_assignments(activity, slot) if a.state is AssignmentState.CONFIRMED
        )

    def _standby_count(self, activity: Activity, slot: Slot) -> int:
        return sum(
            1 for a in self._slot_assignments(activity, slot) if a.state is AssignmentState.STANDBY
        )

    def _pending_offers(self, activity: Activity, slot: Slot, kind: OfferKind | None = None) -> list[Offer]:
        return [
            o
            for o in self.offers.values()
            if o.activity_id == activity.activity_id
            and o.slot_id == slot.slot_id
            and o.state is OfferState.PENDING
            and (kind is None or o.kind is kind)
        ]

    def _make_offer(
        self, activity: Activity, slot: Slot, person_id: str, kind: OfferKind, at: datetime
    ) -> Offer:
        self._offer_seq += 1
        offer = Offer(
            offer_id=f"O-{self._offer_seq:04d}",
            activity_id=activity.activity_id,
            slot_id=slot.slot_id,
            person_id=person_id,
            kind=kind,
            state=OfferState.PENDING,
            created_at=at,
        )
        self.offers[offer.offer_id] = offer
        person = self.pool.get(person_id)
        self._log(
            at,
            "派单",
            f"向 {person.name} 发出「{activity.name} / {slot.role}」{kind.value}派单",
            person_id,
            activity.activity_id,
        )
        return offer

    def dispatch(
        self, activity_id: str, slot_id: str, at: datetime, exclude: frozenset[str] = frozenset()
    ) -> list[Offer]:
        """自动派单：按排名补足正选名额，再按候补规则发候补派单。"""
        activity = self.activities[activity_id]
        slot = activity.slot(slot_id)
        busy = {o.person_id for o in self._pending_offers(activity, slot)}
        busy |= {
            a.person_id
            for a in self._slot_assignments(activity, slot)
            if a.state in (AssignmentState.CONFIRMED, AssignmentState.STANDBY)
        }
        need_primary = (
            slot.headcount
            - self._confirmed_count(activity, slot)
            - len(self._pending_offers(activity, slot, OfferKind.PRIMARY))
        )
        need_backup = (
            activity.waitlist.backup_count
            - self._standby_count(activity, slot)
            - len(self._pending_offers(activity, slot, OfferKind.STANDBY))
        )
        offers = []
        for view in self.candidates(activity_id, slot_id, exclude=exclude):
            pid = view.person.person_id
            if pid in busy:
                continue
            if need_primary > 0:
                kind, need_primary = OfferKind.PRIMARY, need_primary - 1
            elif need_backup > 0:
                kind, need_backup = OfferKind.STANDBY, need_backup - 1
            else:
                break
            offers.append(self._make_offer(activity, slot, pid, kind, at))
        return offers

    def offer_to(
        self, activity_id: str, slot_id: str, person_ids: list[str], at: datetime
    ) -> list[Offer]:
        """多人同时派单：指定人选同时发出正选派单，名额竞争在接受时解决。"""
        activity = self.activities[activity_id]
        slot = activity.slot(slot_id)
        offers = []
        for pid in person_ids:
            person = self.pool.get(pid)
            elig = evaluate(person, activity, slot, self._commitments(pid))
            if not elig.ok:
                self._log(
                    at,
                    "派单校验未通过",
                    f"{person.name} 不能承担「{activity.name} / {slot.role}」：{'；'.join(elig.violations)}",
                    pid,
                    activity.activity_id,
                )
                continue
            offers.append(self._make_offer(activity, slot, pid, OfferKind.PRIMARY, at))
        return offers

    def respond(self, offer_id: str, accept: bool, at: datetime, reason: str = "") -> Offer:
        """登记一次接受或拒绝；接受时重新校验资格并解决名额竞争。"""
        offer = self.offers.get(offer_id)
        if offer is None:
            raise KeyError(f"派单不存在：{offer_id}")
        if offer.state is not OfferState.PENDING:
            raise ValueError(f"派单 {offer_id} 已处理（{offer.state.value}）")
        activity = self.activities[offer.activity_id]
        slot = activity.slot(offer.slot_id)
        person = self.pool.get(offer.person_id)
        offer.responded_at = at
        label = f"「{activity.name} / {slot.role}」"

        if not accept:
            offer.state = OfferState.REJECTED
            offer.response_reason = reason or "本人拒绝"
            self._log(at, "拒绝", f"{person.name} 拒绝{label}：{offer.response_reason}", person.person_id, activity.activity_id)
            return offer

        elig = evaluate(person, activity, slot, self._commitments(person.person_id))
        if not elig.ok:
            offer.state = OfferState.REJECTED
            offer.response_reason = "；".join(elig.violations)
            self._log(
                at,
                "拒绝",
                f"{person.name} 接受{label}未通过校验：{offer.response_reason}",
                person.person_id,
                activity.activity_id,
            )
            return offer

        if self._confirmed_count(activity, slot) < slot.headcount:
            offer.state = OfferState.ACCEPTED
            offer.response_reason = reason or "本人接受"
            self._confirm(offer, elig.reasons, at, AssignmentState.CONFIRMED)
            self._log(at, "接受", f"{person.name} 接受{label}", person.person_id, activity.activity_id)
            self._log(at, "确认", f"{person.name} 确认值守{label}", person.person_id, activity.activity_id)
            self._close_overflow(activity, slot, at)
            return offer

        if self._standby_count(activity, slot) < activity.waitlist.backup_count:
            offer.state = OfferState.ACCEPTED
            offer.response_reason = reason or "正选名额已满，转为候补"
            self._confirm(
                offer, elig.reasons + ["作为候补值守"], at, AssignmentState.STANDBY
            )
            self._log(at, "候补确认", f"{person.name} 成为{label}候补", person.person_id, activity.activity_id)
            self._close_overflow(activity, slot, at)
            return offer

        offer.state = OfferState.REJECTED
        offer.response_reason = "岗位名额已满"
        self._log(at, "拒绝", f"{person.name} 接受{label}时名额已满", person.person_id, activity.activity_id)
        return offer

    def _confirm(
        self, offer: Offer, reasons: list[str], at: datetime, state: AssignmentState
    ) -> Assignment:
        self._assignment_seq += 1
        assignment = Assignment(
            assignment_id=f"A-{self._assignment_seq:04d}",
            activity_id=offer.activity_id,
            slot_id=offer.slot_id,
            person_id=offer.person_id,
            state=state,
            reasons=list(reasons),
            created_at=at,
        )
        self.assignments[assignment.assignment_id] = assignment
        return assignment

    def _close_overflow(self, activity: Activity, slot: Slot, at: datetime) -> None:
        """正选与候补名额都占满后，其余待回复派单自动失效并留痕。"""
        primary_full = self._confirmed_count(activity, slot) >= slot.headcount
        standby_full = self._standby_count(activity, slot) >= activity.waitlist.backup_count
        if not (primary_full and standby_full):
            return
        for offer in self._pending_offers(activity, slot):
            offer.state = OfferState.REJECTED
            offer.responded_at = at
            offer.response_reason = "岗位名额已满"
            person = self.pool.get(offer.person_id)
            self._log(
                at,
                "拒绝",
                f"{person.name} 的派单因「{activity.name} / {slot.role}」名额已满失效",
                offer.person_id,
                activity.activity_id,
            )

    # ---------- 缺席、改期与临时需求的影响重算 ----------

    def _refill(
        self,
        activity: Activity,
        slot: Slot,
        at: datetime,
        trigger: str,
        exclude: frozenset[str] = frozenset(),
    ) -> ImpactReport:
        """名额出现缺口时重算：先递补候补，再重新派单，最后如实报告缺口。"""
        report = ImpactReport(trigger)
        if activity.waitlist.auto_promote:
            while self._confirmed_count(activity, slot) < slot.headcount:
                standbys = [
                    a
                    for a in self._slot_assignments(activity, slot)
                    if a.state is AssignmentState.STANDBY
                ]
                if not standbys:
                    break
                best = max(standbys, key=lambda a: self._score(self.pool.get(a.person_id)))
                person = self.pool.get(best.person_id)
                elig = evaluate(
                    person,
                    activity,
                    slot,
                    self._commitments(person.person_id, exclude_assignment_id=best.assignment_id),
                )
                if not elig.ok:
                    best.state = AssignmentState.REVOKED
                    best.note = "；".join(elig.violations)
                    self._log(
                        at,
                        "撤销",
                        f"候补 {person.name} 转正前校验未通过：{best.note}",
                        person.person_id,
                        activity.activity_id,
                    )
                    report.revoked.append(best)
                    continue
                best.state = AssignmentState.CONFIRMED
                best.reasons = best.reasons + ["由候补递补"]
                self._log(
                    at,
                    "候补递补",
                    f"{person.name} 递补确认「{activity.name} / {slot.role}」",
                    person.person_id,
                    activity.activity_id,
                )
                report.promoted.append(best)
        missing = slot.headcount - self._confirmed_count(activity, slot)
        if missing > 0:
            offers = self.dispatch(activity.activity_id, slot.slot_id, at, exclude=exclude)
            report.new_offers.extend(offers)
            if not offers:
                report.gaps.append(
                    f"「{activity.name}」{slot.role} 尚缺 {missing} 人，人才库暂无可用人选"
                )
        return report

    def report_absence(
        self, assignment_id: str, at: datetime, reason: str = "无故缺席"
    ) -> ImpactReport:
        """登记缺席：写入真实服务记录，并立即重算该岗位。"""
        assignment = self.assignments.get(assignment_id)
        if assignment is None:
            raise KeyError(f"值守安排不存在：{assignment_id}")
        if assignment.state is not AssignmentState.CONFIRMED:
            raise ValueError("只有已确认的值守才能登记缺席")
        activity = self.activities[assignment.activity_id]
        slot = activity.slot(assignment.slot_id)
        person = self.pool.get(assignment.person_id)
        assignment.state = AssignmentState.NO_SHOW
        assignment.note = reason
        self._log(
            at,
            "缺席",
            f"{person.name} 缺席「{activity.name} / {slot.role}」：{reason}",
            person.person_id,
            activity.activity_id,
        )
        self.pool.record_service(
            person.person_id, activity.activity_id, slot.role, ServiceOutcome.NO_SHOW, at, comment=reason
        )
        # 缺席者本人不得再参与本岗位的补位
        return self._refill(activity, slot, at, trigger=f"{person.name} 缺席「{slot.role}」", exclude=frozenset({person.person_id}))

    def release_assignment(
        self, assignment_id: str, at: datetime, reason: str = "组织方释放"
    ) -> ImpactReport | None:
        """人工释放一份确认或候补安排；释放正选会触发重算。"""
        assignment = self.assignments.get(assignment_id)
        if assignment is None:
            raise KeyError(f"值守安排不存在：{assignment_id}")
        if assignment.state not in (AssignmentState.CONFIRMED, AssignmentState.STANDBY):
            raise ValueError("只有已确认或候补的值守才能释放")
        activity = self.activities[assignment.activity_id]
        slot = activity.slot(assignment.slot_id)
        person = self.pool.get(assignment.person_id)
        was_confirmed = assignment.state is AssignmentState.CONFIRMED
        assignment.state = AssignmentState.REVOKED
        assignment.note = reason
        self._log(
            at,
            "释放",
            f"{person.name} 的「{activity.name} / {slot.role}」值守已释放：{reason}",
            person.person_id,
            activity.activity_id,
        )
        if was_confirmed:
            return self._refill(activity, slot, at, trigger=f"释放 {person.name} 的「{slot.role}」")
        return None

    def reschedule(
        self,
        activity_id: str,
        new_start: datetime,
        new_end: datetime,
        at: datetime,
        new_venue: str | None = None,
    ) -> ImpactReport:
        """活动改期：复核全部已确认/候补安排，失效的撤销并重算缺口。"""
        activity = self.activities[activity_id]
        old_desc = f"{activity.start.isoformat()}–{activity.end.isoformat()} @ {activity.venue}"
        activity.start, activity.end = new_start, new_end
        if new_venue:
            activity.venue = new_venue
        new_desc = f"{new_start.isoformat()}–{new_end.isoformat()} @ {activity.venue}"
        self._log(at, "改期", f"「{activity.name}」{old_desc} → {new_desc}", activity_id=activity_id)
        report = ImpactReport(trigger=f"「{activity.name}」改期")
        for assignment in list(self.assignments.values()):
            if assignment.activity_id != activity_id or assignment.state not in (
                AssignmentState.CONFIRMED,
                AssignmentState.STANDBY,
            ):
                continue
            person = self.pool.get(assignment.person_id)
            slot = activity.slot(assignment.slot_id)
            elig = evaluate(
                person,
                activity,
                slot,
                self._commitments(person.person_id, exclude_assignment_id=assignment.assignment_id),
            )
            if not elig.ok:
                assignment.state = AssignmentState.REVOKED
                assignment.note = "；".join(elig.violations)
                self._log(
                    at,
                    "撤销",
                    f"改期后 {person.name} 无法继续承担「{slot.role}」：{assignment.note}",
                    person.person_id,
                    activity_id,
                )
                report.revoked.append(assignment)
            else:
                # 留任人员的入选理由同步刷新为新时段，保证值守表自洽
                markers = [m for m in ("作为候补值守", "由候补递补") if m in assignment.reasons]
                assignment.reasons = elig.reasons + markers
        # 未回复的派单是按旧时段发出的，改期后一律失效并留痕
        for offer in [
            o
            for o in self.offers.values()
            if o.activity_id == activity_id and o.state is OfferState.PENDING
        ]:
            offer.state = OfferState.EXPIRED
            offer.responded_at = at
            offer.response_reason = "活动改期，派单失效"
            person = self.pool.get(offer.person_id)
            self._log(
                at,
                "派单失效",
                f"{person.name} 的「{activity.name} / {activity.slot(offer.slot_id).role}」派单因改期失效",
                offer.person_id,
                activity_id,
            )
        for slot in activity.slots:
            if self._confirmed_count(activity, slot) < slot.headcount:
                report.merge(self._refill(activity, slot, at, trigger=f"「{activity.name}」改期后补位"))
        return report

    def add_requirement(self, activity_id: str, slot: Slot, at: datetime) -> ImpactReport:
        """临时新增岗位（如小语种嘉宾）：立即在人才库中找人，找不到就给出接力建议。"""
        activity = self.activities[activity_id]
        activity.slots.append(slot)
        pair = str(slot.language_pair) if slot.language_pair else "不限语种"
        self._log(
            at,
            "新增需求",
            f"「{activity.name}」临时增加岗位 {slot.role}（{pair}×{slot.headcount}）",
            activity_id=activity_id,
        )
        report = self._refill(activity, slot, at, trigger=f"临时需求「{slot.role}」")
        if report.gaps and slot.language_pair is not None:
            relay = self._suggest_relay(slot.language_pair)
            report.gaps.append(relay or f"接力口译也暂无方案：人才库缺少 {pair} 的中转组合")
        return report

    def _suggest_relay(self, pair: LanguagePair) -> str | None:
        """没有直达人选时，寻找「源语言↔中转语言 + 中转语言↔目标语言」的接力组合。"""
        active = self.pool.all_active()

        def speakers(source: str, target: str) -> list[Person]:
            wanted = LanguagePair(source, target)
            return [p for p in active if any(same_pair(pp, wanted) for pp in p.language_pairs)]

        languages = {pp.source for p in active for pp in p.language_pairs} | {
            pp.target for p in active for pp in p.language_pairs
        }
        for mid in sorted(languages):
            if mid in (pair.source, pair.target):
                continue
            first, second = speakers(pair.source, mid), speakers(mid, pair.target)
            if first and second:
                return (
                    f"接力口译建议：{pair.source}↔{mid} 由 {first[0].name} 承担，"
                    f"{mid}↔{pair.target} 由 {second[0].name} 承担"
                )
        return None

    # ---------- 活动完成：真实服务回填人才库 ----------

    def complete_activity(
        self, activity_id: str, at: datetime, ratings: dict[str, int] | None = None
    ) -> None:
        """活动结束后，把每位在岗人员的服务结果写入人才库。"""
        activity = self.activities[activity_id]
        ratings = ratings or {}
        count = 0
        for assignment in self.assignments.values():
            if assignment.activity_id == activity_id and assignment.state is AssignmentState.CONFIRMED:
                assignment.state = AssignmentState.COMPLETED
                slot = activity.slot(assignment.slot_id)
                self.pool.record_service(
                    assignment.person_id,
                    activity_id,
                    slot.role,
                    ServiceOutcome.COMPLETED,
                    at,
                    rating=ratings.get(assignment.person_id),
                )
                count += 1
        activity.status = "已完成"
        self._log(at, "活动完成", f"「{activity.name}」完成，{count} 人次的真实服务已写入人才库", activity_id=activity_id)

    # ---------- 值守表 ----------

    def roster(self, activity_id: str | None = None) -> Roster:
        """生成值守表：每个岗位附入选理由，并独立复核冲突。"""
        activities = (
            [self.activities[activity_id]] if activity_id else list(self.activities.values())
        )
        entries: list[RosterEntry] = []
        standbys: dict[str, list[str]] = {}
        gaps: list[SlotGap] = []
        for activity in activities:
            for slot in activity.slots:
                on_duty = [
                    a
                    for a in self._slot_assignments(activity, slot)
                    if a.state in (AssignmentState.CONFIRMED, AssignmentState.COMPLETED)
                ]
                for a in on_duty:
                    person = self.pool.get(a.person_id)
                    entries.append(
                        RosterEntry(
                            activity_id=activity.activity_id,
                            activity_name=activity.name,
                            slot_id=slot.slot_id,
                            role=slot.role,
                            person_id=person.person_id,
                            person_name=person.name,
                            organization=person.organization,
                            venue=activity.venue,
                            timezone=activity.timezone,
                            start=activity.start,
                            end=activity.end,
                            reasons=list(a.reasons),
                        )
                    )
                standby_names = [
                    self.pool.get(a.person_id).name
                    for a in self._slot_assignments(activity, slot)
                    if a.state is AssignmentState.STANDBY
                ]
                if standby_names:
                    standbys[f"{activity.name} / {slot.role}"] = standby_names
                missing = slot.headcount - len(on_duty)
                if missing > 0:
                    gaps.append(
                        SlotGap(
                            activity.activity_id,
                            activity.name,
                            slot.slot_id,
                            slot.role,
                            missing,
                            len(standby_names),
                        )
                    )
        entries.sort(key=lambda e: (e.start, e.activity_name, e.slot_id))
        conflicts = validate_roster(entries, self.activities)
        return Roster(entries=entries, standbys=standbys, gaps=gaps, conflicts=conflicts)

    def export_roster(self, path: str | Path, activity_id: str | None = None) -> None:
        data = self.roster(activity_id).to_dict()
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
