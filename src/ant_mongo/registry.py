from dataclasses import dataclass
from typing import Any, Callable, Sequence, Type

from ant_mongo.entity import Entity
from ant_mongo.errors import EntityNotRegisteredError, InvalidEntityMetadataError
from ant_mongo.indexes import IndexSpec
from ant_mongo.naming import CollectionNamingStrategy, default_collection_name


@dataclass(frozen=True)
class EntityMeta:
    entity_type: Type[Entity]
    collection: str
    indexes: Sequence[IndexSpec]
    timestamps: bool
    optimistic_lock: bool
    id_factory: Callable[[], Any] | None
    id_type: Type[Any] | None


class EntityRegistry:
    def __init__(
        self,
        naming_strategy: CollectionNamingStrategy = default_collection_name,
        *,
        strict: bool = False,
    ) -> None:
        self.naming_strategy = naming_strategy
        self.strict = strict
        self._items: dict[Type[Entity], EntityMeta] = {}

    def register(self, entity_type: Type[Entity]) -> EntityMeta:
        meta = self._build_meta(entity_type)
        self._items[entity_type] = meta
        return meta

    def resolve(self, entity_type: Type[Entity]) -> EntityMeta:
        if entity_type in self._items:
            return self._items[entity_type]
        if self.strict:
            raise EntityNotRegisteredError(f"{entity_type.__name__} is not registered")
        return self.register(entity_type)

    def registered_types(self) -> Sequence[Type[Entity]]:
        return tuple(self._items)

    def _build_meta(self, entity_type: Type[Entity]) -> EntityMeta:
        if not isinstance(entity_type, type) or not issubclass(entity_type, Entity):
            raise InvalidEntityMetadataError("Expected an Entity subclass")

        collection = entity_type.mongo_collection or self.naming_strategy(entity_type)
        if not isinstance(collection, str) or not collection.strip():
            raise InvalidEntityMetadataError(
                f"{entity_type.__name__}.mongo_collection must resolve to a non-empty string"
            )

        indexes = tuple(entity_type.mongo_indexes)
        for index in indexes:
            if not isinstance(index, IndexSpec):
                raise InvalidEntityMetadataError(
                    f"{entity_type.__name__}.mongo_indexes must contain IndexSpec values"
                )

        id_factory = entity_type.mongo_id_factory
        if id_factory is not None and not callable(id_factory):
            raise InvalidEntityMetadataError(
                f"{entity_type.__name__}.mongo_id_factory must be callable or None"
            )

        id_type = entity_type.mongo_id_type
        if id_type is not None and not isinstance(id_type, type):
            raise InvalidEntityMetadataError(
                f"{entity_type.__name__}.mongo_id_type must be a type or None"
            )

        return EntityMeta(
            entity_type=entity_type,
            collection=collection,
            indexes=indexes,
            timestamps=bool(entity_type.mongo_timestamps),
            optimistic_lock=bool(entity_type.mongo_optimistic_lock),
            id_factory=id_factory,
            id_type=id_type,
        )
