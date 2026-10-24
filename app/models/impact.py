import uuid

from sqlalchemy import Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ReturnImpactRecord(TimestampMixin, Base):
    """
    Tracks prevented returns, averted wrong-size purchases, and wallet savings
    driven by Outfitted's sizing intelligence, peer fit checks, and virtual try-ons.
    """

    __tablename__ = "return_impact_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fits.id", ondelete="SET NULL"), nullable=True)
    item_name: Mapped[str] = mapped_column(String(140))
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    estimated_price: Mapped[float] = mapped_column(Float, default=65.0, server_default="65.0")
    # Action that prevented return: "size_corrected", "avoided_bad_cut", "fit_check_voted_rethink", "confirmed_first_try"
    action_type: Mapped[str] = mapped_column(String(50))
    dollars_saved: Mapped[float] = mapped_column(Float, default=32.0, server_default="32.0")
    co2_saved_kg: Mapped[float] = mapped_column(Float, default=1.8, server_default="1.8")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
