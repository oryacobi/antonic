# ant-mongo

Small connector-centered MongoDB persistence for passive Pydantic v2 entities.

Models describe data and local Mongo metadata. `AsyncMongoConnector` owns all
database behavior:

```python
from typing import ClassVar, Sequence

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient

from ant_mongo import AsyncMongoConnector, Entity, IndexSpec


class User(Entity):
    email: str
    name: str
    status: str = "active"

    mongo_collection: ClassVar[str] = "users"
    mongo_indexes: ClassVar[Sequence[IndexSpec]] = (
        IndexSpec([("email", ASCENDING)], unique=True, name="uniq_user_email"),
        IndexSpec([("status", ASCENDING), ("created_at", DESCENDING)]),
    )


class Project(Entity):
    owner_id: ObjectId
    slug: str
    title: str

    # Collection defaults to "projects".
    mongo_indexes: ClassVar[Sequence[IndexSpec]] = (
        IndexSpec([("owner_id", ASCENDING), ("slug", ASCENDING)], unique=True),
    )


async def main() -> None:
    client = AsyncMongoClient("mongodb://localhost:27017")
    db = AsyncMongoConnector(client["app"])

    await db.ensure_indexes(User, Project)

    user = await db.save(User(email="a@b.com", name="Alice"))
    found = await db.get(User, user.id)
    active = await db.find(User, status="active", sort=[("created_at", -1)], limit=25)

    await db.patch(User, {"name": "Alice Cooper"}, id=user.id)
    await db.delete(user)

    raw_users = db.collection(User)
    await raw_users.find_one({"email": "a@b.com"}, max_time_ms=100)
```

`filter={...}` accepts raw Mongo filters. Extra keyword arguments are equality
filters, so use `filter={"limit": 10}` for document fields that collide with
connector options.
