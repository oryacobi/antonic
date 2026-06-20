from typing import Any, AsyncIterator, Mapping, Sequence, Type, TypeVar, overload

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError as PyMongoDuplicateKeyError

from ant_mongo.doc import AntDoc, utcnow
from ant_mongo.errors import AntDocNotFoundError, DuplicateAntDocError, OptimisticLockError
from ant_mongo.naming import CollectionNamingStrategy, default_collection_name
from ant_mongo.registry import AntDocMeta, AntDocRegistry

T = TypeVar("T", bound=AntDoc)


class AntConnector:
    def __init__(
        self,
        database: Any,
        naming_strategy: CollectionNamingStrategy = default_collection_name,
        *,
        strict_registration: bool = False,
    ) -> None:
        self.database = database
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

    def collection(self, doc_type: Type[T]) -> Any:
        return self.database[self.registry.resolve(doc_type).collection]

    def raw_collection(self, name: str) -> Any:
        return self.database[name]

    async def save(
        self,
        ant_doc: T,
        *,
        upsert: bool = False,
        session: Any = None,
        comment: Any = None,
        **where: Any,
    ) -> T:
        meta = self.registry.resolve(type(ant_doc))
        if ant_doc.id is None or (meta.optimistic_lock and ant_doc.version == 0):
            return await self.insert(ant_doc, session=session, comment=comment)
        return await self.update(ant_doc, upsert=upsert, session=session, comment=comment, **where)

    async def insert(
        self,
        ant_doc: T,
        *,
        bypass_document_validation: bool | None = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
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
        options = self._options(
            pymongo_options,
            bypass_document_validation=bypass_document_validation,
            session=session,
            comment=comment,
        )

        try:
            result = await self.collection(type(next_doc)).insert_one(
                self._to_document(next_doc),
                **options,
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc

        if next_doc.id is None and getattr(result, "inserted_id", None) is not None:
            next_doc = next_doc.model_copy(update={"id": result.inserted_id})
        return next_doc

    async def update(
        self,
        ant_doc: T,
        *,
        upsert: bool = False,
        sort: Any = None,
        hint: Any = None,
        bypass_document_validation: bool | None = None,
        collation: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
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

        options = self._options(
            pymongo_options,
            upsert=upsert,
            sort=sort,
            hint=hint,
            bypass_document_validation=bypass_document_validation,
            collation=collation,
            let=let,
            session=session,
            comment=comment,
        )

        try:
            result = await self.collection(type(ant_doc)).replace_one(
                query,
                self._to_document(next_doc),
                **options,
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc

        if result.matched_count == 0 and getattr(result, "upserted_id", None) is None:
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
        hint: Any = None,
        max_time_ms: int | None = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> T | None:
        query = self._query(doc_type, filter, where)
        if id is not None:
            meta = self.registry.resolve(doc_type)
            query["_id"] = self._coerce_id_value(id, meta)

        options = self._options(
            pymongo_options,
            projection=projection,
            sort=sort,
            hint=hint,
            max_time_ms=max_time_ms,
            session=session,
            comment=comment,
        )
        doc = await self.collection(doc_type).find_one(query, **options)
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
        batch_size: int | None = None,
        collation: Any = None,
        hint: Any = None,
        max_time_ms: int | None = None,
        session: Any = None,
        comment: Any = None,
        allow_disk_use: bool | None = None,
        pymongo_options: Mapping[str, Any] | None = None,
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
                batch_size=batch_size,
                collation=collation,
                hint=hint,
                max_time_ms=max_time_ms,
                session=session,
                comment=comment,
                allow_disk_use=allow_disk_use,
                pymongo_options=pymongo_options,
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
        batch_size: int | None = None,
        collation: Any = None,
        hint: Any = None,
        max_time_ms: int | None = None,
        session: Any = None,
        comment: Any = None,
        allow_disk_use: bool | None = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> AsyncIterator[T]:
        options = self._options(
            pymongo_options,
            projection=projection,
            sort=sort,
            limit=limit,
            skip=skip,
            batch_size=batch_size,
            collation=collation,
            hint=hint,
            max_time_ms=max_time_ms,
            session=session,
            comment=comment,
            allow_disk_use=allow_disk_use,
        )
        cursor = self.collection(doc_type).find(self._query(doc_type, filter, where), **options)
        async for doc in cursor:
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
        array_filters: Any = None,
        collation: Any = None,
        hint: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> T | None:
        if "id" in changes or "_id" in changes:
            raise ValueError("patch cannot change id/_id")

        meta = self.registry.resolve(doc_type)
        query = self._query(doc_type, filter, where)
        if id is not None:
            query["_id"] = self._coerce_id_value(id, meta)
        if expected_version is not None:
            query["version"] = expected_version

        set_values = dict(changes)
        if meta.timestamps:
            set_values["updated_at"] = utcnow()

        update_doc: dict[str, Any] = {}
        if set_values:
            update_doc["$set"] = set_values
        if meta.optimistic_lock:
            update_doc["$inc"] = {"version": 1}
        if not update_doc:
            raise ValueError("patch requires at least one change")

        options = self._options(
            pymongo_options,
            projection=projection,
            sort=sort,
            upsert=upsert,
            return_document=ReturnDocument.AFTER,
            array_filters=array_filters,
            collation=collation,
            hint=hint,
            let=let,
            session=session,
            comment=comment,
        )
        doc = await self.collection(doc_type).find_one_and_update(query, update_doc, **options)
        return None if doc is None else self._from_document(doc_type, doc)

    async def update_one(
        self,
        doc_type: Type[T],
        update: Mapping[str, Any],
        filter: Mapping[str, Any] | None = None,
        *,
        upsert: bool = False,
        array_filters: Any = None,
        bypass_document_validation: bool | None = None,
        collation: Any = None,
        hint: Any = None,
        sort: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> Any:
        options = self._options(
            pymongo_options,
            upsert=upsert,
            array_filters=array_filters,
            bypass_document_validation=bypass_document_validation,
            collation=collation,
            hint=hint,
            sort=sort,
            let=let,
            session=session,
            comment=comment,
        )
        try:
            return await self.collection(doc_type).update_one(
                self._query(doc_type, filter, where),
                dict(update),
                **options,
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc

    async def update_many(
        self,
        doc_type: Type[T],
        update: Mapping[str, Any],
        filter: Mapping[str, Any] | None = None,
        *,
        upsert: bool = False,
        array_filters: Any = None,
        bypass_document_validation: bool | None = None,
        collation: Any = None,
        hint: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> Any:
        options = self._options(
            pymongo_options,
            upsert=upsert,
            array_filters=array_filters,
            bypass_document_validation=bypass_document_validation,
            collation=collation,
            hint=hint,
            let=let,
            session=session,
            comment=comment,
        )
        try:
            return await self.collection(doc_type).update_many(
                self._query(doc_type, filter, where),
                dict(update),
                **options,
            )
        except PyMongoDuplicateKeyError as exc:
            raise DuplicateAntDocError(str(exc)) from exc

    async def delete(
        self,
        ant_doc: AntDoc,
        *,
        hint: Any = None,
        collation: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> bool:
        if ant_doc.id is None:
            return False
        result = await self.delete_one(
            type(ant_doc),
            {"id": ant_doc.id},
            hint=hint,
            collation=collation,
            let=let,
            session=session,
            comment=comment,
            pymongo_options=pymongo_options,
            **where,
        )
        return result.deleted_count == 1

    async def delete_one(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        collation: Any = None,
        hint: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> Any:
        options = self._options(
            pymongo_options,
            collation=collation,
            hint=hint,
            let=let,
            session=session,
            comment=comment,
        )
        return await self.collection(doc_type).delete_one(
            self._query(doc_type, filter, where),
            **options,
        )

    async def delete_many(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        collation: Any = None,
        hint: Any = None,
        let: Any = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> Any:
        options = self._options(
            pymongo_options,
            collation=collation,
            hint=hint,
            let=let,
            session=session,
            comment=comment,
        )
        return await self.collection(doc_type).delete_many(
            self._query(doc_type, filter, where),
            **options,
        )

    async def count(
        self,
        doc_type: Type[T],
        filter: Mapping[str, Any] | None = None,
        *,
        skip: int | None = None,
        limit: int | None = None,
        hint: Any = None,
        collation: Any = None,
        max_time_ms: int | None = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> int:
        options = self._options(
            pymongo_options,
            skip=skip,
            limit=limit,
            hint=hint,
            collation=collation,
            maxTimeMS=max_time_ms,
            session=session,
            comment=comment,
        )
        return await self.collection(doc_type).count_documents(
            self._query(doc_type, filter, where),
            **options,
        )

    async def distinct(
        self,
        doc_type: Type[T],
        key: str,
        filter: Mapping[str, Any] | None = None,
        *,
        max_time_ms: int | None = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **where: Any,
    ) -> list[Any]:
        options = self._options(
            pymongo_options,
            maxTimeMS=max_time_ms,
            session=session,
            comment=comment,
        )
        return await self.collection(doc_type).distinct(
            key,
            self._query(doc_type, filter, where),
            **options,
        )

    async def aggregate(
        self,
        doc_type: Type[T],
        pipeline: Sequence[Mapping[str, Any]],
        *,
        as_type: Type[T] | None = None,
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> list[Any]:
        aggregate_options = self._options(
            pymongo_options,
            session=session,
            comment=comment,
            **options,
        )
        cursor = self.collection(doc_type).aggregate(list(pipeline), **aggregate_options)
        if as_type is None:
            return [doc async for doc in cursor]
        return [self._from_document(as_type, doc) async for doc in cursor]

    async def ensure_indexes(
        self,
        *doc_types: Type[AntDoc],
        session: Any = None,
        comment: Any = None,
        pymongo_options: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> dict[Type[AntDoc], list[str]]:
        targets = doc_types or tuple(self.registry.registered_types())
        create_options = self._options(
            pymongo_options,
            session=session,
            comment=comment,
            **options,
        )
        created: dict[Type[AntDoc], list[str]] = {}
        for doc_type in targets:
            meta = self.registry.resolve(doc_type)
            models = [index.to_index_model() for index in meta.indexes]
            created[doc_type] = (
                await self.collection(doc_type).create_indexes(models, **create_options)
                if models
                else []
            )
        return created

    def _query(
        self,
        doc_type: Type[AntDoc],
        filter: Mapping[str, Any] | None,
        where: Mapping[str, Any],
    ) -> dict[str, Any]:
        meta = self.registry.resolve(doc_type)
        query = dict(filter or {})
        query.update(where)
        if "id" in query:
            query["_id"] = self._coerce_id_value(query.pop("id"), meta)
        elif "_id" in query:
            query["_id"] = self._coerce_id_value(query["_id"], meta)
        return query

    def _coerce_id_value(self, value: Any, meta: AntDocMeta) -> Any:
        if meta.id_type is not ObjectId:
            return value
        if isinstance(value, str) and ObjectId.is_valid(value):
            return ObjectId(value)
        if isinstance(value, Mapping):
            coerced = {}
            for key, item in value.items():
                if key in {"$in", "$nin", "$all"} and isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                    coerced[key] = [self._coerce_id_value(member, meta) for member in item]
                else:
                    coerced[key] = self._coerce_id_value(item, meta)
            return coerced
        return value

    def _to_document(self, ant_doc: AntDoc) -> dict[str, Any]:
        doc = ant_doc.model_dump(mode="python", by_alias=False)
        doc_id = doc.pop("id", None)
        if doc_id is not None:
            doc["_id"] = doc_id
        return doc

    def _from_document(self, doc_type: Type[T], doc: Mapping[str, Any]) -> T:
        data = dict(doc)
        data["id"] = data.pop("_id", None)
        return doc_type.model_validate(data)

    def _options(self, base: Mapping[str, Any] | None = None, **options: Any) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in options.items():
            if value is not None:
                merged[key] = value
        return merged
