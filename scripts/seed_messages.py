"""Seed demo people, a direct chat, and a circle with a fit check, so the inbox isn't empty in dev.

Run from the repo root, against the database in DATABASE_URL (never runs on its own):

    python -m scripts.seed_messages
    python -m scripts.seed_messages --email you@example.com

The first creates a demo account (printed at the end); the second seeds chats for your own account.

Safe to run more than once: existing people and chats are reused.
"""

import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.conversation import Conversation, ConversationMember
from app.models.user import User
from app.repositories import user as user_repository
from app.schemas.conversation import ConversationCreate, MessageCreate, ProductIn
from app.schemas.user import UserCreate
from app.services import conversation as conversations
from app.services import follow as follows
from app.services.image import upload_image
from app.services.user import create_user
from app.storage import get_storage

PASSWORD = "outfitted-demo"
DEMO = ("sofoniyas", "Sofoniyas", "sofoniyas@example.com")
FRIENDS = [
    ("mayamakesfits", "Maya Chen", "maya@example.com"),
    ("jordy.jpg", "Jordan Lee", "jordan@example.com"),
    ("sophia.morin", "Sophia Morin", "sophia@example.com"),
]
CIRCLE_TITLE = "Gallery night"


def get_or_create(db, username: str, full_name: str, email: str) -> User:
    existing = user_repository.get_by_username(db, username) or user_repository.get_by_email(db, email)
    if existing:
        return existing
    return create_user(db, UserCreate(email=email, username=username, password=PASSWORD, full_name=full_name))


def look_photo() -> bytes:
    image = Image.new("RGB", (800, 1000), "#EFEDE6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((260, 180, 540, 640), fill="#121212")
    draw.polygon([(300, 640), (500, 640), (580, 940), (220, 940)], fill="#D9D3C7")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def existing_circle(db, user: User) -> Conversation | None:
    return db.scalar(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == user.id, Conversation.title == CIRCLE_TITLE)
    )


def send_text(db, user: User, conversation_id, body: str) -> None:
    conversations.send_message(db, user, conversation_id, MessageCreate(kind="text", body=body))


def seed_circle(db, me: User, maya: User, jordan: User, sophia: User) -> None:
    if existing_circle(db, me):
        print(f"Circle '{CIRCLE_TITLE}' already exists, skipping")
        return
    circle, _ = conversations.create_conversation(
        db, me, ConversationCreate(type="circle", member_ids=[maya.id, jordan.id, sophia.id], title=CIRCLE_TITLE)
    )
    photo = upload_image(db, get_storage(), me, look_photo())
    check = conversations.send_message(
        db, me, circle.id,
        MessageCreate(kind="fit_check", image_id=photo.id, question="Is the satin skirt too dressed up with chunky boots?", context="Vernissage · 18°C"),
    )
    for voter, choice in ((maya, "wear"), (sophia, "wear"), (jordan, "rethink")):
        conversations.vote(db, voter, check.id, choice)
    send_text(db, sophia, circle.id, "10/10 silhouette. The boots make it.")
    conversations.send_message(
        db, maya, circle.id,
        MessageCreate(kind="product", body="Or try these instead?", product=ProductIn(name="Chunky Loafers", color="Black", price="$320")),
    )
    print(f"Created circle '{CIRCLE_TITLE}'")


def seed_direct(db, me: User, maya: User) -> None:
    direct, created = conversations.create_conversation(db, me, ConversationCreate(type="direct", member_ids=[maya.id]))
    if not created:
        print("Direct chat with Maya already exists, skipping")
        return
    send_text(db, me, direct.id, "Are we still thrifting Saturday?")
    send_text(db, maya, direct.id, "Yes! See you at 11.")
    send_text(db, maya, direct.id, "Bring the tote, I found a jacket you need to try.")
    print("Created direct chat with Maya")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", help="Your existing account's email; its chats get seeded instead of the demo account's.")
    args = parser.parse_args()

    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        me = user_repository.get_by_email(db, args.email) if args.email else get_or_create(db, *DEMO)
        if me is None:
            sys.exit(f"No account with email {args.email}. Sign up in the app first.")
        maya, jordan, sophia = (get_or_create(db, *friend) for friend in FRIENDS)
        for friend in (maya, jordan, sophia):
            follows.follow(db, me, friend.username)
            follows.follow(db, friend, me.username)
        seed_circle(db, me, maya, jordan, sophia)
        seed_direct(db, me, maya)
    finally:
        db.close()

    print(f"\nSeeded messages for {me.email}.")
    if not args.email:
        print(f"Sign in as {DEMO[2]} / {PASSWORD}")
    print(f"Friends sign in with their email and password '{PASSWORD}'.")


if __name__ == "__main__":
    main()
