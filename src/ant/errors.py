class PersistenceError(Exception):
    """Base class for Ant persistence errors."""


class InvalidAntDocMetadataError(PersistenceError):
    """Raised when an AntDoc class has invalid metadata."""


class AntDocNotRegisteredError(PersistenceError):
    """Raised by strict registries when an AntDoc type was not registered."""


class DuplicateAntDocError(PersistenceError):
    """Raised when a backend rejects a write because of a duplicate key."""


class AntDocNotFoundError(PersistenceError):
    """Raised when an update/delete requires a document that does not exist."""


class OptimisticLockError(PersistenceError):
    """Raised when optimistic version checks fail."""


class InvalidAntQueryError(PersistenceError):
    """Raised when an Ant filter/update uses unsupported syntax."""


class UnsupportedAntCapabilityError(PersistenceError):
    """Raised when a backend does not support an optional Ant capability."""
