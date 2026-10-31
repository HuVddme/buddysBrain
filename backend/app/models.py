from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator
from typing import List, Literal, Optional
from .utils.objectid import PyObjectId
from bson import ObjectId

class ResourceModel(BaseModel):
    title: str
    description: str
    media_type: str
    media_link: str
    course: str
    summary: Optional[str] = ""
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow)
    embedding: Optional[List[float]] = None

class ResourceOut(ResourceModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    passage_count: int = 0

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {
            ObjectId: str,
            datetime: lambda v: v.isoformat(),
        }
    }


class BulkResourceCreate(BaseModel):
    """Admin link imports; derived content must come from backend processing."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    media_type: Literal["article", "video"]
    media_link: str = Field(min_length=1, max_length=2048)
    course: str = Field(min_length=1, max_length=200)

    @field_validator("media_link", mode="before")
    @classmethod
    def validate_link(cls, value):
        if not isinstance(value, str) or "\\" in value or any(
            ord(char) < 32 or ord(char) == 127 for char in value
        ):
            raise ValueError("Provide a valid HTTP or HTTPS URL.")
        url = TypeAdapter(HttpUrl).validate_python(value.strip())
        if url.username is not None or url.password is not None or url.port not in {80, 443}:
            raise ValueError("URLs must use port 80 or 443 and must not contain credentials.")
        return str(url)

class SearchQuery(BaseModel):
    query: str
