from pydantic import BaseModel, Field


class StreakRead(BaseModel):
    current: int
    longest: int
    active_today: bool = Field(description="Whether today already counts (in your timezone).")
    freezes_available: int = Field(description="Each covers one missed day automatically. Earn 1 per 7 days, max 2.")
    hours_left_today: float = Field(description="Hours until your local midnight.")
    next_milestone: int | None = Field(description="The next of 3, 7, 14, 30, 50, 100, 365; null past 365.")
