from dataclasses import dataclass

from polar_django.models import Subscription


@dataclass(frozen=True)
class Plan:
    slug: str
    name: str
    max_monitors: int
    min_interval_minutes: int


FREE = Plan(slug="free", name="Free", max_monitors=2, min_interval_minutes=5)
PRO = Plan(slug="pro", name="Pro", max_monitors=5, min_interval_minutes=1)

PLANS_BY_SLUG = {plan.slug: plan for plan in (FREE, PRO)}


def plan_for(user) -> Plan:
    """The user's current plan, falling back to Free for unknown tiers."""
    return PLANS_BY_SLUG.get(Subscription.tier_for(user), FREE)


def allowed_intervals(plan: Plan, choices) -> list[tuple[int, str]]:
    """Filter interval choices down to those the plan permits."""
    return [(value, label) for value, label in choices if value >= plan.min_interval_minutes]
