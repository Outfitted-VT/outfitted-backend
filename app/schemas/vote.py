from typing import Literal

from pydantic import BaseModel

VoteChoice = Literal["wear", "rethink"]


class FitVoteIn(BaseModel):
    """The body of PUT /fits/{fit_id}/vote."""

    choice: VoteChoice


class VoteCounts(BaseModel):
    """How a fit's votes stand. Both zero when nobody has voted."""

    wear: int = 0
    rethink: int = 0
