import importlib
from pathlib import Path
from typing import Any, Callable, ClassVar, Sequence
from uuid import UUID, uuid4

import pytest
from bson import ObjectId
from pydantic import ConfigDict

import antonic
from antonic import (
    ASCENDING,
    DESCENDING,
    AntConnector,
    AntDoc,
    AntIndex,
    DeleteResult,
    InvalidAntQueryError,
    OptimisticLockError,
    UnsupportedAntCapabilityError,
    UpdateResult,
    default_collection_name,
)
from antonic.backends.mongo import MongoBackend
from tests.fakes import FakeAsyncDatabase


class User(AntDoc):
    email: str
    name: str
    status: str = "active"

    ant_collection: ClassVar[str] = "users"
    ant_indexes: ClassVar[Sequence[AntIndex]] = (
        AntIndex([("email", ASCENDING)], unique=True, name="uniq_user_email"),
        AntIndex([("status", ASCENDING), ("created_at", DESCENDING)], name="status_created"),
    )


class Project(AntDoc):
    owner_id: UUID
    slug: str
    title: str
    archived: bool = False

    ant_indexes: ClassVar[Sequence[AntIndex]] = (
        AntIndex([("owner_id", ASCENDING), ("slug", ASCENDING)], unique=True),
    )


class ProjectInvite(AntDoc):
    email: str


class Company(AntDoc):
    name: str


class Box(AntDoc):
    label: str


class ApiKey(AntDoc):
    id: str | None = None
    token: str

    ant_id_type: ClassVar[type[str]] = str
    ant_id_factory: ClassVar[Callable[[], Any] | None] = None


class UuidUser(AntDoc):
    email: str

    ant_collection: ClassVar[str] = "uuid_users"
    ant_id_factory: ClassVar[Callable[[], Any] | None] = uuid4
    ant_id_type: ClassVar[type[UUID]] = UUID


class ObjectIdUser(AntDoc):
    email: str

    ant_collection: ClassVar[str] = "object_id_users"


class FlexibleDoc(AntDoc):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_by_name=True,
        validate_by_alias=True,
        extra="allow",
    )

    name: str


def mongo_db() -> AntConnector:
    return AntConnector(MongoBackend(FakeAsyncDatabase()))


def test_default_collection_names_are_pluralized() -> None:
    assert default_collection_name(User) == "users"
    assert default_collection_name(ProjectInvite) == "project_invites"
    assert default_collection_name(Company) == "companies"
    assert default_collection_name(Box) == "boxes"


def test_old_package_and_public_names_are_not_available() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ant")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ant_mongo")

    assert not hasattr(antonic, "AsyncMongoConnector")
    assert not hasattr(antonic, "Entity")
    assert not hasattr(antonic, "IndexSpec")
    assert not hasattr(antonic, "EntityMeta")
    assert not hasattr(antonic, "EntityRegistry")


def test_core_source_does_not_import_mongo_packages() -> None:
    core_root = Path(__file__).parents[1] / "src" / "antonic"
    for path in core_root.glob("*.py"):
        text = path.read_text()
        assert "from pymongo" not in text
        assert "import pymongo" not in text
        assert "from bson" not in text
        assert "import bson" not in text


def test_registry_resolves_lazy_metadata() -> None:
    db = mongo_db()

    user_meta = db.register(User)
    project_meta = db.registry.resolve(Project)

    assert user_meta.collection == "users"
    assert project_meta.collection == "projects"
    assert db.collection(Project).name == "projects"


@pytest.mark.asyncio
async def test_save_get_find_count_delete_round_trip() -> None:
    db = mongo_db()

    user = await db.save(User(email="a@b.com", name="Alice"))
    await db.save(User(email="c@d.com", name="Cora", status="inactive"))

    raw_doc = db.collection(User).documents[user.id]
    assert "id" not in raw_doc
    assert raw_doc["_id"] == user.id
    assert isinstance(user.id, ObjectId)
    assert user.version == 1
    assert user.created_at is not None
    assert user.updated_at is not None

    found = await db.get(User, str(user.id))
    assert found == user

    active = await db.find(User, status="active", sort=[("created_at", DESCENDING)], limit=25)
    assert [item.email for item in active] == ["a@b.com"]
    assert db.collection(User).last_find_options["limit"] == 25

    assert await db.count(User, status="active", limit=1000) == 1
    assert await db.delete(user) is True
    assert await db.get(User, user.id) is None


@pytest.mark.asyncio
async def test_raw_filter_and_where_kwargs_merge() -> None:
    db = mongo_db()
    await db.save(User(email="a@b.com", name="Alice"))
    await db.save(User(email="c@d.com", name="Cora", status="pending"))

    users = await db.find(
        User,
        {"$and": [{"status": {"$in": ["active", "pending"]}}, {"name": {"$ne": "Alice"}}]},
        email="c@d.com",
    )

    assert len(users) == 1
    assert users[0].name == "Cora"


@pytest.mark.asyncio
async def test_update_uses_optimistic_version() -> None:
    db = mongo_db()
    user = await db.save(User(email="a@b.com", name="Alice"))

    updated = await db.save(user.model_copy(update={"name": "Alice Cooper"}))

    assert updated.version == 2
    assert updated.name == "Alice Cooper"
    with pytest.raises(OptimisticLockError):
        await db.save(user.model_copy(update={"name": "Stale Alice"}))


@pytest.mark.asyncio
async def test_patch_updates_fields_and_increments_version() -> None:
    db = mongo_db()
    user = await db.save(User(email="a@b.com", name="Alice"))

    patched = await db.patch(User, {"name": "Alice Cooper"}, id=user.id, expected_version=1)

    assert patched is not None
    assert patched.name == "Alice Cooper"
    assert patched.version == 2
    assert await db.patch(User, {"name": "Too Late"}, id=user.id, expected_version=1) is None


