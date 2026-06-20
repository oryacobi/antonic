from typing import Any, AsyncIterator, Mapping, Sequence, Type, TypeVar, overload

from ant.backend import AntBackend
from ant.doc import AntDoc, utcnow
from ant.errors import AntDocNotFoundError, InvalidAntQueryError, OptimisticLockError, UnsupportedAntCapabilityError
from ant.naming import CollectionNamingStrategy, default_collection_name
from ant.query import validate_projection, validate_query, validate_sort, validate_update
from ant.registry import AntDocMeta, AntDocRegistry
from ant.results import DeleteResult, UpdateResult

T = TypeVar("T", bound=AntDoc)


class AntConnector:
    def __init__(
        self,
        backend: AntBackend,
        naming_strategy: CollectionNamingStrategy = default_collection_name,
        *,
        strict_registration: bool = False,
    ) -> None:
        self.backend = backend
        self.registry = AntDocRegistry(naming_strategy, strict=strict_registration)

    @overload
    def register(self, doc_type: Type[T]) -> AntDocMeta:
        ...

    @overload
    def register(self, doc_type: Type[AntDoc], *doc_types: Type[AntDoc]) -> tuple[AntDocMeta, ...]:
        ...

    def register(self, doc_type: Type[AntDoc], *doc_types: Type[AntDoc]) -> AntDocMeta | tuple[AntDocMeta, ...]:
        metas = tuple(self.registry.register(item) for item in (doc_type, *doc_types))
        return metas[0] if len(metas) == 1 else metas

    def collection(self, doc_type: Type[AntDoc]) -> Any:
        return self.backend.collection(self.registry.resolve(doc_type))

    def raw_collection(self, name: str) -> Any:
        return self.backend.raw_collection(name)

    async def save(
        self,
        ant_doc: T,
        *,
        upsert: bool = False,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> T:
        meta = self.registry.resolve(type(ant_doc))
        if ant_doc.id is None or (meta.optimistic_lock and ant_doc.version == 0):
            return await self.insert(ant_doc, backend_options=backend_options)
        return await self.update(ant_doc, upsert=upsert, backend_options=backend_options, **where)

    async def insert(
        self,
        ant_doc: T,
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> T:
        meta = self.registry.resolve(type(ant_doc))
        now = utcnow()
        updates: dict[str, Any] = {}

        if ant_doc.id is None and meta.id_factory is not None:
            updates["id"] = meta.id_factory()
        if meta.timestamps:
            updates["created_at"] = ant_doc.created_at or now
            updates["updated_at"] = now
        if meta.optimistic_lock:
            updates["version"] = 1

        next_doc = ant_doc.model_copy(update=updates)
        stored = await self.backend.insert(
            meta,
            self._to_document(next_doc),
            backend_options=backend_options,
        )
        if next_doc.id is None and stored.get("id") is not None:
            next_doc = next_doc.model_copy(update={"id": stored["id"]})
        return next_doc

    async def update(
        self,
        ant_doc: T,
        *,
        upsert: bool = False,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> T:
        if ant_doc.id is None:
            raise AntDocNotFoundError("Cannot update AntDoc without id")

        meta = self.registry.resolve(type(ant_doc))
        old_version = ant_doc.version
        changes: dict[str, Any] = {}
        if meta.timestamps:
            changes["updated_at"] = utcnow()
        if meta.optimistic_lock:
            changes["version"] = old_version + 1

        next_doc = ant_doc.model_copy(update=changes)
        query = self._query(type(ant_doc), {"id": ant_doc.id}, where)
        if meta.optimistic_lock:
            query["version"] = old_version
        validate_sort(sort)

        result = await self.backend.replace_one(
            meta,
            query,
            self._to_document(next_doc),
            upsert=upsert,
            sort=sort,
            backend_options=backend_options,
        )
        if result.matched_count == 0 and result.upserted_id is None:
            if meta.optimistic_lock:
                raise OptimisticLockError(type(ant_doc).__name__)
            raise AntDocNotFoundError(type(ant_doc).__name__)
        return next_doc

    async def get(
        self,
        doc_type: Type[T],
        id: Any = None,
        filter: Mapping[str, Any] | None = None,
        *,
        projection: Any = None,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> T | None:
        query = self._query(doc_type, filter, where)
        if id is not None:
            query["id"] = id
        validate_projection(projection)
        validate_sort(sort)

        meta = self.registry.resolve(doc_type)
        doc = await self.backend.find_one(
            meta,
            validate_query(query),
            projection=projection,
            sort=sort,
            backend_options=backend_options,
        )
        return None if doc is None else self._from_document(doc_type, doc)

    async def find(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        projection: Any = None,
        sort: Any = None,
        limit: int | None = None,
        skip: int | None = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> list[T]:
        return [
            item
            async for item in self.iter_find(
                doc_type,
                filter,
                projection=projection,
                sort=sort,
                limit=limit,
                skip=skip,
                backend_options=backend_options,
                **where,
            )
        ]

    async def iter_find(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        projection: Any = None,
        sort: Any = None,
        limit: int | None = None,
        skip: int | None = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> AsyncIterator[T]:
        validate_projection(projection)
        validate_sort(sort)
        meta = self.registry.resolve(doc_type)
        async for doc in self.backend.find(
            meta,
            self._query(doc_type, filter, where),
            projection=projection,
            sort=sort,
            limit=limit,
            skip=skip,
            backend_options=backend_options,
        ):
            yield self._from_document(doc_type, doc)

    async def patch(
        self,
        doc_type: Type[T],
        changes: Mapping[str, Any],
        id: Any = None,
        filter: Mapping[str, Any] | None = None,
        *,
        expected_version: int | None = None,
        upsert: bool = False,
        projection: Any = None,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> T | None:
        self._ensure_patchable_changes(changes)
        meta = self.registry.resolve(doc_type)
        query = self._query(doc_type, filter, where)
        if id is not None:
            query["id"] = id
        if expected_version is not None:
            query["version"] = expected_version
        query = validate_query(query)
        validate_projection(projection)
        validate_sort(sort)

        set_values = dict(changes)
        if meta.timestamps:
            set_values["updated_at"] = utcnow()

        update_doc: dict[str, Any] = {}
        if set_values:
            update_doc["$set"] = set_values
        if meta.optimistic_lock:
            update_doc["$inc"] = {"version": 1}
        update_doc = validate_update(update_doc)

        doc = await self.backend.find_one_and_update(
            meta,
            query,
            update_doc,
            upsert=upsert,
            projection=projection,
            sort=sort,
            backend_options=backend_options,
        )
        return None if doc is None else self._from_document(doc_type, doc)

    async def update_one(
        self,
        doc_type: Type[T],
        update: Mapping[str, Any],
        filter: Mapping[str, Any] | None = None,
        *,
        upsert: bool = False,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> UpdateResult:
        validate_sort(sort)
        meta = self.registry.resolve(doc_type)
        return await self.backend.update_one(
            meta,
            self._query(doc_type, filter, where),
            validate_update(update),
            upsert=upsert,
            sort=sort,
            backend_options=backend_options,
        )

    async def update_many(
        self,
        doc_type: Type[T],
        update: Mapping[str, Any],
        filter: Mapping[str, Any] | None = None,
        *,
        upsert: bool = False,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> UpdateResult:
        meta = self.registry.resolve(doc_type)
        return await self.backend.update_many(
            meta,
            self._query(doc_type, filter, where),
            validate_update(update),
            upsert=upsert,
            backend_options=backend_options,
        )

    async def delete(
        self,
        ant_doc: AntDoc,
        *,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> bool:
        if ant_doc.id is None:
            return False
        result = await self.delete_one(
            type(ant_doc),
            {"id": ant_doc.id},
            backend_options=backend_options,
            **where,
        )
        return result.deleted_count == 1

    async def delete_one(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> DeleteResult:
        meta = self.registry.resolve(doc_type)
        return await self.backend.delete_one(
            meta,
            self._query(doc_type, filter, where),
            backend_options=backend_options,
        )

    async def delete_many(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> DeleteResult:
        meta = self.registry.resolve(doc_type)
        return await self.backend.delete_many(
            meta,
            self._query(doc_type, filter, where),
            backend_options=backend_options,
        )

    async def count(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        skip: int | None = None,
        limit: int | None = None,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> int:
        meta = self.registry.resolve(doc_type)
        return await self.backend.count(
            meta,
            self._query(doc_type, filter, where),
            skip=skip,
            limit=limit,
            backend_options=backend_options,
        )

    async def distinct(
        self,
        doc_type: Type[T],
        key: str,
        filter: Mapping[str, Any] | None = None,
        *,
        backend_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> list[Any]:
        validate_projection([key])
        meta = self.registry.resolve(doc_type)
        return await self.backend.distinct(
            meta,
            key,
            self._query(doc_type, filter, where),
            backend_options=backend_options,
        )

    async def aggregate(
        self,
        doc_type: Type[T],
        pipeline: Sequence[Mapping[str, Any]],
        *,
        as_type: Type[T] | None = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        aggregate = getattr(self.backend, "aggregate", None)
        if aggregate is None:
            raise UnsupportedAntCapabilityError("backend does not support aggregate")

        rows = await aggregate(
            self.registry.resolve(doc_type),
            list(pipeline),
            backend_options=backend_options,
        )
        if as_type is None:
            return rows
        return [self._from_document(as_type, doc) for doc in rows]

    async def ensure_indexes(
        self,
        *doc_types: Type[AntDoc],
        backend_options: Mapping[str, Any] | None = None,
    ) -> dict[Type[AntDoc], list[str]]:
        targets = doc_types or tuple(self.registry.registered_types())
        created: dict[Type[AntDoc], list[str]] = {}
        for doc_type in targets:
            meta = self.registry.resolve(doc_type)
            created[doc_type] = await self.backend.ensure_indexes(
                meta,
                meta.indexes,
                backend_options=backend_options,
            )
        return created

    def _query(
        self,
        doc_type: Type[AntDoc],
        filter: Mapping[str, Any] | None,
        where: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.registry.resolve(doc_type)
        query = dict(filter or {})
        query.update(where)
        return validate_query(query)

    def _to_document(self, ant_doc: AntDoc) -> dict[str, Any]:
        return ant_doc.model_dump(mode="python", by_alias=False)

    def _from_document(self, doc_type: Type[T], doc: Mapping[str, Any]) -> T:
        return doc_type.model_validate(dict(doc))

    def _ensure_patchable_changes(self, changes: Mapping[str, Any]) -> None:
        for field in changes:
            if not isinstance(field, str):
                raise InvalidAntQueryError("patch field names must be strings")
            if field == "id" or field.startswith("id.") or field == "_id" or field.startswith("_id."):
                raise InvalidAntQueryError("patch cannot change id")
