"""Daily streaks. A day counts when the user posts a fit, posts a story, or sends a fit check, on their
local calendar. Missing one day uses a freeze if one is available; otherwise the streak ends and the
next activity starts it again at 1."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.localtime import local_now, next_midnight
from app.db.mixins import utcnow
from app.models.streak import UserStreak
from app.models.user import User
from app.repositories import streak as repo
from app.schemas.streak import StreakRead
from app.services import notification as notifications

MILESTONES = (3, 7, 14, 30, 50, 100, 365)
FREEZE_EVERY = 7
MAX_FREEZES = 2
REMINDER_HOUR = 19
REMINDER_MIN_STREAK = 2


@dataclass(frozen=True)
class Settled:
    current: int
    last_active_date: date | None
    frozen_date: date | None
    freezes: int
    outcome: str | None = None
    lost: int = 0

    @property
    def covered_through(self) -> date | None:
        """The latest day the streak covers, by activity or by a freeze."""
        if self.frozen_date and self.last_active_date and self.frozen_date > self.last_active_date:
            return self.frozen_date
        return self.last_active_date


def _settled(streak: UserStreak | None, today: date) -> Settled:
    """The streak after accounting for days missed before today. A freeze covers one missed day, and only
    when the day before it was active; two missed days in a row end the streak."""
    if streak is None:
        return Settled(0, None, None, 0)
    state = Settled(streak.current_count, streak.last_active_date, streak.frozen_date, streak.freezes_available)
    covered = state.covered_through
    if state.current == 0 or covered is None or (today - covered).days <= 1:
        return state
    if (today - covered).days == 2 and state.freezes > 0 and covered == state.last_active_date:
        frozen = today - timedelta(days=1)
        return Settled(state.current, state.last_active_date, frozen, state.freezes - 1, "saved")
    return Settled(0, state.last_active_date, state.frozen_date, state.freezes, "lost", lost=state.current)


def _today(user: User, now: datetime) -> date:
    return local_now(now, user.timezone).date()


def _get_or_create(db: Session, user: User) -> UserStreak:
    streak = repo.get(db, user.id)
    if streak is not None:
        return streak
    try:
        streak = UserStreak(user_id=user.id, current_count=0, longest_count=0, freezes_available=0)
        repo.add(db, streak)
        db.commit()
    except IntegrityError:
        db.rollback()
        streak = repo.get(db, user.id)
    return streak


def _apply(streak: UserStreak, settled: Settled) -> None:
    streak.current_count = settled.current
    streak.frozen_date = settled.frozen_date
    streak.freezes_available = settled.freezes


def _announce_outcome(db: Session, user: User, settled: Settled, today: date) -> None:
    if settled.outcome == "saved":
        data = {"count": settled.current, "freezes_left": settled.freezes, "date": today.isoformat()}
        notifications.notify(db, user.id, "streak_saved", entity_type="streak", data=data)
    elif settled.outcome == "lost":
        notifications.notify(db, user.id, "streak_lost", entity_type="streak", data={"count": settled.lost})


def _settle(db: Session, user: User, streak: UserStreak, today: date) -> None:
    settled = _settled(streak, today)
    if settled.outcome is None:
        return
    _apply(streak, settled)
    db.commit()
    _announce_outcome(db, user, settled, today)


def record_activity(db: Session, user: User, now: datetime | None = None) -> None:
    """Count today for the user. Idempotent within a local day."""
    now = now or utcnow()
    today = _today(user, now)
    streak = _get_or_create(db, user)
    _settle(db, user, streak, today)
    if streak.last_active_date is not None and streak.last_active_date >= today:
        return
    covered = _settled(streak, today).covered_through
    continuing = streak.current_count > 0 and covered == today - timedelta(days=1)
    streak.current_count = streak.current_count + 1 if continuing else 1
    streak.last_active_date = today
    streak.longest_count = max(streak.longest_count, streak.current_count)
    if streak.current_count % FREEZE_EVERY == 0:
        streak.freezes_available = min(MAX_FREEZES, streak.freezes_available + 1)
    db.commit()
    if streak.current_count in MILESTONES:
        notifications.notify(db, user.id, "streak_milestone", entity_type="streak", data={"count": streak.current_count})


def _hours_left(user: User, today: date, now: datetime) -> float:
    return round((next_midnight(today, user.timezone) - now).total_seconds() / 3600, 2)


def get_streak(db: Session, user: User, now: datetime | None = None) -> StreakRead:
    now = now or utcnow()
    today = _today(user, now)
    streak = repo.get(db, user.id)
    settled = _settled(streak, today)
    return StreakRead(
        current=settled.current,
        longest=streak.longest_count if streak else 0,
        active_today=settled.current > 0 and settled.last_active_date == today,
        freezes_available=settled.freezes,
        hours_left_today=_hours_left(user, today, now),
        next_milestone=next((m for m in MILESTONES if m > settled.current), None),
    )


def current_streaks(db: Session, users: list[User], now: datetime | None = None) -> dict:
    """{user_id: current streak} as of now, for showing on profiles."""
    now = now or utcnow()
    streaks = repo.get_many(db, [u.id for u in users])
    return {u.id: _settled(streaks.get(u.id), _today(u, now)).current for u in users}


def current_streak(db: Session, user: User, now: datetime | None = None) -> int:
    return current_streaks(db, [user], now)[user.id]


def send_reminders(db: Session, now: datetime | None = None) -> int:
    """Hourly job: remind people with a streak of 2+ who haven't counted today, during 19:00-20:00 local
    time, at most once a day. Returns how many were reminded."""
    now = now or utcnow()
    reminded = 0
    for streak, user in repo.running(db, at_least=REMINDER_MIN_STREAK):
        local = local_now(now, user.timezone)
        today = local.date()
        if local.hour != REMINDER_HOUR or streak.last_reminded_date == today:
            continue
        _settle(db, user, streak, today)
        covered = _settled(streak, today).covered_through
        if streak.current_count < REMINDER_MIN_STREAK or covered != today - timedelta(days=1):
            continue
        streak.last_reminded_date = today
        db.commit()
        data = {"count": streak.current_count, "hours_left": int(_hours_left(user, today, now))}
        notifications.notify(db, user.id, "streak_reminder", entity_type="streak", data=data, now=now)
        reminded += 1
    return reminded


def check_lapsed(db: Session, now: datetime | None = None) -> int:
    """Hourly job: once a user's local midnight passes after a missed day, use a freeze (streak_saved) or
    end the streak (streak_lost). Returns how many streaks changed."""
    now = now or utcnow()
    changed = 0
    for streak, user in repo.running(db):
        before = streak.current_count, streak.freezes_available
        _settle(db, user, streak, _today(user, now))
        changed += before != (streak.current_count, streak.freezes_available)
    return changed
