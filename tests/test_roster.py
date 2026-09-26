import unittest
from pathlib import Path

from src.models import AssignmentState
from src.roster import build_roster
from src.seed import load_seed

SEED = Path("fixtures/seed.json")


class RosterTest(unittest.TestCase):
    def setUp(self):
        self.pool, self.d = load_seed(SEED)
        for post_id in ("POST-01", "POST-02", "POST-03"):
            offers = self.d.dispatch(post_id)
            self.assertTrue(offers, f"{post_id} 应有人可派")
            self.d.respond(offers[0].assignment_id, accept=True)

    def test_roster_has_no_conflicts_and_every_post_explained(self):
        roster = build_roster(self.d)
        self.assertEqual(roster["conflicts"], [])
        self.assertEqual(roster["unfilled_posts"], [])
        self.assertEqual(len(roster["entries"]), 3)
        for entry in roster["entries"]:
            self.assertTrue(entry["why"], f"{entry['post_id']} 缺少承担理由")
            self.assertTrue(entry["assignee"])
            self.assertTrue(entry["organization"])

    def test_roster_reflects_absence_recompute(self):
        confirmed = [
            a for a in self.d.assignments.values() if a.state == AssignmentState.CONFIRMED
        ]
        target = next(a for a in confirmed if a.post_id == "POST-01")
        self.d.report_absence(target.assignment_id, reason="突发疾病")
        roster = build_roster(self.d)
        # POST-01 被撤销后重新邀约但尚未确认 → 岗位空缺被暴露而非隐藏
        self.assertIn("POST-01", roster["unfilled_posts"])
        self.assertEqual(roster["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
