from typing import Any, AsyncIterator, Mapping, Protocol, Sequence

from antonic.index import AntIndex
from antonic.registry import AntDocMeta
from antonic.results import DeleteResult, UpdateResult


class AntBackend(Protocol):
    def collection(self, meta: AntDocMeta) -> Any:
        ...

    def raw_collection(self, name: str) -> Any:
        ...

    async def insert(
        self,
        meta: AntDocMeta,
        document: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        ...

    async def replace_one(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        replacement: Mapping[str, Any],
        *,
        upsert: bool = False,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> UpdateResult:
        ...

    async def find_one(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        projection: Any = None,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        ...

    def find(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        projection: Any = None,
        sort: Any = None,
        limit: int | None = None,
        skip: int | None = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Mapping[str, Any]]:
        ...

    async def find_one_and_update(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
        projection: Any = None,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        ...

    async def update_one(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> UpdateResult:
        ...

    async def update_many(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
        backend_options: Mapping[str, Any] | None = None,
    ) -> UpdateResult:
        ...

    async def delete_one(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> DeleteResult:
        ...

    async def delete_many(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> DeleteResult:
        ...

    async def count(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        skip: int | None = None,
        limit: int | None = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> int:
        ...

    async def distinct(
        self,
        meta: AntDocMeta,
        key: str,
        filter: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        ...

    async def ensure_indexes(
        self,
        meta: AntDocMeta,
        indexes: Sequence[AntIndex],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> list[str]:
        ...
