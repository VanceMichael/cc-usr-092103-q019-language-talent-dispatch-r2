"""派单调度：多人同时派单、接受/拒绝留痕、缺席与改期重算。

所有邀约、接受、拒绝、撤销都写入审计日志；任何变更（临时小语种嘉宾、
缺席、改期）都会触发影响重算，而不是等到现场才暴露冲突。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from .models import Assignment, AssignmentState, Person, Post
from .pool import TalentPool
from .scheduling import BLOCKING_STATES, check_eligibility, find_conflicts, rank_candidates


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Dispatcher:
    def __init__(self, pool: TalentPool) -> None:
        self.pool = pool
        self.posts: dict[str, Post] = {}
        self.assignments: dict[str, Assignment] = {}
        self.audit_log: list[dict] = []
        self._seq = 0
        self._lock = threading.RLock()  # respond → _backfill → dispatch 会重入

    # ---- 岗位登记 -------------------------------------------------------

    def add_post(self, post: Post) -> None:
        """登记岗位（含临时增加的小语种嘉宾需求）。"""
        if post.post_id in self.posts:
            raise ValueError(f"岗位已存在: {post.post_id}")
        self.posts[post.post_id] = post
        self._log("post_added", post.post_id, f"{post.scenario}/{post.language_pair}")

    # ---- 派单 -----------------------------------------------------------

    def dispatch(self, post_id: str) -> list[Assignment]:
        """为岗位计算合格人选并按候补规则同时发出邀约。

        返回本次发出的邀约；若无合格人选，记录人才缺口。
        """
        with self._lock:
            post = self.posts[post_id]
            if self._filled(post_id):
                return []
            # 已邀约未答复、已拒绝过本岗位的人不再重复邀约
            engaged = {
                a.person_id
                for a in self.assignments.values()
                if a.post_id == post_id
                and a.state in (AssignmentState.OFFERED, AssignmentState.REJECTED)
            }
            candidates: list[tuple[Person, list[str]]] = []
            for person in self.pool.active_members():
                if person.person_id in engaged:
                    continue
                ok, reasons = check_eligibility(person, post)
                if not ok:
                    continue
                if find_conflicts(person.person_id, post, list(self.assignments.values()), self.posts):
                    continue
                candidates.append((person, reasons))
            if not candidates:
                self._log("talent_gap", post_id, f"岗位 {post.scenario}/{post.language_pair} 无合格人选")
                return []
            ranked = rank_candidates(candidates, post.waitlist_rule.rank_by)
            offers = []
            for person, reasons in ranked[: post.waitlist_rule.max_concurrent_offers]:
                offers.append(self._offer(post, person, reasons))
            return offers

    def _offer(self, post: Post, person: Person, reasons: list[str]) -> Assignment:
        self._seq += 1
        assignment = Assignment(
            assignment_id=f"A{self._seq:04d}",
            post_id=post.post_id,
            person_id=person.person_id,
            state=AssignmentState.OFFERED,
            reasons=reasons,
            offered_at=_now(),
        )
        self.assignments[assignment.assignment_id] = assignment
        self._log("offered", post.post_id, f"邀约 {person.name}", assignment.assignment_id)
        return assignment

    # ---- 接受 / 拒绝 ------------------------------------------------------

    def respond(self, assignment_id: str, accept: bool, note: str = "") -> Assignment:
        """人员应答。多人同时接受时先确认者生效，其余按冲突拒绝并留痕。"""
        with self._lock:
            a = self.assignments[assignment_id]
            if a.state == AssignmentState.CANCELLED and accept:
                # 邀约刚被撤回（岗位已确认他人），对方的接受按竞态拒绝留痕
                a.state = AssignmentState.REJECTED
                a.decided_at = _now()
                a.note = "接受时岗位已被占用"
                self._log("rejected", a.post_id, f"{a.person_id} 接受未生效：岗位已被占用", a.assignment_id)
                return a
            if a.state != AssignmentState.OFFERED:
                raise ValueError(f"派单 {assignment_id} 当前状态不可应答: {a.state.value}")
            post = self.posts[a.post_id]
            a.decided_at = _now()
            a.note = note
            if not accept:
                a.state = AssignmentState.REJECTED
                self._log("rejected", a.post_id, f"{a.person_id} 拒绝：{note}", a.assignment_id)
                self._backfill(a.post_id)
                return a
            if self._filled(a.post_id) or find_conflicts(
                a.person_id, post, list(self.assignments.values()), self.posts
            ):
                a.state = AssignmentState.REJECTED
                a.note = f"接受时岗位已被占用或存在冲突。{note}".strip()
                self._log("rejected", a.post_id, f"{a.person_id} 接受未生效：{a.note}", a.assignment_id)
                return a
            a.state = AssignmentState.CONFIRMED
            self._log("accepted", a.post_id, f"{a.person_id} 接受并确认", a.assignment_id)
            for other in self.assignments.values():
                if other.post_id == a.post_id and other.state == AssignmentState.OFFERED:
                    other.state = AssignmentState.CANCELLED
                    other.decided_at = _now()
                    other.note = "岗位已确认他人"
                    self._log("cancelled", a.post_id, f"撤回对 {other.person_id} 的邀约", other.assignment_id)
            return a

    # ---- 缺席 / 改期 ------------------------------------------------------

    def report_absence(self, assignment_id: str, reason: str) -> None:
        """缺席：撤销确认，留痕，并立即重算该岗位人选。"""
        with self._lock:
            a = self.assignments[assignment_id]
            if a.state not in BLOCKING_STATES:
                raise ValueError(f"派单 {assignment_id} 未处于占用状态")
            a.state = AssignmentState.REVOKED
            a.decided_at = _now()
            a.note = f"缺席：{reason}"
            self._log("revoked", a.post_id, f"{a.person_id} 缺席：{reason}", a.assignment_id)
        self.dispatch(a.post_id)

    def reschedule_post(self, post_id: str, new_start: str, new_end: str) -> dict:
        """改期：重算该岗位全部确认人选，不合格者撤销并重新派单。"""
        with self._lock:
            post = self.posts[post_id]
            post.start, post.end = new_start, new_end
            self._log("rescheduled", post_id, f"改期为 {new_start} ~ {new_end}")
        impact = {"revoked": [], "kept": []}
        for a in list(self.assignments.values()):
            if a.post_id != post_id or a.state not in BLOCKING_STATES:
                continue
            person = self.pool.people[a.person_id]
            ok, reasons = check_eligibility(person, post)
            conflict = find_conflicts(
                person.person_id,
                post,
                list(self.assignments.values()),
                self.posts,
                exclude_assignment_id=a.assignment_id,
            )
            if ok and not conflict:
                a.reasons = reasons
                impact["kept"].append(a.assignment_id)
            else:
                a.state = AssignmentState.REVOKED
                a.decided_at = _now()
                a.note = "改期后不再满足条件或产生冲突"
                self._log("revoked", post_id, f"{a.person_id} 因改期撤销", a.assignment_id)
                impact["revoked"].append(a.assignment_id)
        if impact["revoked"]:
            self.dispatch(post_id)
        return impact

    # ---- 内部 -------------------------------------------------------------

    def _filled(self, post_id: str) -> bool:
        return any(
            a.post_id == post_id and a.state in BLOCKING_STATES for a in self.assignments.values()
        )

    def _backfill(self, post_id: str) -> None:
        """拒绝后按候补规则补邀下一位。"""
        if not self._filled(post_id):
            self.dispatch(post_id)

    def _log(self, action: str, post_id: str, detail: str, assignment_id: str = "") -> None:
        self.audit_log.append(
            {
                "at": _now(),
                "action": action,
                "post_id": post_id,
                "assignment_id": assignment_id,
                "detail": detail,
            }
        )
