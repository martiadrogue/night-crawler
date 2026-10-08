"""Export the Mongo `users` collection as a Keycloak partial import.

A one-off, for accounts created before Keycloak owned them. Each account
keeps its `id`, so every `user_id` already stored (Crawlers, versions,
Instruction Generations) still names its owner once imported. Bcrypt
hashes are not carried over (Keycloak can't verify them without an
extension). Instead each account gets a random temporary password:
without one it couldn't log in at all, since `UPDATE_PASSWORD` only
runs after a login and the realm has no password reset by email. At
their first login, users replace it.

Run it in the `web` container, before dropping the collection:

    docker compose exec web python \
        backend/scripts/export_users_to_keycloak.py

It writes `var/keycloak/users-import.json` (or the path given as the
only argument) and, beside it, `temporary-passwords.csv` (email,
password) to hand to each user. Both are readable only by their owner,
and the passwords are never logged. Import the JSON in the admin console
as described in README.md, *Moving accounts to Keycloak*, then delete
both files.
"""

import asyncio
import csv
import io
import json
import logging
import secrets
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from night_crawler.core.config import get_settings
from pymongo import AsyncMongoClient

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2] / "var" / "keycloak" / "users-import.json"
)
PASSWORDS_FILENAME = "temporary-passwords.csv"
ROLES = ("admin", "user", "viewer")


def to_keycloak_user(db_user: dict, temporary_password: str) -> dict:
    """Return a Keycloak user representation for one stored account.

    The account holds only its own role, as `/api/users` sets roles,
    and a temporary password. An unknown role falls back to `user`, the
    default.
    """
    role = db_user.get("role") if db_user.get("role") in ROLES else "user"
    representation = {
        "id": db_user["_id"],
        "username": db_user["email"],
        "email": db_user["email"],
        "emailVerified": True,
        "enabled": True,
        "realmRoles": [role],
        "credentials": [
            {"type": "password", "value": temporary_password, "temporary": True}
        ],
        "requiredActions": ["UPDATE_PASSWORD"],
    }
    if isinstance(db_user.get("created_at"), datetime):
        representation["createdTimestamp"] = _to_epoch_ms(db_user["created_at"])
    return representation


def create_temporary_password() -> str:
    """Return a random password that meets the API's password rules.

    The fixed tail guarantees an uppercase letter, a lowercase letter,
    and a digit whatever the random part holds.
    """
    return f"{secrets.token_urlsafe(12)}Aa1"


def _to_epoch_ms(created_at: datetime) -> int:
    """Return a naive-UTC datetime as Keycloak's epoch milliseconds."""
    return int(created_at.replace(tzinfo=UTC).timestamp() * 1000)


async def export_users(output: Path) -> Counter:
    """Write every stored account to `output`; return them by role.

    The temporary passwords go to `PASSWORDS_FILENAME` beside it.
    """
    settings = get_settings()
    client: AsyncMongoClient = AsyncMongoClient(settings.mongo_url, tz_aware=False)
    try:
        cursor = client[settings.mongo_database]["users"].find({})
        db_users = [db_user async for db_user in cursor]
    finally:
        await client.close()

    users = [to_keycloak_user(user, create_temporary_password()) for user in db_users]
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_private(output, json.dumps({"users": users}, indent=2) + "\n")
    _write_private(output.parent / PASSWORDS_FILENAME, _to_passwords_csv(users))
    return Counter(user["realmRoles"][0] for user in users)


def _to_passwords_csv(users: list[dict]) -> str:
    """Return `email,temporary_password` rows, one per account."""
    rows = io.StringIO()
    writer = csv.writer(rows)
    writer.writerow(["email", "temporary_password"])
    for user in users:
        writer.writerow([user["email"], user["credentials"][0]["value"]])
    return rows.getvalue()


def _write_private(path: Path, text: str) -> None:
    """Write `text` to `path`, readable only by its owner."""
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(text)


def main() -> None:
    """Export to the path given, else to `DEFAULT_OUTPUT`."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    by_role = asyncio.run(export_users(output))
    logger.info(
        "Exported %d accounts to %s (%s); temporary passwords in %s.",
        sum(by_role.values()),
        output,
        ", ".join(f"{count} {role}" for role, count in sorted(by_role.items())),
        output.parent / PASSWORDS_FILENAME,
    )


if __name__ == "__main__":
    main()
