import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.dispatch.engine import DispatchEngine
from src.dispatch.enums import ClearanceLevel, PersonnelCategory, Sensitivity, ServiceType
from src.dispatch.models import (
    Activity,
    AvailabilityWindow,
    Credential,
    LanguagePair,
    Person,
    Slot,
    WaitlistRule,
)
from src.dispatch.pool import TalentPool
from src.dispatch.roster import RosterEntry, validate_roster

SH = ZoneInfo("Asia/Shanghai")
ZH_EN = LanguagePair("中文", "英语")
CONF = ServiceType.CONFERENCE_INTERPRETATION
T0 = datetime(2026, 9, 26, 10, tzinfo=SH)


def make_entry(person_id="P1", name="张三", activity_id="A1", slot_id="S1", venue="主会场", start_h=9, end_h=12):
    return RosterEntry(
        activity_id=activity_id,
        activity_name=f"活动{activity_id}",
        slot_id=slot_id,
        role="英语同传",
        person_id=person_id,
        person_name=name,
        organization="北辰外国语大学",
        venue=venue,
        timezone="Asia/Shanghai",
        start=datetime(2026, 10, 20, start_h, tzinfo=SH),
        end=datetime(2026, 10, 20, end_h, tzinfo=SH),
        reasons=["语种方向匹配：中文↔英语"],
    )


class ValidateRosterTest(unittest.TestCase):
    def test_clean_entries_pass(self):
        entries = [make_entry("P1", "张三", "A1"), make_entry("P2", "李四", "A2", venue="分会场")]
        self.assertEqual(validate_roster(entries), [])

    def test_time_conflict_same_venue(self):
        entries = [
            make_entry(activity_id="A1", start_h=9, end_h=12),
            make_entry(activity_id="A2", start_h=11, end_h=14),
        ]
        kinds = [c.kind for c in validate_roster(entries)]
        self.assertIn("时间冲突", kinds)

    def test_location_conflict_different_venues(self):
        entries = [
            make_entry(activity_id="A1", venue="主会场", start_h=9, end_h=12),
            make_entry(activity_id="A2", venue="分会场", start_h=11, end_h=14),
        ]
        kinds = [c.kind for c in validate_roster(entries)]
        self.assertIn("地点冲突", kinds)

    def test_responsibility_conflict_same_activity(self):
        entries = [
            make_entry(activity_id="A1", slot_id="S1"),
            make_entry(activity_id="A1", slot_id="S2"),
        ]
        kinds = [c.kind for c in validate_roster(entries)]
        self.assertIn("职责冲突", kinds)

    def test_overstaffing_detected_with_activities(self):
        activity = Activity(
            activity_id="A1",
            name="论坛",
            scenario="国际会议",
            service_type=CONF,
            venue="主会场",
            timezone="Asia/Shanghai",
            start=datetime(2026, 10, 20, 9, tzinfo=SH),
            end=datetime(2026, 10, 20, 12, tzinfo=SH),
            sensitivity=Sensitivity.MEDIUM,
            min_clearance=ClearanceLevel.INTERNAL,
            slots=[Slot("S1", "英语同传", CONF, ZH_EN, headcount=1)],
            waitlist=WaitlistRule(),
        )
        entries = [make_entry("P1", "张三"), make_entry("P2", "李四")]
        conflicts = validate_roster(entries, {"A1": activity})
        self.assertTrue(any("超编" in c.detail for c in conflicts))

    def test_non_overlapping_same_person_ok(self):
        entries = [
            make_entry(activity_id="A1", start_h=9, end_h=12),
            make_entry(activity_id="A2", venue="分会场", start_h=14, end_h=17),
        ]
        self.assertEqual(validate_roster(entries), [])


class EngineRosterTest(unittest.TestCase):
    def setUp(self):
        self.pool = TalentPool()
        self.engine = DispatchEngine(self.pool)
        person = Person(
            person_id="P1",
            name="张三",
            category=PersonnelCategory.TRANSLATOR,
            organization="北辰外国语大学",
            service_types={CONF},
            language_pairs=[ZH_EN],
            credentials=[Credential("CATTI二级口译", frozenset({CONF}), frozenset(), date(2024, 1, 1), date(2028, 1, 1))],
            availability=[AvailabilityWindow(datetime(2026, 10, 20, 8, tzinfo=SH), datetime(2026, 10, 20, 18, tzinfo=SH))],
            clearance=ClearanceLevel.INTERNAL,
            membership_valid_until=date(2027, 12, 31),
        )
        self.pool.register(person)
        activity = Activity(
            activity_id="A1",
            name="论坛",
            scenario="国际会议",
            service_type=CONF,
            venue="主会场",
            timezone="Asia/Shanghai",
            start=datetime(2026, 10, 20, 9, tzinfo=SH),
            end=datetime(2026, 10, 20, 12, tzinfo=SH),
            sensitivity=Sensitivity.MEDIUM,
            min_clearance=ClearanceLevel.INTERNAL,
            slots=[Slot("S1", "英语同传", CONF, ZH_EN, headcount=1)],
            waitlist=WaitlistRule(backup_count=0),
        )
        self.engine.open_activity(activity, T0)
        offers = self.engine.dispatch("A1", "S1", T0)
        self.engine.respond(offers[0].offer_id, True, T0)

    def test_roster_clean_and_explained(self):
        roster = self.engine.roster()
        self.assertTrue(roster.is_clean)
        self.assertEqual(len(roster.entries), 1)
        entry = roster.entries[0]
        self.assertEqual(entry.person_name, "张三")
        self.assertGreater(len(entry.reasons), 3)

    def test_roster_to_dict_json_serializable(self):
        roster = self.engine.roster()
        text = json.dumps(roster.to_dict(), ensure_ascii=False)
        self.assertIn("张三", text)

    def test_export_roster_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            roster_path = Path(tmp) / "roster.json"
            history_path = Path(tmp) / "history.jsonl"
            self.engine.export_roster(roster_path)
            self.engine.export_history(history_path)
            data = json.loads(roster_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["entries"]), 1)
            lines = history_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertGreater(len(lines), 0)
            first = json.loads(lines[0])
            self.assertIn("kind", first)


if __name__ == "__main__":
    unittest.main()
