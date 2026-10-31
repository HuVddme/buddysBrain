from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, TypeAdapter, field_validator
from typing import Annotated, List, Literal, Optional
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


class UploadResourceOut(ResourceOut):
    duplicate: bool = False


ResourceTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ResourceDescription = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ResourceCourse = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ResourceCreate(BaseModel):
    """Validated link input, separate from stored/legacy resource responses."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: ResourceTitle
    description: ResourceDescription
    media_type: Literal["article", "video"]
    media_link: str = Field(min_length=1, max_length=2048)
    course: ResourceCourse

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
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
