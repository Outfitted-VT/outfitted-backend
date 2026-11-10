from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from app.services import streak as streaks
from tests.conftest import AuthedUser

USERS_URL = "/api/v1/users"
NEW_YORK = ZoneInfo("America/New_York")


def at(year, month, day, hour=12, minute=0, second=0, tz=NEW_YORK) -> datetime:
    """A local wall-clock time, as the UTC instant the server sees."""
    return datetime(year, month, day, hour, minute, second, tzinfo=tz).astimezone(UTC)


@pytest.fixture
def jane(create_user) -> AuthedUser:
    return create_user("jane", "Jane Doe")


@pytest.fixture
def user(client: TestClient, db: Session, jane: AuthedUser) -> User:
    response = client.patch(f"{USERS_URL}/me", headers=jane.headers, json={"timezone": "America/New_York"})
    assert response.status_code == 200, response.text
    return db.get(User, jane.id)


def active_days(db: Session, user: User, start: datetime, days: int) -> datetime:
    for offset in range(days):
        streaks.record_activity(db, user, start + timedelta(days=offset))
    return start + timedelta(days=days - 1)


def view(db: Session, user: User, now: datetime):
    return streaks.get_streak(db, user, now)


def kinds(db: Session, user: User) -> list[str]:
    rows = db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.created_at)
    return [n.type for n in rows]


def test_timezone_is_validated(client: TestClient, jane) -> None:
    assert client.patch(f"{USERS_URL}/me", headers=jane.headers, json={"timezone": "Mars/Base"}).status_code == 422
    assert client.patch(f"{USERS_URL}/me", headers=jane.headers, json={"timezone": "/etc/passwd"}).status_code == 422
    me = client.get(f"{USERS_URL}/me", headers=jane.headers).json()
    assert me["timezone"] == "UTC" and me["current_streak"] == 0


def test_activity_is_idempotent_within_a_day(db, user) -> None:
    morning = at(2026, 6, 1, 8)
    streaks.record_activity(db, user, morning)
    streaks.record_activity(db, user, morning + timedelta(hours=10))

    streak = view(db, user, morning + timedelta(hours=11))
    assert (streak.current, streak.longest, streak.active_today) == (1, 1, True)


def test_consecutive_days_count_up(db, user) -> None:
    last = active_days(db, user, at(2026, 6, 1), 5)

    streak = view(db, user, last)
    assert (streak.current, streak.longest, streak.next_milestone) == (5, 5, 7)


def test_days_follow_the_users_timezone(db, user) -> None:
    streaks.record_activity(db, user, datetime(2026, 6, 2, 3, 0, tzinfo=UTC))
    streaks.record_activity(db, user, datetime(2026, 6, 2, 5, 0, tzinfo=UTC))

    assert view(db, user, datetime(2026, 6, 2, 5, 0, tzinfo=UTC)).current == 2


def test_midnight_edges(db, user) -> None:
    streaks.record_activity(db, user, at(2026, 6, 1, 23, 59, 59))
    streaks.record_activity(db, user, at(2026, 6, 2, 0, 0, 0))

    assert view(db, user, at(2026, 6, 2, 0, 0, 1)).current == 2
    end_of_day = view(db, user, at(2026, 6, 2, 23, 59, 59))
    assert end_of_day.active_today is True
    assert end_of_day.hours_left_today == 0.0
    next_day = view(db, user, at(2026, 6, 3, 0, 0, 0))
    assert (next_day.current, next_day.active_today) == (2, False)


def test_dst_days_have_23_and_25_hours(db, user) -> None:
    assert view(db, user, at(2026, 3, 8, 0, 0)).hours_left_today == 23.0
    assert view(db, user, at(2026, 11, 1, 0, 0)).hours_left_today == 25.0
    assert view(db, user, at(2026, 6, 1, 0, 0)).hours_left_today == 24.0


def test_streak_continues_across_dst_changes(db, user) -> None:
    streaks.record_activity(db, user, at(2026, 3, 7, 23, 30))
    streaks.record_activity(db, user, at(2026, 3, 8, 23, 30))
    assert view(db, user, at(2026, 3, 8, 23, 45)).current == 2

    streaks.record_activity(db, user, at(2026, 10, 31, 23, 30))
    streaks.record_activity(db, user, at(2026, 11, 1, 1, 30))
    streaks.record_activity(db, user, at(2026, 11, 2, 0, 15))
    assert view(db, user, at(2026, 11, 2, 1)).current == 3


