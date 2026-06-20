from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from pymongo import IndexModel


@dataclass(frozen=True)
class IndexSpec:
    keys: Sequence[tuple[str, Any]]
    name: str | None = None
    unique: bool = False
    sparse: bool = False
    expire_after_seconds: int | None = None
    partial_filter: Mapping[str, Any] | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("IndexSpec.keys must not be empty")
        for key in self.keys:
            if not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str):
                raise ValueError("IndexSpec.keys must contain (field_name, direction) tuples")

    def to_index_model(self) -> IndexModel:
        kwargs = dict(self.options)
        if self.name is not None:
            kwargs["name"] = self.name
        if self.unique:
            kwargs["unique"] = True
        if self.sparse:
            kwargs["sparse"] = True
        if self.expire_after_seconds is not None:
            kwargs["expireAfterSeconds"] = self.expire_after_seconds
        if self.partial_filter is not None:
            kwargs["partialFilterExpression"] = dict(self.partial_filter)
        return IndexModel(list(self.keys), **kwargs)
