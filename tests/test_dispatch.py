import unittest
from pathlib import Path

from src.models import (
    AssignmentState,
    Clearance,
    ContentRating,
    Post,
    ServiceType,
    WaitlistRule,
)
from src.seed import load_seed

SEED = Path("fixtures/seed.json")


def make_post(**overrides) -> Post:
    base = dict(
        post_id="POST-NEW",
        event_id="EV-200",
        scenario="临时会谈",
        service_type=ServiceType.CONFERENCE_INTERPRETING,
        language_pair="zh-sw",
        location="国际会议中心B厅",
        timezone="Asia/Shanghai",
        start="2026-10-17T09:00:00+08:00",
        end="2026-10-17T11:00:00+08:00",
        sensitivity=Clearance.INTERNAL,
        content_rating=ContentRating.ALL_AGES,
        waitlist_rule=WaitlistRule(max_concurrent_offers=2),
    )
    base.update(overrides)
    return Post(**base)


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.pool, self.d = load_seed(SEED)

    def actions(self):
        return [e["action"] for e in self.d.audit_log]

    def test_accept_confirms_and_cancels_other_offers(self):
        offers = self.d.dispatch("POST-03")  # P004、P005 同时被邀约
        self.assertEqual(len(offers), 2)
        first = self.d.respond(offers[0].assignment_id, accept=True)
        self.assertEqual(first.state, AssignmentState.CONFIRMED)
        second = self.d.assignments[offers[1].assignment_id]
        self.assertEqual(second.state, AssignmentState.CANCELLED)
        self.assertIn("accepted", self.actions())
        self.assertIn("cancelled", self.actions())

    def test_simultaneous_accepts_first_one_wins(self):
        offers = self.d.dispatch("POST-03")
        a, b = offers
        self.d.respond(a.assignment_id, accept=True)
        # 另一人尚未收到撤回通知，同时接受 → 应被拒绝并留痕
        loser = self.d.respond(b.assignment_id, accept=True)
        self.assertEqual(loser.state, AssignmentState.REJECTED)
        self.assertIn("岗位已被占用", loser.note)

    def test_rejection_is_recorded_and_backfills(self):
        offers = self.d.dispatch("POST-03")
        rejected = self.d.respond(offers[0].assignment_id, accept=False, note="临时有事")
        self.assertEqual(rejected.state, AssignmentState.REJECTED)
        self.assertIn("rejected", self.actions())
        entry = next(e for e in self.d.audit_log if e["action"] == "rejected")
        self.assertIn("临时有事", entry["detail"])

    def test_absence_revokes_and_redispatches(self):
        offers = self.d.dispatch("POST-01")
        confirmed = self.d.respond(offers[0].assignment_id, accept=True)
        self.d.report_absence(confirmed.assignment_id, reason="航班取消")
        revoked = self.d.assignments[confirmed.assignment_id]
        self.assertEqual(revoked.state, AssignmentState.REVOKED)
        self.assertIn("缺席", revoked.note)
        # 重新派单：P001 再次被邀约
        new_offers = [
            a for a in self.d.assignments.values()
            if a.post_id == "POST-01" and a.state == AssignmentState.OFFERED
        ]
        self.assertEqual(len(new_offers), 1)
        self.assertIn("revoked", self.actions())

    def test_reschedule_recomputes_impact(self):
        offers = self.d.dispatch("POST-02")  # P004 合格（证书有效、时段覆盖）
        confirmed = self.d.respond(offers[0].assignment_id, accept=True)
        self.assertEqual(confirmed.person_id, "P004")
        # 改期到 P004 可用时段之外（其可用期到 10-20）
        impact = self.d.reschedule_post("POST-02", "2026-10-25T14:00:00+08:00", "2026-10-25T16:00:00+08:00")
        self.assertIn(confirmed.assignment_id, impact["revoked"])
        self.assertEqual(self.d.assignments[confirmed.assignment_id].state, AssignmentState.REVOKED)
        # 无人可补 → 记录人才缺口
        self.assertIn("talent_gap", self.actions())

    def test_reschedule_keeps_still_eligible_assignee(self):
        offers = self.d.dispatch("POST-02")
        confirmed = self.d.respond(offers[0].assignment_id, accept=True)
        impact = self.d.reschedule_post("POST-02", "2026-10-16T14:00:00+08:00", "2026-10-16T16:00:00+08:00")
        self.assertIn(confirmed.assignment_id, impact["kept"])
        self.assertEqual(self.d.assignments[confirmed.assignment_id].state, AssignmentState.CONFIRMED)

    def test_rare_language_guest_triggers_redispatch(self):
        post = make_post()  # 临时增加斯瓦希里语嘉宾
        self.d.add_post(post)
        offers = self.d.dispatch(post.post_id)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].person_id, "P003")  # 唯一持 zh-sw 有效证书者

    def test_unknown_language_reports_gap(self):
        post = make_post(post_id="POST-JA", language_pair="zh-ja")
        self.d.add_post(post)
        offers = self.d.dispatch(post.post_id)
        self.assertEqual(offers, [])
        gap = next(e for e in self.d.audit_log if e["action"] == "talent_gap")
        self.assertIn("zh-ja", gap["detail"])

    def test_every_decision_kept_in_audit_log(self):
        offers = self.d.dispatch("POST-03")
        self.d.respond(offers[0].assignment_id, accept=False, note="课程冲突")
        rest = [a for a in self.d.assignments.values() if a.state == AssignmentState.OFFERED]
        for a in rest:
            self.d.respond(a.assignment_id, accept=True)
        for action in ("offered", "rejected", "accepted"):
            self.assertIn(action, self.actions())
        for entry in self.d.audit_log:
            self.assertTrue(entry["at"])


if __name__ == "__main__":
    unittest.main()
