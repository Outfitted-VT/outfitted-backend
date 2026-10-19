from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page. `null` means this is the last page."
    )