def test_freeze_earned_every_7_days_max_2(db, user) -> None:
    start = at(2026, 6, 1)
    assert view(db, user, active_days(db, user, start, 6)).freezes_available == 0
    assert view(db, user, active_days(db, user, start + timedelta(days=6), 1)).freezes_available == 1
    last = active_days(db, user, start + timedelta(days=7), 14)
    assert view(db, user, last).freezes_available == 2


def test_missed_day_uses_a_freeze(db, user) -> None:
    last = active_days(db, user, at(2026, 6, 1), 7)

    assert streaks.check_lapsed(db, at(2026, 6, 8, 23, 59)) == 0
    assert streaks.check_lapsed(db, at(2026, 6, 9, 0, 30)) == 1
    assert streaks.check_lapsed(db, at(2026, 6, 9, 1, 30)) == 0

    saved = view(db, user, at(2026, 6, 9, 9))
    assert (saved.current, saved.freezes_available, saved.active_today) == (7, 0, False)
    assert kinds(db, user)[-1] == "streak_saved"
    streaks.record_activity(db, user, at(2026, 6, 9, 9))
    assert view(db, user, at(2026, 6, 9, 10)).current == 8
    assert last < at(2026, 6, 9)


def test_freeze_is_used_on_the_next_activity_if_the_job_missed_it(db, user) -> None:
    active_days(db, user, at(2026, 6, 1), 7)

    streaks.record_activity(db, user, at(2026, 6, 9, 12))

    streak = view(db, user, at(2026, 6, 9, 13))
    assert (streak.current, streak.freezes_available) == (8, 0)


def test_two_missed_days_reset_even_with_freezes(db, user) -> None:
    active_days(db, user, at(2026, 6, 1), 14)
    assert view(db, user, at(2026, 6, 14, 13)).freezes_available == 2

    streaks.check_lapsed(db, at(2026, 6, 16, 0, 30))
    assert view(db, user, at(2026, 6, 16, 1)).current == 14
    streaks.check_lapsed(db, at(2026, 6, 17, 0, 30))

    lost = view(db, user, at(2026, 6, 17, 9))
    assert (lost.current, lost.longest) == (0, 14)
    assert kinds(db, user)[-2:] == ["streak_saved", "streak_lost"]
    streaks.record_activity(db, user, at(2026, 6, 17, 9))
    assert view(db, user, at(2026, 6, 17, 10)).current == 1


def test_missed_day_without_freeze_resets(db, user) -> None:
    active_days(db, user, at(2026, 6, 1), 3)

    streaks.check_lapsed(db, at(2026, 6, 5, 0, 5))
    streaks.check_lapsed(db, at(2026, 6, 5, 1, 5))

    assert view(db, user, at(2026, 6, 5, 9)).current == 0
    assert kinds(db, user).count("streak_lost") == 1
    lost = db.query(Notification).filter(Notification.type == "streak_lost").one()
    assert lost.data["count"] == 3
    streaks.record_activity(db, user, at(2026, 6, 5, 9))
    assert view(db, user, at(2026, 6, 5, 10)).current == 1


def test_view_shows_a_lapsed_streak_before_the_job_runs(db, user) -> None:
    active_days(db, user, at(2026, 6, 1), 3)

    assert view(db, user, at(2026, 6, 5, 9)).current == 0
    assert streaks.current_streak(db, user, at(2026, 6, 5, 9)) == 0


def test_milestones_notify(db, user) -> None:
    active_days(db, user, at(2026, 6, 1), 7)

    milestones = db.query(Notification).filter(Notification.type == "streak_milestone").all()
    assert sorted(n.data["count"] for n in milestones) == [3, 7]


def test_reminder_in_the_evening_once_a_day(db, user) -> None:
    active_days(db, user, at(2026, 6, 1), 2)

    assert streaks.send_reminders(db, at(2026, 6, 3, 18, 59)) == 0
    assert streaks.send_reminders(db, at(2026, 6, 3, 19, 5)) == 1
    assert streaks.send_reminders(db, at(2026, 6, 3, 19, 55)) == 0
    assert streaks.send_reminders(db, at(2026, 6, 3, 20, 5)) == 0

    reminder = db.query(Notification).filter(Notification.type == "streak_reminder").one()
    assert reminder.data == {**reminder.data, "count": 2, "hours_left": 4}


def test_no_reminder_when_already_active_or_streak_short(db, client, create_user, user) -> None:
    active_days(db, user, at(2026, 6, 1), 3)
    other = db.get(User, create_user("solo").id)
    streaks.record_activity(db, other, datetime(2026, 6, 3, 12, tzinfo=UTC))

    assert streaks.send_reminders(db, at(2026, 6, 3, 19, 30)) == 0
    assert streaks.send_reminders(db, datetime(2026, 6, 4, 19, 30, tzinfo=UTC)) == 0


