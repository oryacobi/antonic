from dataclasses import dataclass
from typing import Any, Callable, Sequence, Type

from ant.doc import AntDoc
from ant.errors import AntDocNotRegisteredError, InvalidAntDocMetadataError
from ant.index import AntIndex
from ant.naming import CollectionNamingStrategy, default_collection_name


@dataclass(frozen=True)
class AntDocMeta:
    doc_type: Type[AntDoc]
    collection: str
    indexes: Sequence[AntIndex]
    timestamps: bool
    optimistic_lock: bool
    id_factory: Callable[[], Any] | None
    id_type: Type[Any] | None


class AntDocRegistry:
    def __init__(
        self,
        naming_strategy: CollectionNamingStrategy = default_collection_name,
        *,
        strict: bool = False,
    ) -> None:
        self.naming_strategy = naming_strategy
        self.strict = strict
        self._items: dict[Type[AntDoc], AntDocMeta] = {}

    def register(self, doc_type: Type[AntDoc]) -> AntDocMeta:
        meta = self._build_meta(doc_type)
        self._items[doc_type] = meta
        return meta

    def resolve(self, doc_type: Type[AntDoc]) -> AntDocMeta:
        if doc_type in self._items:
            return self._items[doc_type]
        if self.strict:
            raise AntDocNotRegisteredError(f"{doc_type.__name__} is not registered")
        return self.register(doc_type)

    def registered_types(self) -> Sequence[Type[AntDoc]]:
        return tuple(self._items)

    def _build_meta(self, doc_type: Type[AntDoc]) -> AntDocMeta:
        if not isinstance(doc_type, type) or not issubclass(doc_type, AntDoc):
            raise InvalidAntDocMetadataError("Expected an AntDoc subclass")

        collection = doc_type.ant_collection or self.naming_strategy(doc_type)
        if not isinstance(collection, str) or not collection.strip():
            raise InvalidAntDocMetadataError(
                f"{doc_type.__name__}.ant_collection must resolve to a non-empty string"
            )

        indexes = tuple(doc_type.ant_indexes)
        for index in indexes:
            if not isinstance(index, AntIndex):
                raise InvalidAntDocMetadataError(
                    f"{doc_type.__name__}.ant_indexes must contain AntIndex values"
                )

        id_factory = doc_type.ant_id_factory
        if id_factory is not None and not callable(id_factory):
            raise InvalidAntDocMetadataError(
                f"{doc_type.__name__}.ant_id_factory must be callable or None"
            )

        id_type = doc_type.ant_id_type
        if id_type is not None and not isinstance(id_type, type):
            raise InvalidAntDocMetadataError(
                f"{doc_type.__name__}.ant_id_type must be a type or None"
            )

        return AntDocMeta(
            doc_type=doc_type,
            collection=collection,
            indexes=indexes,
            timestamps=bool(doc_type.ant_timestamps),
            optimistic_lock=bool(doc_type.ant_optimistic_lock),
            id_factory=id_factory,
            id_type=id_type,
        )
