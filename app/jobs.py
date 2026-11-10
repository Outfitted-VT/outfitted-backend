"""Background jobs, run by APScheduler inside the app when RUN_SCHEDULER is true.

Only one process should run them, so the setting is off by default; turn it on for a single instance.
Each job opens its own database session and calls a service function that tests run directly.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.session import SessionLocal
from app.services import story as story_service
from app.services import streak as streak_service
from app.storage import get_storage

logger = logging.getLogger(__name__)


def streak_reminders() -> None:
    with SessionLocal() as db:
        logger.info("streak reminders sent: %s", streak_service.send_reminders(db))


def streak_checks() -> None:
    with SessionLocal() as db:
        logger.info("streaks saved or ended: %s", streak_service.check_lapsed(db))


def story_cleanup() -> None:
    with SessionLocal() as db:
        logger.info("expired stories removed: %s", story_service.cleanup_expired(db, get_storage()))


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(streak_reminders, CronTrigger(minute=5), id="streak_reminders")
    scheduler.add_job(streak_checks, CronTrigger(minute=1), id="streak_checks")
    scheduler.add_job(story_cleanup, CronTrigger(hour=3, minute=30), id="story_cleanup")
    return scheduler
