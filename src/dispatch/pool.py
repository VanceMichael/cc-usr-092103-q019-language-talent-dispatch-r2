"""人才库：只依据真实服务记录更新，定期清理过期证明与失效名单。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .enums import ServiceOutcome
from .models import Feedback, Person, ServiceRecord


@dataclass
class PruneReport:
    """一次清理的结果，全部留痕。"""

    on: date
    removed_credentials: list[str] = field(default_factory=list)
    removed_authorizations: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"清理 {len(self.removed_credentials)} 份过期证明、"
            f"{len(self.removed_authorizations)} 份过期授权、停用 {len(self.deactivated)} 人"
        )


class TalentPool:
    """语言人才库。

    两条铁律：
    1. 反馈与服务统计只允许通过 record_service 依据真实服务写入；
    2. prune 定期清出过期证明、过期授权与失效名单，避免越积越多。
    """

    def __init__(self) -> None:
        self._people: dict[str, Person] = {}
        self.service_records: list[ServiceRecord] = []
        self.prune_log: list[str] = []
        self._record_seq = 0

    def register(self, person: Person) -> None:
        if person.person_id in self._people:
            raise ValueError(f"人员编号重复：{person.person_id}")
        self._people[person.person_id] = person

    def get(self, person_id: str) -> Person:
        try:
            return self._people[person_id]
        except KeyError:
            raise KeyError(f"人才库中不存在人员：{person_id}") from None

    def all(self) -> list[Person]:
        return list(self._people.values())

    def all_active(self) -> list[Person]:
        return [p for p in self._people.values() if p.active]

    def record_service(
        self,
        person_id: str,
        activity_id: str,
        slot_role: str,
        outcome: ServiceOutcome,
        at: datetime,
        rating: int | None = None,
        comment: str = "",
    ) -> ServiceRecord:
        """依据一次真实服务更新人才库（反馈的唯一写入口）。"""
        person = self.get(person_id)
        self._record_seq += 1
        record = ServiceRecord(
            record_id=f"SR-{self._record_seq:04d}",
            activity_id=activity_id,
            slot_role=slot_role,
            outcome=outcome,
            recorded_at=at,
        )
        person.service_history.append(record)
        self.service_records.append(record)
        if outcome is ServiceOutcome.COMPLETED:
            if rating is not None:
                if not 1 <= rating <= 5:
                    raise ValueError("评分须在 1 到 5 之间")
                person.feedback.append(
                    Feedback(activity_id, rating, comment or "服务完成", at, record.record_id)
                )
        else:  # 缺席同样是真实服务记录，按最低分计入
            person.feedback.append(
                Feedback(activity_id, 1, comment or "无故缺席", at, record.record_id)
            )
        return record

    def prune(self, on: date, stale_days: int = 365) -> PruneReport:
        """清出过期证明、过期授权，并停用名单失效且长期无真实服务的人员。"""
        report = PruneReport(on)
        for person in self._people.values():
            kept_credentials = []
            for cred in person.credentials:
                if cred.is_valid(on):
                    kept_credentials.append(cred)
                else:
                    msg = f"{person.name} 的过期证明已清出：{cred.name}（{cred.expires_on} 到期）"
                    report.removed_credentials.append(msg)
                    self.prune_log.append(f"{on} {msg}")
            person.credentials = kept_credentials

            kept_authorizations = []
            for auth in person.authorizations:
                if auth.is_valid(on):
                    kept_authorizations.append(auth)
                else:
                    msg = f"{person.name} 的过期授权已清出：{auth.kind.value}（{auth.expires_on} 到期）"
                    report.removed_authorizations.append(msg)
                    self.prune_log.append(f"{on} {msg}")
            person.authorizations = kept_authorizations

            if person.active and self._is_stale(person, on, stale_days):
                person.active = False
                person.deactivated_reason = f"单位名单失效且 {stale_days} 天内无真实服务"
                msg = f"{person.name} 已停用：{person.deactivated_reason}"
                report.deactivated.append(msg)
                self.prune_log.append(f"{on} {msg}")
        return report

    @staticmethod
    def _is_stale(person: Person, on: date, stale_days: int) -> bool:
        if person.membership_valid_until is None or person.membership_valid_until >= on:
            return False
        cutoff = on - timedelta(days=stale_days)
        return not any(r.recorded_at.date() >= cutoff for r in person.service_history)
