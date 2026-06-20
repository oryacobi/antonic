from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError as PyMongoDuplicateKeyError


class FakeAsyncCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs
        self._index = 0

    def __aiter__(self) -> "FakeAsyncCursor":
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self.docs):
            raise StopAsyncIteration
        item = self.docs[self._index]
        self._index += 1
        return deepcopy(item)


class FakeAsyncDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeAsyncCollection] = {}

    def __getitem__(self, name: str) -> "FakeAsyncCollection":
        if name not in self.collections:
            self.collections[name] = FakeAsyncCollection(name)
        return self.collections[name]


class FakeAsyncCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.documents: dict[Any, dict[str, Any]] = {}
        self.created_indexes: list[Any] = []
        self.last_find_options: dict[str, Any] = {}

    async def insert_one(self, document: Mapping[str, Any], **options: Any) -> Any:
        doc = deepcopy(dict(document))
        doc.setdefault("_id", ObjectId())
        if doc["_id"] in self.documents:
            raise PyMongoDuplicateKeyError("duplicate key")
        self.documents[doc["_id"]] = doc
        return SimpleNamespace(inserted_id=doc["_id"])

    async def replace_one(self, filter: Mapping[str, Any], replacement: Mapping[str, Any], **options: Any) -> Any:
        matches = self._matching_documents(filter)
        if matches:
            old = matches[0]
            new_doc = deepcopy(dict(replacement))
            new_doc.setdefault("_id", old["_id"])
            self.documents[old["_id"]] = new_doc
            return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

        if options.get("upsert"):
            doc = deepcopy(dict(replacement))
            doc.setdefault("_id", filter.get("_id", ObjectId()))
            self.documents[doc["_id"]] = doc
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])

        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    async def find_one(self, filter: Mapping[str, Any] | None = None, **options: Any) -> dict[str, Any] | None:
        docs = self._apply_find_options(self._matching_documents(filter or {}), options)
        return deepcopy(docs[0]) if docs else None

    def find(self, filter: Mapping[str, Any] | None = None, **options: Any) -> FakeAsyncCursor:
        self.last_find_options = dict(options)
        return FakeAsyncCursor(self._apply_find_options(self._matching_documents(filter or {}), options))

    async def find_one_and_update(
        self,
        filter: Mapping[str, Any],
        update: Mapping[str, Any],
        **options: Any,
    ) -> dict[str, Any] | None:
        matches = self._apply_find_options(self._matching_documents(filter), options)
        if not matches and not options.get("upsert"):
            return None

        if matches:
            before = deepcopy(matches[0])
            doc_id = before["_id"]
        else:
            before = {"_id": filter.get("_id", ObjectId())}
            for key, value in filter.items():
                if not key.startswith("$") and not isinstance(value, Mapping):
                    before[key] = value
            doc_id = before["_id"]
            self.documents[doc_id] = before

        self._apply_update(self.documents[doc_id], update)
        after = deepcopy(self.documents[doc_id])
        if options.get("return_document") == ReturnDocument.AFTER:
            return after
        return before

    async def update_one(self, filter: Mapping[str, Any], update: Mapping[str, Any], **options: Any) -> Any:
        matches = self._matching_documents(filter)
        if not matches:
            if options.get("upsert"):
                doc = {"_id": filter.get("_id", ObjectId())}
                self.documents[doc["_id"]] = doc
                self._apply_update(doc, update)
                return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc["_id"])
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        self._apply_update(matches[0], update)
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

    async def update_many(self, filter: Mapping[str, Any], update: Mapping[str, Any], **options: Any) -> Any:
        matches = self._matching_documents(filter)
        for doc in matches:
            self._apply_update(doc, update)
        return SimpleNamespace(matched_count=len(matches), modified_count=len(matches), upserted_id=None)

    async def delete_one(self, filter: Mapping[str, Any], **options: Any) -> Any:
        matches = self._matching_documents(filter)
        if not matches:
            return SimpleNamespace(deleted_count=0)
        del self.documents[matches[0]["_id"]]
        return SimpleNamespace(deleted_count=1)

    async def delete_many(self, filter: Mapping[str, Any], **options: Any) -> Any:
        matches = self._matching_documents(filter)
        for doc in matches:
            del self.documents[doc["_id"]]
        return SimpleNamespace(deleted_count=len(matches))

    async def count_documents(self, filter: Mapping[str, Any], **options: Any) -> int:
        docs = self._apply_find_options(self._matching_documents(filter), options)
        return len(docs)

    async def distinct(self, key: str, filter: Mapping[str, Any] | None = None, **options: Any) -> list[Any]:
        values = []
        for doc in self._matching_documents(filter or {}):
            value = self._value_for(doc, key)
            if value not in values:
                values.append(value)
        return values

    def aggregate(self, pipeline: Sequence[Mapping[str, Any]], **options: Any) -> FakeAsyncCursor:
        docs = list(self.documents.values())
        for stage in pipeline:
            if "$match" in stage:
                docs = [doc for doc in docs if self._matches(doc, stage["$match"])]
        return FakeAsyncCursor([deepcopy(doc) for doc in docs])

    async def create_indexes(self, indexes: Sequence[Any], **options: Any) -> list[str]:
        self.created_indexes.extend(indexes)
        names = []
        for index in indexes:
            document = getattr(index, "document", {})
            names.append(document.get("name") or "_".join(document.get("key", {}).keys()))
        return names

    def _matching_documents(self, filter: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [doc for doc in self.documents.values() if self._matches(doc, filter)]

    def _matches(self, doc: Mapping[str, Any], filter: Mapping[str, Any]) -> bool:
        for key, expected in filter.items():
            actual = self._value_for(doc, key)
            if isinstance(expected, Mapping):
                for operator, operand in expected.items():
                    if operator == "$in" and actual not in operand:
                        return False
                    if operator == "$nin" and actual in operand:
                        return False
                    if operator == "$gte" and actual < operand:
                        return False
                    if operator == "$gt" and actual <= operand:
                        return False
                    if operator == "$lte" and actual > operand:
                        return False
                    if operator == "$lt" and actual >= operand:
                        return False
                    if operator == "$ne" and actual == operand:
                        return False
                    if operator == "$exists" and ((actual is not None) != bool(operand)):
                        return False
            elif actual != expected:
                return False
        return True

    def _value_for(self, doc: Mapping[str, Any], key: str) -> Any:
        value: Any = doc
        for part in key.split("."):
            if not isinstance(value, Mapping) or part not in value:
                return None
            value = value[part]
        return value

    def _apply_find_options(self, docs: list[dict[str, Any]], options: Mapping[str, Any]) -> list[dict[str, Any]]:
        items = [deepcopy(doc) for doc in docs]
        sort = options.get("sort")
        if sort:
            for key, direction in reversed(list(sort)):
                items.sort(key=lambda doc: self._value_for(doc, key), reverse=direction < 0)
        skip = options.get("skip") or 0
        limit = options.get("limit")
        if skip:
            items = items[skip:]
        if limit:
            items = items[:limit]
        return items

    def _apply_update(self, doc: dict[str, Any], update: Mapping[str, Any]) -> None:
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        for key, value in update.get("$inc", {}).items():
            doc[key] = doc.get(key, 0) + value
        for key in update.get("$unset", {}):
            doc.pop(key, None)
