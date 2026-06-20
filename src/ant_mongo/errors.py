class PersistenceError(Exception):
    """Base class for connector persistence errors."""


class InvalidAntDocMetadataError(PersistenceError):
    """Raised when an AntDoc class has invalid metadata."""


class AntDocNotRegisteredError(PersistenceError):
    """Raised by strict registries when an AntDoc type was not registered."""


class DuplicateAntDocError(PersistenceError):
    """Raised when MongoDB rejects a write because of a duplicate key."""


class AntDocNotFoundError(PersistenceError):
    """Raised when an update/delete requires a document that does not exist."""


class OptimisticLockError(PersistenceError):
    """Raised when optimistic version checks fail."""
