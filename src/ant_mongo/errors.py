class PersistenceError(Exception):
    """Base class for connector persistence errors."""


class InvalidEntityMetadataError(PersistenceError):
    """Raised when an entity class has invalid Mongo metadata."""


class EntityNotRegisteredError(PersistenceError):
    """Raised by strict registries when an entity type was not registered."""


class DuplicateEntityError(PersistenceError):
    """Raised when MongoDB rejects a write because of a duplicate key."""


class EntityNotFoundError(PersistenceError):
    """Raised when an update/delete requires a document that does not exist."""


class OptimisticLockError(PersistenceError):
    """Raised when optimistic version checks fail."""
