# ant

Small connector-centered persistence for Pydantic v2 AntDocs.

AntDocs describe data and local persistence metadata. `AntConnector` owns
document behavior, while a backend owns storage-specific translation:

```python
from typing import ClassVar, Sequence

from pymongo import AsyncMongoClient

from ant import ASCENDING, DESCENDING, AntConnector, AntDoc, AntIndex
from ant.backends.mongo import MongoBackend


class User(AntDoc):
    email: str
    name: str
    status: str = "active"

    ant_collection: ClassVar[str] = "users"
    ant_indexes: ClassVar[Sequence[AntIndex]] = (
        AntIndex([("email", ASCENDING)], unique=True, name="uniq_user_email"),
        AntIndex([("status", ASCENDING), ("created_at", DESCENDING)]),
    )


class Project(AntDoc):
    owner_id: str
    slug: str
    title: str

    # Collection defaults to "projects".
    ant_indexes: ClassVar[Sequence[AntIndex]] = (
        AntIndex([("owner_id", ASCENDING), ("slug", ASCENDING)], unique=True),
    )


async def main() -> None:
    client = AsyncMongoClient("mongodb://localhost:27017")
    db = AntConnector(MongoBackend(client["app"]))

    await db.ensure_indexes(User, Project)

    user = await db.save(User(email="a@b.com", name="Alice"))
    found = await db.get(User, user.id)
    active = await db.find(User, status="active", sort=[("created_at", -1)], limit=25)

    await db.patch(User, {"name": "Alice Cooper"}, id=user.id)
    await db.delete(user)

    raw_users = db.collection(User)
    await raw_users.find_one({"email": "a@b.com"})
```

`filter={...}` accepts Ant's Mongo-like query DSL. Extra keyword arguments are
equality filters, so use `filter={"limit": 10}` for document fields that collide
with connector options.

`AntDoc` uses UUID ids by default. MongoDB ObjectId users can opt in:

```python
from ant.backends.mongo import MongoObjectIdDoc


class LegacyUser(MongoObjectIdDoc):
    email: str
```

## License

Apache-2.0. See [LICENSE](LICENSE).
