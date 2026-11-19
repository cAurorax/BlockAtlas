"""Validated API request contracts."""

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=72)


class Registration(Credentials):
    nickname: str = Field(min_length=1, max_length=24)

    @field_validator("nickname")
    @classmethod
    def nickname_not_blank(cls, value):
        if not value.strip():
            raise ValueError("昵称不能为空")
        return value.strip()


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=72)


class PostInput(BaseModel):
    attach_pack: bool = False
    mod_slug: str = Field(default="", max_length=80)
    effect_second: int = Field(default=0, ge=0, le=86400)
    content: str = Field(default="", max_length=3000)
    tags: list[str] = Field(default_factory=list, max_length=5)
    media_ids: list[int] = Field(default_factory=list, max_length=9)
    visibility: Literal["public", "friends", "private"] = "public"

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values):
        tags = list(dict.fromkeys(x.strip().lstrip("#") for x in values))
        if any(not x or len(x) > 20 for x in tags):
            raise ValueError("每个标签须为 1 至 20 个字符")
        return tags


class CommentInput(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    parent_id: int | None = None


class RatingInput(BaseModel):
    score: int = Field(ge=1, le=5, strict=True)


class FriendInput(BaseModel):
    user_id: int


class FriendDecision(BaseModel):
    action: Literal["accept", "reject"]


class ToggleInput(BaseModel):
    enabled: bool


class WordInput(BaseModel):
    word: str = Field(min_length=1, max_length=30)
