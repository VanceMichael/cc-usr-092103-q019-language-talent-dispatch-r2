"""生成最终值守表：无时间、地点和职责冲突，每个岗位附承担理由。"""

from __future__ import annotations

from .dispatch import Dispatcher
from .models import AssignmentState
from .scheduling import BLOCKING_STATES, find_conflicts


def build_roster(dispatcher: Dispatcher) -> dict:
    """汇总已确认派单，逐岗说明为何由该人员承担，并整体校验无冲突。"""
    entries = []
    confirmed = [
        a for a in dispatcher.assignments.values() if a.state == AssignmentState.CONFIRMED
    ]
    for a in sorted(confirmed, key=lambda x: x.post_id):
        post = dispatcher.posts[a.post_id]
        person = dispatcher.pool.people[a.person_id]
        entries.append(
            {
                "post_id": post.post_id,
                "event_id": post.event_id,
                "scenario": post.scenario,
                "service_type": post.service_type.value,
                "language_pair": post.language_pair,
                "location": post.location,
                "timezone": post.timezone,
                "start": post.start,
                "end": post.end,
                "assignee": person.name,
                "organization": person.organization,
                "why": a.reasons,
            }
        )

    conflicts = []
    for a in confirmed:
        post = dispatcher.posts[a.post_id]
        for c in find_conflicts(
            a.person_id,
            post,
            list(dispatcher.assignments.values()),
            dispatcher.posts,
            exclude_assignment_id=a.assignment_id,
        ):
            conflicts.append({"post_id": a.post_id, "person_id": a.person_id, "conflict": c})

    unfilled = [
        p.post_id
        for p in dispatcher.posts.values()
        if not any(
            a.post_id == p.post_id and a.state in BLOCKING_STATES
            for a in dispatcher.assignments.values()
        )
    ]
    return {"entries": entries, "conflicts": conflicts, "unfilled_posts": unfilled}