def test_streak_endpoints(client: TestClient, db, jane, user, upload_image, create_user) -> None:
    client.post("/api/v1/fits", headers=jane.headers, json={"image_ids": [upload_image(jane)]})

    streak = client.get(f"{USERS_URL}/me/streak", headers=jane.headers).json()
    assert streak["current"] == 1 and streak["longest"] == 1 and streak["active_today"] is True
    assert streak["freezes_available"] == 0 and streak["next_milestone"] == 3
    assert 0 < streak["hours_left_today"] <= 25
    assert client.get(f"{USERS_URL}/me", headers=jane.headers).json()["current_streak"] == 1
    viewer = create_user("viewer")
    assert client.get(f"{USERS_URL}/jane", headers=viewer.headers).json()["current_streak"] == 1


def test_vault_fits_dont_count_but_stories_and_fit_checks_do(client: TestClient, create_user, upload_image) -> None:
    def streak(user):
        return client.get(f"{USERS_URL}/me/streak", headers=user.headers).json()["current"]

    drafter = create_user("drafter")
    client.post("/api/v1/fits", headers=drafter.headers, json={"image_ids": [upload_image(drafter)], "privacy_tier": "vault"})
    assert streak(drafter) == 0

    storyteller = create_user("storyteller")
    client.post("/api/v1/stories", headers=storyteller.headers, json={"image_id": upload_image(storyteller)})
    assert streak(storyteller) == 1

    checker, friend = create_user("checker"), create_user("friend")
    client.put(f"{USERS_URL}/friend/follow", headers=checker.headers)
    chat = client.post(
        "/api/v1/conversations", headers=checker.headers, json={"type": "direct", "member_ids": [str(friend.id)]}
    ).json()["id"]
    client.post(f"/api/v1/conversations/{chat}/messages", headers=checker.headers, json={"kind": "text", "body": "hi"})
    assert streak(checker) == 0
    body = {"kind": "fit_check", "image_id": upload_image(checker), "question": "This?"}
    client.post(f"/api/v1/conversations/{chat}/messages", headers=checker.headers, json=body)
    assert streak(checker) == 1


def test_unknown_stored_timezone_falls_back_to_utc(db, user) -> None:
    user.timezone = "Not/AZone"
    db.commit()
    streaks.record_activity(db, user, datetime(2026, 6, 1, 23, tzinfo=UTC))

    assert view(db, user, datetime(2026, 6, 2, 0, 30, tzinfo=UTC)).active_today is False


