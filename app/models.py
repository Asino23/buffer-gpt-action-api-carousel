from datetime import datetime
from ipaddress import ip_address
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class Channel(BaseModel):
    name: str
    platform: str
    channel_id: str


class PostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10_000)
    image_url: HttpUrl | None = None
    image_urls: list[HttpUrl] | None = Field(
        default=None, min_length=1, max_length=10
    )
    alt_text: str | None = Field(default=None, max_length=2_000)
    alt_texts: list[str] | None = Field(default=None, min_length=1, max_length=10)
    thread: list[str] | None = Field(default=None, min_length=2, max_length=100)

    @field_validator("channel_id", "text")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @staticmethod
    def validate_public_image_url(value: HttpUrl, field_name: str) -> HttpUrl:
        parsed = urlparse(str(value))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"{field_name} must use HTTPS")
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".local"):
            raise ValueError(f"{field_name} must use a public host")
        try:
            address = ip_address(host)
            if not address.is_global:
                raise ValueError(f"{field_name} must use a public host")
        except ValueError as exc:
            if "public host" in str(exc):
                raise
        return value

    @field_validator("image_url")
    @classmethod
    def safe_public_image_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return value
        return cls.validate_public_image_url(value, "image_url")

    @field_validator("image_urls")
    @classmethod
    def safe_public_image_urls(
        cls, value: list[HttpUrl] | None
    ) -> list[HttpUrl] | None:
        if value is None:
            return value
        return [
            cls.validate_public_image_url(image_url, "image_urls")
            for image_url in value
        ]

    @model_validator(mode="after")
    def validate_image_and_alt_texts(self) -> "PostRequest":
        if self.image_url is not None and self.image_urls is not None:
            raise ValueError("use image_url or image_urls, not both")
        if self.alt_text is not None and self.alt_texts is not None:
            raise ValueError("use alt_text or alt_texts, not both")
        if (
            self.alt_text is not None
            and self.image_url is None
            and self.image_urls is None
        ):
            raise ValueError("alt_text requires image_url or image_urls")
        if self.alt_texts is not None:
            image_count = len(
                self.image_urls or ([self.image_url] if self.image_url else [])
            )
            if image_count == 0:
                raise ValueError("alt_texts requires image_url or image_urls")
            if len(self.alt_texts) not in {1, image_count}:
                raise ValueError(
                    "alt_texts must contain one item or match image_urls length"
                )
        return self

    @field_validator("thread")
    @classmethod
    def validate_thread(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 10_000 for item in cleaned):
            raise ValueError("thread items must contain between 1 and 10000 characters")
        return cleaned

    @model_validator(mode="after")
    def thread_root_matches_text(self) -> "PostRequest":
        if self.thread is not None and self.thread[0] != self.text:
            raise ValueError("the first thread item must match text")
        return self


class ScheduledPostRequest(PostRequest):
    scheduled_at: datetime


class BatchScheduledPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posts: list[ScheduledPostRequest] = Field(min_length=1, max_length=20)


class PublishPostRequest(PostRequest):
    confirm_publish: bool

    @model_validator(mode="after")
    def publishing_must_be_confirmed(self) -> "PublishPostRequest":
        if self.confirm_publish is not True:
            raise ValueError("confirm_publish must be true")
        return self


class PostResult(BaseModel):
    id: str
    text: str | None = None
    due_at: datetime | None = None


class BatchPostResult(BaseModel):
    index: int
    channel_id: str
    scheduled_at: datetime
    success: bool
    id: str | None = None
    error: str | None = None


class BatchScheduleResult(BaseModel):
    success_count: int
    failure_count: int
    results: list[BatchPostResult]
