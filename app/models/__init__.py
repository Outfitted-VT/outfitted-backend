# Import every model here so Base.metadata knows about it.
# Alembic imports this package to autogenerate migrations.
from app.db.base import Base
from app.models.comment import FitComment
from app.models.conversation import Conversation, ConversationMember, FitCheckVote, Message
from app.models.detection import ImageDetection
from app.models.device import DeviceToken
from app.models.engagement import FitLike, FitSave
from app.models.fit import Fit, FitImage, FitItem, FitTag
from app.models.follow import Follow
from app.models.image import Image
from app.models.impact import ReturnImpactRecord
from app.models.memory import OutfitMemory
from app.models.message import DirectMessage
from app.models.notification import Notification, NotificationSettings
from app.models.refresh_token import RefreshToken
from app.models.sizing import UserReferenceGarment
from app.models.story import Story, StoryView
from app.models.streak import UserStreak
from app.models.tryon import TryOn, TryOnPiece
from app.models.user import User
from app.models.vote import FitVote
from app.models.wardrobe import WardrobeItem

__all__ = [
    "Base",
    "Conversation",
    "ConversationMember",
    "DeviceToken",
    "DirectMessage",
    "Fit",
    "FitComment",
    "FitCheckVote",
    "FitImage",
    "FitItem",
    "FitLike",
    "FitSave",
    "FitTag",
    "FitVote",
    "Follow",
    "Image",
    "ImageDetection",
    "Message",
    "Notification",
    "NotificationSettings",
    "OutfitMemory",
    "RefreshToken",
    "ReturnImpactRecord",
    "Story",
    "StoryView",
    "TryOn",
    "TryOnPiece",
    "User",
    "UserReferenceGarment",
    "UserStreak",
    "WardrobeItem",
]