def utc(year, month, day, hour=12, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def set_timezone(client: TestClient, db: Session, who: AuthedUser, name: str, now: datetime, monkeypatch) -> User:
    """PATCH /users/me with the server clock frozen at `now`."""
    monkeypatch.setattr(streaks, "utcnow", lambda: now)
    response = client.patch(f"{USERS_URL}/me", headers=who.headers, json={"timezone": name})
    assert response.status_code == 200, response.text
    user = db.get(User, who.id)
    db.refresh(user)
    return user


def test_story_then_timezone_change_still_counts_today(client, db, jane, upload_image, monkeypatch) -> None:
    # The reported bug: account is UTC, posts a story at 02:00 UTC (21:00 the day before in New York),
    # then the app sets America/New_York.
    monkeypatch.setattr(streaks, "utcnow", lambda: utc(2026, 11, 10, 2))
    response = client.post("/api/v1/stories", headers=jane.headers, json={"image_id": upload_image(jane)})
    assert response.status_code in (200, 201), response.text

    set_timezone(client, db, jane, "America/New_York", utc(2026, 11, 10, 2, 5), monkeypatch)

    streak = client.get(f"{USERS_URL}/me/streak", headers=jane.headers).json()
    assert (streak["current"], streak["active_today"]) == (1, True)


def test_utc_to_new_york_after_utc_midnight(client, db, jane, monkeypatch) -> None:
    utc_user = db.get(User, jane.id)
    streaks.record_activity(db, utc_user, utc(2026, 11, 9, 1))  # UTC day 11-09
    streaks.record_activity(db, utc_user, utc(2026, 11, 10, 2))  # UTC day 11-10 = NY 11-09 21:00
    assert view(db, utc_user, utc(2026, 11, 10, 2, 1)).current == 2

    user = set_timezone(client, db, jane, "America/New_York", utc(2026, 11, 10, 2, 5), monkeypatch)

    now = at(2026, 11, 9, 21, 30)
    streak = view(db, user, now)
    assert (streak.current, streak.active_today) == (2, True)
    streaks.record_activity(db, user, at(2026, 11, 9, 23, 59))  # same NY day: no double count
    assert view(db, user, at(2026, 11, 9, 23, 59)).current == 2

    next_day = view(db, user, at(2026, 11, 10, 0, 0))
    assert (next_day.current, next_day.active_today) == (2, False)
    streaks.record_activity(db, user, at(2026, 11, 10, 8))
    assert (view(db, user, at(2026, 11, 10, 8)).current, kinds(db, user)) == (3, ["streak_milestone"])


def test_utc_to_new_york_does_not_break_an_open_day(client, db, jane, monkeypatch) -> None:
    # Last counted at 01:00 UTC on 11-09 (20:00 NY on 11-08). It's 23:00 UTC on 11-10 and today isn't
    # counted yet. Re-reading that instant in New York would leave a 2-day gap; the streak must survive.
    utc_user = db.get(User, jane.id)
    streaks.record_activity(db, utc_user, utc(2026, 11, 8, 12))
    streaks.record_activity(db, utc_user, utc(2026, 11, 9, 1))

    user = set_timezone(client, db, jane, "America/New_York", utc(2026, 11, 10, 23), monkeypatch)

    streak = view(db, user, utc(2026, 11, 10, 23, 30))
    assert (streak.current, streak.active_today) == (2, False)
    assert streaks.check_lapsed(db, utc(2026, 11, 11, 0, 1)) == 0
    streaks.record_activity(db, user, at(2026, 11, 10, 22))
    assert view(db, user, at(2026, 11, 10, 22)).current == 3
    assert "streak_lost" not in kinds(db, user)


def test_new_york_to_utc_after_utc_midnight(client, db, jane, user, monkeypatch) -> None:
    streaks.record_activity(db, user, at(2026, 11, 8, 12))
    streaks.record_activity(db, user, at(2026, 11, 9, 23, 30))  # NY 11-09 = 04:30 UTC on 11-10

    user = set_timezone(client, db, jane, "UTC", utc(2026, 11, 10, 4, 35), monkeypatch)

    streak = view(db, user, utc(2026, 11, 10, 5))
    assert (streak.current, streak.active_today) == (2, True)
    streaks.record_activity(db, user, utc(2026, 11, 10, 18))  # same UTC day: no double count
    assert view(db, user, utc(2026, 11, 10, 18)).current == 2

    next_day = view(db, user, utc(2026, 11, 11, 0))
    assert (next_day.current, next_day.active_today) == (2, False)
    streaks.record_activity(db, user, utc(2026, 11, 11, 9))
    assert view(db, user, utc(2026, 11, 11, 9)).current == 3


def test_new_york_to_utc_before_utc_midnight(client, db, jane, user, monkeypatch) -> None:
    # Active on NY 11-09 at 18:00, switched to UTC at 23:30 UTC (still 11-09 in both): nothing moves.
    streaks.record_activity(db, user, at(2026, 11, 8, 12))
    streaks.record_activity(db, user, at(2026, 11, 9, 18))

    user = set_timezone(client, db, jane, "UTC", utc(2026, 11, 9, 23, 30), monkeypatch)

    assert view(db, user, utc(2026, 11, 9, 23, 45)).active_today is True
    after_midnight = view(db, user, utc(2026, 11, 10, 0, 30))
    assert (after_midnight.current, after_midnight.active_today) == (2, False)
    streaks.record_activity(db, user, utc(2026, 11, 10, 0, 30))
    assert view(db, user, utc(2026, 11, 10, 0, 30)).current == 3


def test_timezone_change_keeps_reminder_and_freeze_dates_in_step(client, db, jane, user, monkeypatch) -> None:
    active_days(db, user, at(2026, 11, 1, 12), 7)  # 11-01..11-07, earns a freeze
    assert streaks.send_reminders(db, at(2026, 11, 8, 19, 30)) == 1  # reminded on NY 11-08
    # 01:00 UTC on 11-09 is still 11-08 in NY; moving to UTC makes it 11-09 there.
    user = set_timezone(client, db, jane, "UTC", utc(2026, 11, 9, 1), monkeypatch)

    streak = view(db, user, utc(2026, 11, 9, 1))
    assert (streak.current, streak.freezes_available, streak.active_today) == (7, 1, False)
    # The open day they were reminded about is 11-09 in UTC: no second reminder for it.
    assert streaks.send_reminders(db, utc(2026, 11, 9, 19, 30)) == 0
    streaks.record_activity(db, user, utc(2026, 11, 9, 20))
    assert streaks.send_reminders(db, utc(2026, 11, 10, 19, 30)) == 1
