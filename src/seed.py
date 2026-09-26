"""从样例资料构建人才库与调度器。"""

from __future__ import annotations

import json
from pathlib import Path

from .dispatch import Dispatcher
from .models import (
    Authorization,
    AvailabilityWindow,
    Certification,
    Clearance,
    ContentRating,
    Feedback,
    Person,
    Post,
    ServiceType,
    WaitlistRule,
)
from .pool import TalentPool


def load_seed(path: Path) -> tuple[TalentPool, Dispatcher]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pool = TalentPool()
    for p in data["people"]:
        person = Person(
            person_id=p["person_id"],
            name=p["name"],
            organization=p["organization"],
            category=p["category"],
            language_pairs=p["language_pairs"],
            service_types=[ServiceType(s) for s in p["service_types"]],
            clearance=Clearance(p["clearance"]),
            is_minor=p.get("is_minor", False),
            certifications=[Certification(**c) for c in p.get("certifications", [])],
            availability=[AvailabilityWindow(**w) for w in p.get("availability", [])],
            authorizations=[Authorization(**a) for a in p.get("authorizations", [])],
            feedback=[Feedback(**f) for f in p.get("feedback", [])],
        )
        pool.add_person(person)
    dispatcher = Dispatcher(pool)
    for q in data["posts"]:
        rule = WaitlistRule(**q.get("waitlist_rule", {}))
        post = Post(
            post_id=q["post_id"],
            event_id=q["event_id"],
            scenario=q["scenario"],
            service_type=ServiceType(q["service_type"]),
            language_pair=q["language_pair"],
            location=q["location"],
            timezone=q["timezone"],
            start=q["start"],
            end=q["end"],
            sensitivity=Clearance(q["sensitivity"]),
            content_rating=ContentRating(q.get("content_rating", "适宜全体")),
            waitlist_rule=rule,
        )
        dispatcher.add_post(post)
    return pool, dispatcher