@pytest.mark.asyncio
async def test_update_one_delete_many_distinct_and_aggregate() -> None:
    db = mongo_db()
    first = await db.save(User(email="a@b.com", name="Alice"))
    await db.save(User(email="c@d.com", name="Cora"))

    result = await db.update_one(User, {"$set": {"status": "disabled"}}, email="a@b.com")
    assert isinstance(result, UpdateResult)
    assert result.matched_count == 1
    assert await db.distinct(User, "status") == ["disabled", "active"]
    assert await db.distinct(User, "id", email="a@b.com") == [first.id]

    rows = await db.aggregate(User, [{"$match": {"status": "disabled"}}])
    assert rows[0]["email"] == "a@b.com"
    assert rows[0]["id"] == first.id

    deleted = await db.delete_many(User, status="active")
    assert isinstance(deleted, DeleteResult)
    assert deleted.deleted_count == 1
    assert await db.count(User) == 1


@pytest.mark.asyncio
async def test_upsert_result_ids_are_ant_ids() -> None:
    db = mongo_db()
    new_id = ObjectId()

    result = await db.update_one(
        User,
        {"$set": {"email": "new@b.com", "name": "New"}},
        id=str(new_id),
        upsert=True,
    )
    found = await db.get(User, str(new_id))

    assert result.upserted_id == new_id
    assert found is not None
    assert found.id == new_id


@pytest.mark.asyncio
async def test_explicit_uuid_ids_round_trip() -> None:
    db = mongo_db()

    saved = await db.save(UuidUser(email="a@b.com"))
    found = await db.get(UuidUser, str(saved.id))

    assert isinstance(saved.id, UUID)
    assert db.collection(UuidUser).documents[str(saved.id)]["_id"] == str(saved.id)
    assert found == saved

    new_id = uuid4()
    result = await db.update_one(
        UuidUser,
        {"$set": {"email": "new@b.com"}},
        id=new_id,
        upsert=True,
    )
    upserted = await db.get(UuidUser, str(new_id))

    assert result.upserted_id == new_id
    assert upserted is not None
    assert upserted.id == new_id


@pytest.mark.asyncio
async def test_custom_string_id_is_not_coerced_to_object_id() -> None:
    db = mongo_db()
    hex_looking_id = "0123456789abcdef01234567"

    saved = await db.save(ApiKey(id=hex_looking_id, token="secret"))
    found = await db.get(ApiKey, hex_looking_id)

    assert saved.id == hex_looking_id
    assert found is not None
    assert found.id == hex_looking_id
    assert isinstance(db.collection(ApiKey).documents[hex_looking_id]["_id"], str)


@pytest.mark.asyncio
async def test_plain_ant_doc_uses_object_ids_with_mongo_backend() -> None:
    db = mongo_db()

    saved = await db.save(ObjectIdUser(email="a@b.com"))
    found = await db.get(ObjectIdUser, str(saved.id))

    assert isinstance(saved.id, ObjectId)
    assert db.collection(ObjectIdUser).documents[saved.id]["_id"] == saved.id
    assert found == saved

    explicit_id = ObjectId()
    explicit = await db.save(ObjectIdUser(id=str(explicit_id), email="c@d.com"))

    assert explicit.id == explicit_id
    assert db.collection(ObjectIdUser).documents[explicit_id]["_id"] == explicit_id


@pytest.mark.asyncio
async def test_ensure_indexes_uses_ant_metadata() -> None:
    db = mongo_db()

    created = await db.ensure_indexes(User, Project)

    assert created[User] == ["uniq_user_email", "status_created"]
    assert created[Project] == ["owner_id_1_slug_1"]


@pytest.mark.asyncio
async def test_extra_allow_preserves_unknown_fields_on_read() -> None:
    db = mongo_db()
    collection = db.collection(FlexibleDoc)
    raw_id = ObjectId()
    await collection.insert_one({"_id": raw_id, "name": "Loose", "unknown": 42})

    found = await db.get(FlexibleDoc, str(raw_id))

    assert found is not None
    assert found.id == raw_id
    assert found.model_extra == {"unknown": 42}


@pytest.mark.asyncio
async def test_query_validation_rejects_private_id_and_unsupported_operators() -> None:
    db = mongo_db()

    with pytest.raises(InvalidAntQueryError):
        await db.find(User, {"_id": "not-public"})
    with pytest.raises(InvalidAntQueryError):
        await db.find(User, {"email": {"$regex": "@b.com"}})
    with pytest.raises(InvalidAntQueryError):
        await db.find(User, {"$and": "not-a-list"})

    assert await db.find(User, {"id": {"$exists": True}}) == []


@pytest.mark.asyncio
async def test_update_validation_rejects_private_id_and_unsupported_operators() -> None:
    db = mongo_db()

    with pytest.raises(InvalidAntQueryError):
        await db.update_one(User, {"$rename": {"name": "full_name"}})
    with pytest.raises(InvalidAntQueryError):
        await db.update_one(User, {"$set": {"_id": "not-public"}})
    with pytest.raises(InvalidAntQueryError):
        await db.update_one(User, {"$set": {"id": "immutable"}})


@pytest.mark.asyncio
async def test_aggregate_is_optional_backend_capability() -> None:
    class NoAggregateBackend:
        def collection(self, meta: Any) -> Any:
            raise AssertionError("collection should not be called")

        def raw_collection(self, name: str) -> Any:
            raise AssertionError("raw_collection should not be called")

    db = AntConnector(NoAggregateBackend())

    with pytest.raises(UnsupportedAntCapabilityError):
        await db.aggregate(User, [])
