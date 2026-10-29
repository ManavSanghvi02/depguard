"""Runs migrations as the table owner (MIGRATION_DATABASE_URL). Tests pass their own URL through
the `url` config option instead."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from depguard.config import get_settings
from depguard.db.models import Base
from depguard.db.postgres import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = config.get_main_option("url") or get_settings().migration_database_url
if not url:
    raise SystemExit("MIGRATION_DATABASE_URL is not set (see .env.example)")


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    # The app's async driver, so there's one Postgres driver (asyncpg) everywhere.
    engine = make_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
        await connection.commit()
    await engine.dispose()


asyncio.run(main())
