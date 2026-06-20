from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AntIndex:
    keys: Sequence[tuple[str, Any]]
    name: str | None = None
    unique: bool = False
    sparse: bool = False
    expire_after_seconds: int | None = None
    partial_filter: Mapping[str, Any] | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.keys:
            raise ValueError("AntIndex.keys must not be empty")
        for key in self.keys:
            if not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str):
                raise ValueError("AntIndex.keys must contain (field_name, direction) tuples")
