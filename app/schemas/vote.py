from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

# Fits get this poll unless the poster picks another one (or none).
DEFAULT_POLL_QUESTION = "Would you wear it?"
DEFAULT_POLL_OPTIONS = ("Wear it", "Rethink")

PollQuestion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
PollAnswer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class PollIn(BaseModel):
    """A fit's poll: the question viewers answer and 2–4 answers to pick from."""

    question: PollQuestion
    options: list[PollAnswer] = Field(min_length=2, max_length=4)

    @field_validator("options")
    @classmethod
    def distinct_options(cls, options: list[str]) -> list[str]:
        if len({option.casefold() for option in options}) != len(options):
            raise ValueError("Each answer can only appear once")
        return options


def default_poll() -> PollIn:
    return PollIn(question=DEFAULT_POLL_QUESTION, options=list(DEFAULT_POLL_OPTIONS))


class PollOptionRead(BaseModel):
    label: str
    votes: int


class PollRead(BaseModel):
    """A fit's poll as a viewer sees it. Everyone sees the same tallies."""

    question: str
    options: list[PollOptionRead]
    total_votes: int
    my_vote: int | None = Field(description="Index of the answer you picked, or null.")
    locked: bool = Field(description="True once anyone has voted: the poll can't be changed.")

    @classmethod
    def of(cls, fit, counts: dict[int, int], my_vote: int | None) -> "PollRead | None":
        if fit.poll_question is None or not fit.poll_options:
            return None
        options = [
            PollOptionRead(label=label, votes=counts.get(i, 0))
            for i, label in enumerate(fit.poll_options)
        ]
        total = sum(option.votes for option in options)
        return cls(
            question=fit.poll_question,
            options=options,
            total_votes=total,
            my_vote=my_vote,
            locked=total > 0,
        )


class FitVoteIn(BaseModel):
    """The body of PUT /fits/{fit_id}/vote."""

    option: int = Field(ge=0, description="Index of the answer in the fit's poll.")
