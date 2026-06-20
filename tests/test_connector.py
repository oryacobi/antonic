from typing import Any, Callable, ClassVar, Sequence

import pytest
from bson import ObjectId
from pydantic import ConfigDict
from pymongo import ASCENDING, DESCENDING

import ant_mongo
from ant_mongo import (
    AntConnector,
    AntDoc,
    AntIndex,
    OptimisticLockError,
    default_collection_name,
)
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
    owner_id: ObjectId
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


class FlexibleDoc(AntDoc):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_by_name=True,
        validate_by_alias=True,
        extra="allow",
    )

    name: str


def test_default_collection_names_are_pluralized() -> None:
    assert default_collection_name(User) == "users"
    assert default_collection_name(ProjectInvite) == "project_invites"
    assert default_collection_name(Company) == "companies"
    assert default_collection_name(Box) == "boxes"


def test_old_public_names_are_not_exported() -> None:
    assert not hasattr(ant_mongo, "AsyncMongoConnector")
    assert not hasattr(ant_mongo, "Entity")
    assert not hasattr(ant_mongo, "IndexSpec")
    assert not hasattr(ant_mongo, "EntityMeta")
    assert not hasattr(ant_mongo, "EntityRegistry")


def test_registry_resolves_lazy_metadata() -> None:
    db = AntConnector(FakeAsyncDatabase())

    user_meta = db.register(User)
    project_meta = db.registry.resolve(Project)

    assert user_meta.collection == "users"
    assert project_meta.collection == "projects"
    assert db.collection(Project).name == "projects"


@pytest.mark.asyncio
async def test_save_get_find_count_delete_round_trip() -> None:
    db = AntConnector(FakeAsyncDatabase())

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

    active = await db.find(User, status="active", sort=[("created_at", -1)], limit=25)
    assert [item.email for item in active] == ["a@b.com"]
    assert db.collection(User).last_find_options["limit"] == 25

    assert await db.count(User, status="active", limit=1000) == 1
    assert await db.delete(user) is True
    assert await db.get(User, user.id) is None


@pytest.mark.asyncio
async def test_raw_filter_and_where_kwargs_merge() -> None:
    db = AntConnector(FakeAsyncDatabase())
    await db.save(User(email="a@b.com", name="Alice"))
    await db.save(User(email="c@d.com", name="Cora", status="pending"))

    users = await db.find(
        User,
        {"status": {"$in": ["active", "pending"]}},
        email="c@d.com",
    )

    assert len(users) == 1
    assert users[0].name == "Cora"


@pytest.mark.asyncio
async def test_update_uses_optimistic_version() -> None:
    db = AntConnector(FakeAsyncDatabase())
    user = await db.save(User(email="a@b.com", name="Alice"))

    updated = await db.save(user.model_copy(update={"name": "Alice Cooper"}))

    assert updated.version == 2
    assert updated.name == "Alice Cooper"
    with pytest.raises(OptimisticLockError):
        await db.save(user.model_copy(update={"name": "Stale Alice"}))


@pytest.mark.asyncio
async def test_patch_updates_fields_and_increments_version() -> None:
    db = AntConnector(FakeAsyncDatabase())
    user = await db.save(User(email="a@b.com", name="Alice"))

    patched = await db.patch(User, {"name": "Alice Cooper"}, id=user.id, expected_version=1)

    assert patched is not None
    assert patched.name == "Alice Cooper"
    assert patched.version == 2
    assert await db.patch(User, {"name": "Too Late"}, id=user.id, expected_version=1) is None


@pytest.mark.asyncio
async def test_update_one_delete_many_distinct_and_aggregate() -> None:
    db = AntConnector(FakeAsyncDatabase())
    await db.save(User(email="a@b.com", name="Alice"))
    await db.save(User(email="c@d.com", name="Cora"))

    result = await db.update_one(User, {"$set": {"status": "disabled"}}, email="a@b.com")
    assert result.matched_count == 1
    assert await db.distinct(User, "status") == ["disabled", "active"]

    rows = await db.aggregate(User, [{"$match": {"status": "disabled"}}])
    assert rows[0]["email"] == "a@b.com"

    deleted = await db.delete_many(User, status="active")
    assert deleted.deleted_count == 1
    assert await db.count(User) == 1


@pytest.mark.asyncio
async def test_custom_string_id_is_not_coerced_to_object_id() -> None:
    db = AntConnector(FakeAsyncDatabase())
    hex_looking_id = "0123456789abcdef01234567"

    saved = await db.save(ApiKey(id=hex_looking_id, token="secret"))
    found = await db.get(ApiKey, hex_looking_id)

    assert saved.id == hex_looking_id
    assert found is not None
    assert found.id == hex_looking_id
    assert isinstance(db.collection(ApiKey).documents[hex_looking_id]["_id"], str)


@pytest.mark.asyncio
async def test_ensure_indexes_uses_ant_metadata() -> None:
    db = AntConnector(FakeAsyncDatabase())

    created = await db.ensure_indexes(User, Project)

    assert created[User] == ["uniq_user_email", "status_created"]
    assert created[Project] == ["owner_id_1_slug_1"]


@pytest.mark.asyncio
async def test_extra_allow_preserves_unknown_fields_on_read() -> None:
    db = AntConnector(FakeAsyncDatabase())
    collection = db.collection(FlexibleDoc)
    raw_id = ObjectId()
    await collection.insert_one({"_id": raw_id, "name": "Loose", "unknown": 42})

    found = await db.get(FlexibleDoc, raw_id)

    assert found is not None
    assert found.model_extra == {"unknown": 42}
