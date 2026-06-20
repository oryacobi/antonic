from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UpdateResult:
    matched_count: int
    modified_count: int
    upserted_id: Any | None = None


@dataclass(frozen=True)
class DeleteResult:
    deleted_count: int
