from datetime import datetime, timezone
from typing import Any, Callable, ClassVar, Sequence

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ant_mongo.index import AntIndex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AntDoc(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_by_name=True,
        validate_by_alias=True,
        extra="forbid",
    )

    id: Any | None = Field(default=None)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 0

    ant_collection: ClassVar[str | None] = None
    ant_indexes: ClassVar[Sequence[AntIndex]] = ()
    ant_timestamps: ClassVar[bool] = True
    ant_optimistic_lock: ClassVar[bool] = True
    ant_id_factory: ClassVar[Callable[[], Any] | None] = ObjectId
    ant_id_type: ClassVar[type[Any] | None] = ObjectId

    @field_serializer("id", when_used="json")
    def serialize_id(self, value: Any) -> Any:
        if isinstance(value, ObjectId):
            return str(value)
        return value
