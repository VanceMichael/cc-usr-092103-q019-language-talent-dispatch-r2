"""端到端演示：建库、派单、现场变动重算，直到产出最终值守表。

运行：python -m src.dispatch.demo
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .engine import DispatchEngine
from .enums import OfferState, ServiceType
from .models import Slot
from .seed import ZH_LO, ZH_SW, build_activities, build_pool

SH = ZoneInfo("Asia/Shanghai")


def _dt(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=SH)


def _print_events(engine: DispatchEngine, kinds: set[str], title: str) -> None:
    print(f"\n—— {title} ——")
    for e in engine.events:
        if e.kind in kinds:
            print(f"  #{e.seq:02d} [{e.at.strftime('%m-%d %H:%M')}] {e.kind}｜{e.detail}")


def main() -> DispatchEngine:
    pool = build_pool()
    engine = DispatchEngine(pool)
    t0 = _dt(9, 26, 10)
    forum, museum, camp = build_activities()
    for activity in (forum, museum, camp):
        engine.open_activity(activity, t0)

    print("—— 1. 派单（自动排名 + 多人同时派单）——")
    for slot in forum.slots:
        engine.dispatch(forum.activity_id, slot.slot_id, t0)
    # 英语讲解：向高然、孙倩两人同时派单，名额在接受时竞争
    engine.offer_to(museum.activity_id, "S3", ["P06", "P07"], t0)
    for slot in camp.slots:
        engine.dispatch(camp.activity_id, slot.slot_id, t0)
    # 张小禾只有监护人授权，缺少学校授权，派单校验直接拦下
    engine.offer_to(camp.activity_id, "S5", ["P11"], t0)

    print("\n—— 2. 接受与拒绝（全部留痕）——")

    def respond(person_id: str, slot_id: str, accept: bool, reason: str = "") -> None:
        for offer in engine.offers.values():
            if (
                offer.person_id == person_id
                and offer.slot_id == slot_id
                and offer.state is OfferState.PENDING
            ):
                engine.respond(offer.offer_id, accept, t0, reason)
                return
        print(f"  （{person_id} 在 {slot_id} 没有待回复的派单）")

    respond("P01", "S1", True)                 # 陈述确认英语同传
    respond("P05", "S1", True)                 # 阿依古丽正选已满，转为候补
    respond("P02", "S2", True)                 # 林澜确认法语同传（陈述的法语派单因名额已满自动失效）
    respond("P07", "S3", False, "当天有课")    # 孙倩拒绝英语讲解，留痕
    respond("P06", "S3", True)                 # 高然确认英语讲解
    # 高然确认后，日语讲解派单会自动排除她（同一活动时段职责冲突）
    engine.dispatch(museum.activity_id, "S4", t0)
    respond("P08", "S4", True)                 # 郑川确认日语讲解
    respond("P09", "S5", True)                 # 吴帆确认交流助教
    respond("P10", "S5", True)                 # 李小满确认（双授权齐全）
    respond("P13", "S5", True)                 # 苏杭成为交流营候补

    print("\n—— 3. 改期：论坛提前到下午，系统复核全部安排 ——")
    report = engine.reschedule(forum.activity_id, _dt(10, 20, 13), _dt(10, 20, 16), _dt(10, 19, 9))
    print("  " + report.summary())
    # 林澜的可用时段只有上午被撤销，韩露收到补位派单并接受
    for offer in report.new_offers:
        engine.respond(offer.offer_id, True, _dt(10, 19, 9, 5))

    print("\n—— 4. 临时小语种嘉宾：斯瓦希里语 ——")
    # 陈述已确认全程在岗，释放阿依古丽的英语候补，让她转任小语种联络
    standby = next(
        a for a in engine.assignments.values()
        if a.person_id == "P05" and a.state.value == "候补待岗"
    )
    engine.release_assignment(standby.assignment_id, _dt(10, 20, 12, 30), "陈述确认在岗，释放候补转任小语种联络")
    report = engine.add_requirement(
        forum.activity_id,
        Slot("S6", "斯瓦希里语联络", ServiceType.CONFERENCE_INTERPRETATION, ZH_SW, headcount=1),
        _dt(10, 20, 12, 30),
    )
    print("  " + report.summary())
    for offer in report.new_offers:
        engine.respond(offer.offer_id, True, _dt(10, 20, 12, 35))

    print("\n—— 5. 临时小语种嘉宾：老挝语（人才库没有，如实报缺口）——")
    report = engine.add_requirement(
        museum.activity_id,
        Slot("S7", "老挝语联络", ServiceType.PUBLIC_DOCENT, ZH_LO, headcount=1),
        _dt(10, 20, 12, 40),
    )
    print("  " + report.summary())

    print("\n—— 6. 缺席：日语讲解郑川未到，立即重算 ——")
    absence = next(
        a for a in engine.assignments.values()
        if a.person_id == "P08" and a.state.value == "已确认"
    )
    report = engine.report_absence(absence.assignment_id, _dt(10, 20, 13, 30), "临场失联")
    print("  " + report.summary())
    for offer in report.new_offers:
        engine.respond(offer.offer_id, True, _dt(10, 20, 13, 35))

    print("\n—— 7. 活动完成：真实服务回填人才库 ——")
    engine.complete_activity(forum.activity_id, _dt(10, 20, 16, 30), {"P01": 5, "P03": 5, "P05": 5})
    engine.complete_activity(museum.activity_id, _dt(10, 20, 17, 30), {"P06": 5, "P07": 4})
    engine.complete_activity(camp.activity_id, _dt(10, 21, 18), {"P09": 5, "P10": 5})
    for pid in ("P07", "P08", "P10"):
        person = pool.get(pid)
        print(
            f"  {person.name}：{person.completed_count()} 次服务，"
            f"平均评分 {person.average_rating():.2f}（含缺席/新增记录）"
        )

    print("\n—— 8. 人才库清理：过期证明与失效名单 ——")
    report = pool.prune(datetime(2026, 10, 22).date())
    for line in report.removed_credentials + report.deactivated:
        print("  " + line)

    print()
    print(engine.roster().render())

    _print_events(engine, {"接受", "拒绝", "候补确认", "候补递补", "撤销", "缺席", "释放", "派单校验未通过", "派单失效"}, "接受与拒绝留痕")
    return engine


if __name__ == "__main__":
    main()
