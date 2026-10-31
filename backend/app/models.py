from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional
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

class SearchQuery(BaseModel):
    query: str
