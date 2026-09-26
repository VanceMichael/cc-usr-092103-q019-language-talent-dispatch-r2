"""人才库维护：只依据真实服务更新，定期清理过期证书与失效名单。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Authorization, Certification, Feedback, Person, parse_dt

# 超过该天数没有任何服务记录且证书全部失效的成员视为失效名单
STALE_AFTER_DAYS = 365


class TalentPool:
    """人才库。

    反馈与活跃度只能通过 record_service（真实完成的服务）写入，
    不允许直接改分；purge 负责清出过期证书、失效授权和失效成员。
    """

    def __init__(self) -> None:
        self.people: dict[str, Person] = {}

    def add_person(self, person: Person) -> None:
        if person.person_id in self.people:
            raise ValueError(f"人员已存在: {person.person_id}")
        self.people[person.person_id] = person

    def add_certification(self, person_id: str, cert: Certification) -> None:
        self._get(person_id).certifications.append(cert)

    def add_authorization(self, person_id: str, auth: Authorization) -> None:
        self._get(person_id).authorizations.append(auth)

    def record_service(self, person_id: str, feedback: Feedback) -> None:
        """唯一允许更新历史反馈的入口：必须对应一次真实完成的服务。"""
        if not 1 <= feedback.rating <= 5:
            raise ValueError("评分须在 1-5 之间")
        parse_dt(feedback.recorded_at)  # 校验时间格式
        self._get(person_id).feedback.append(feedback)

    def purge(self, as_of: datetime) -> dict:
        """清理过期证书、失效授权与失效成员，返回清理报告。"""
        report = {"expired_certs": [], "expired_auths": [], "deactivated": []}
        for person in self.people.values():
            kept_certs = []
            for cert in person.certifications:
                if parse_dt(cert.expires) <= as_of:
                    report["expired_certs"].append((person.person_id, cert.cert_id))
                else:
                    kept_certs.append(cert)
            person.certifications = kept_certs

            kept_auths = []
            for auth in person.authorizations:
                if parse_dt(auth.expires) <= as_of:
                    report["expired_auths"].append((person.person_id, auth.kind))
                else:
                    kept_auths.append(auth)
            person.authorizations = kept_auths

            if self._is_stale(person, as_of):
                person.active = False
                report["deactivated"].append(person.person_id)
        return report

    def _is_stale(self, person: Person, as_of: datetime) -> bool:
        if not person.active:
            return False
        if person.certifications:  # 仍有有效证书则保留
            return False
        if not person.feedback:  # 从未服务且无有效证书
            return True
        last_service = max(parse_dt(f.recorded_at) for f in person.feedback)
        return as_of - last_service > timedelta(days=STALE_AFTER_DAYS)

    def active_members(self) -> list[Person]:
        return [p for p in self.people.values() if p.active]

    def _get(self, person_id: str) -> Person:
        try:
            return self.people[person_id]
        except KeyError:
            raise KeyError(f"人员不存在: {person_id}") from None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
