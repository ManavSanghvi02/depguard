"""Give depguard_api and depguard_refresh a login password, taken from their own URLs.

`make migrate` runs this after the migrations, as the table owner. The password lives only in
DATABASE_URL / REFRESH_DATABASE_URL (.env locally), so there is no second copy to keep in sync.
"""

import asyncio
from urllib.parse import unquote, urlsplit

import asyncpg

from depguard.config import Settings, get_settings

# The only roles this may touch: never the owner or a Supabase system role.
ROLES = {"depguard_api", "depguard_refresh"}
# The .env.example placeholders are fine for the local Docker database, nowhere else.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def role_and_password(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    role, password = unquote(parts.username or ""), unquote(parts.password or "")
    if role not in ROLES:
        raise SystemExit(f"expected a URL for one of {sorted(ROLES)}, got user {role!r}")
    if not password:
        raise SystemExit(f"the URL for {role} has no password")
    if password.startswith("change-me") and parts.hostname not in LOCAL_HOSTS:
        raise SystemExit(f"{role} still has the .env.example placeholder password; set a real one")
    return role, password


async def set_passwords(settings: Settings) -> list[str]:
    urls = {
        "DATABASE_URL": settings.database_url,
        "REFRESH_DATABASE_URL": settings.refresh_database_url,
        "MIGRATION_DATABASE_URL": settings.migration_database_url,
    }
    missing = [name for name, url in urls.items() if not url]
    if missing:
        raise SystemExit(f"not set: {', '.join(missing)}")
    roles = [
        role_and_password(settings.database_url),
        role_and_password(settings.refresh_database_url),
    ]
    connection = await asyncpg.connect(settings.migration_database_url)
    try:
        for role, password in roles:
            # ALTER ROLE can't take query parameters, so Postgres's format() quotes both safely
            # (%I = identifier, %L = literal) and the result is run.
            statement = await connection.fetchval(
                "SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', $1::text, $2::text)",
                role,
                password,
            )
            await connection.execute(statement)
    finally:
        await connection.close()
    return [role for role, _ in roles]


if __name__ == "__main__":
    for role in asyncio.run(set_passwords(get_settings())):
        print(f"password set for {role}")  # never the password itself
