from typing import Any, AsyncIterator, ClassVar, Mapping, Sequence
from uuid import UUID

from bson import ObjectId
from pymongo import IndexModel, ReturnDocument
from pymongo.errors import DuplicateKeyError as PyMongoDuplicateKeyError

from ant.doc import AntDoc
from ant.errors import DuplicateAntDocError
from ant.index import AntIndex
from ant.query import validate_query
from ant.registry import AntDocMeta
from ant.results import DeleteResult, UpdateResult


class MongoObjectIdDoc(AntDoc):
    ant_id_factory: ClassVar[Any] = ObjectId
    ant_id_type: ClassVar[type[Any] | None] = ObjectId


class MongoBackend:
    def __init__(self, database: Any) -> None:
        self.database = database

    def collection(self, meta: AntDocMeta) -> Any:
        return self.database[meta.collection]

    def raw_collection(self, name: str) -> Any:
        return self.database[name]

    async def insert(
        self,
        meta: AntDocMeta,
        document: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        stored = dict(document)
        try:
            result = await self.collection(meta).insert_one(
                self._to_mongo_document(meta, stored),
                **self._options(backend_options),
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc

        if stored.get("id") is None and getattr(result, "inserted_id", None) is not None:
            stored["id"] = self._from_mongo_id(meta, result.inserted_id)
        return stored

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
        try:
            result = await self.collection(meta).replace_one(
                self._to_mongo_query(meta, filter),
                self._to_mongo_document(meta, replacement),
                **self._options(
                    backend_options,
                    upsert=upsert,
                    sort=self._to_mongo_sort(sort),
                ),
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc
        return self._update_result(meta, result)

    async def find_one(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        projection: Any = None,
        sort: Any = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        doc = await self.collection(meta).find_one(
            self._to_mongo_query(meta, filter),
            **self._options(
                backend_options,
                projection=self._to_mongo_projection(projection),
                sort=self._to_mongo_sort(sort),
            ),
        )
        return None if doc is None else self._from_mongo_document(meta, doc)

    async def find(
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
        cursor = self.collection(meta).find(
            self._to_mongo_query(meta, filter),
            **self._options(
                backend_options,
                projection=self._to_mongo_projection(projection),
                sort=self._to_mongo_sort(sort),
                limit=limit,
                skip=skip,
            ),
        )
        async for doc in cursor:
            yield self._from_mongo_document(meta, doc)

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
        try:
            doc = await self.collection(meta).find_one_and_update(
                self._to_mongo_query(meta, filter),
                self._to_mongo_update(meta, update),
                **self._options(
                    backend_options,
                    projection=self._to_mongo_projection(projection),
                    sort=self._to_mongo_sort(sort),
                    upsert=upsert,
                    return_document=ReturnDocument.AFTER,
                ),
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc
        return None if doc is None else self._from_mongo_document(meta, doc)

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
        try:
            result = await self.collection(meta).update_one(
                self._to_mongo_query(meta, filter),
                self._to_mongo_update(meta, update),
                **self._options(
                    backend_options,
                    upsert=upsert,
                    sort=self._to_mongo_sort(sort),
                ),
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc
        return self._update_result(meta, result)

    async def update_many(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
        backend_options: Mapping[str, Any] | None = None,
    ) -> UpdateResult:
        try:
            result = await self.collection(meta).update_many(
                self._to_mongo_query(meta, filter),
                self._to_mongo_update(meta, update),
                **self._options(backend_options, upsert=upsert),
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc
        return self._update_result(meta, result)

    async def delete_one(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> DeleteResult:
        result = await self.collection(meta).delete_one(
            self._to_mongo_query(meta, filter),
            **self._options(backend_options),
        )
        return DeleteResult(deleted_count=result.deleted_count)

    async def delete_many(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> DeleteResult:
        result = await self.collection(meta).delete_many(
            self._to_mongo_query(meta, filter),
            **self._options(backend_options),
        )
        return DeleteResult(deleted_count=result.deleted_count)

    async def count(
        self,
        meta: AntDocMeta,
        filter: Mapping[str, Any],
        *,
        skip: int | None = None,
        limit: int | None = None,
        backend_options: Mapping[str, Any] | None = None,
    ) -> int:
        return await self.collection(meta).count_documents(
            self._to_mongo_query(meta, filter),
            **self._options(backend_options, skip=skip, limit=limit),
        )

    async def distinct(
        self,
        meta: AntDocMeta,
        key: str,
        filter: Mapping[str, Any],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        mongo_key = self._to_mongo_field(key)
        values = await self.collection(meta).distinct(
            mongo_key,
            self._to_mongo_query(meta, filter),
            **self._options(backend_options),
        )
        if key == "id":
            return [self._from_mongo_id(meta, value) for value in values]
        return values

    async def aggregate(
        self,
        meta: AntDocMeta,
        pipeline: Sequence[Mapping[str, Any]],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]:
        cursor = self.collection(meta).aggregate(list(pipeline), **self._options(backend_options))
        return [self._from_mongo_document(meta, doc) async for doc in cursor]

    async def ensure_indexes(
        self,
        meta: AntDocMeta,
        indexes: Sequence[AntIndex],
        *,
        backend_options: Mapping[str, Any] | None = None,
    ) -> list[str]:
        models = [self._to_index_model(meta, index) for index in indexes]
        if not models:
            return []
        return await self.collection(meta).create_indexes(models, **self._options(backend_options))

    def _to_mongo_query(self, meta: AntDocMeta, query: Mapping[str, Any]) -> dict[str, Any]:
        validate_query(query)
        converted: dict[str, Any] = {}
        for key, value in query.items():
            if key in {"$and", "$or"}:
                converted[key] = [self._to_mongo_query(meta, item) for item in value]
                continue
            mongo_key = self._to_mongo_field(key)
            converted[mongo_key] = (
                self._to_mongo_id_filter(meta, value) if key == "id" else value
            )
        return converted

    def _to_mongo_update(self, meta: AntDocMeta, update: Mapping[str, Any]) -> dict[str, Any]:
        converted: dict[str, Any] = {}
        for operator, changes in update.items():
            converted[operator] = {
                self._to_mongo_field(field): self._to_mongo_value(meta, field, value)
                for field, value in changes.items()
            }
        return converted

    def _to_mongo_document(self, meta: AntDocMeta, document: Mapping[str, Any]) -> dict[str, Any]:
        doc = dict(document)
        doc_id = doc.pop("id", None)
        if doc_id is not None:
            doc["_id"] = self._to_mongo_id(meta, doc_id)
        return doc

    def _from_mongo_document(self, meta: AntDocMeta, document: Mapping[str, Any]) -> dict[str, Any]:
        doc = dict(document)
        if "_id" in doc:
            doc["id"] = self._from_mongo_id(meta, doc.pop("_id"))
        return doc

    def _to_mongo_id_filter(self, meta: AntDocMeta, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {operator: self._to_mongo_id_filter(meta, operand) for operator, operand in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [self._to_mongo_id_filter(meta, item) for item in value]
        return self._to_mongo_id(meta, value)

    def _to_mongo_value(self, meta: AntDocMeta, field: str, value: Any) -> Any:
        return self._to_mongo_id(meta, value) if field == "id" else value

    def _to_mongo_id(self, meta: AntDocMeta, value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if meta.id_type is UUID:
            return value
        if meta.id_type is ObjectId and isinstance(value, str) and ObjectId.is_valid(value):
            return ObjectId(value)
        return value

    def _from_mongo_id(self, meta: AntDocMeta, value: Any) -> Any:
        if meta.id_type is UUID and isinstance(value, str):
            return UUID(value)
        return value

    def _to_mongo_field(self, field: str) -> str:
        return "_id" if field == "id" else field

    def _to_mongo_projection(self, projection: Any) -> Any:
        if projection is None:
            return None
        if isinstance(projection, Mapping):
            return {self._to_mongo_field(field): value for field, value in projection.items()}
        if isinstance(projection, Sequence) and not isinstance(projection, (str, bytes)):
            return [self._to_mongo_field(field) for field in projection]
        return projection

    def _to_mongo_sort(self, sort: Any) -> Any:
        if sort is None:
            return None
        return [(self._to_mongo_field(field), direction) for field, direction in sort]

    def _to_index_model(self, meta: AntDocMeta, index: AntIndex) -> IndexModel:
        kwargs = dict(index.options)
        if index.name is not None:
            kwargs["name"] = index.name
        if index.unique:
            kwargs["unique"] = True
        if index.sparse:
            kwargs["sparse"] = True
        if index.expire_after_seconds is not None:
            kwargs["expireAfterSeconds"] = index.expire_after_seconds
        if index.partial_filter is not None:
            kwargs["partialFilterExpression"] = self._to_mongo_query(meta, index.partial_filter)
        return IndexModel([(self._to_mongo_field(field), direction) for field, direction in index.keys], **kwargs)

    def _update_result(self, meta: AntDocMeta, result: Any) -> UpdateResult:
        upserted_id = getattr(result, "upserted_id", None)
        return UpdateResult(
            matched_count=result.matched_count,
            modified_count=result.modified_count,
            upserted_id=None if upserted_id is None else self._from_mongo_id(meta, upserted_id),
        )

    def _options(self, base: Mapping[str, Any] | None = None, **options: Any) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in options.items():
            if value is not None:
                merged[key] = value
        return merged
