from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import String, engine_from_config, pool, text

from alembic import context  # type: ignore[attr-defined]

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _build_postgres_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DBNAME") or os.getenv("POSTGRES_DB", "evidencelab")
    user = os.getenv("POSTGRES_USER", "evidencelab")
    password = os.getenv("POSTGRES_PASSWORD", "evidencelab")
    return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db}"


VERSION_NUM_TYPE = String(128)


def _widen_version_column(connection) -> None:  # type: ignore[no-untyped-def]
    """Ensure alembic_version.version_num can hold 128-char revision IDs.

    Older installations may have the default varchar(32) which is too short
    for descriptive revision IDs such as ``0006_fix_default_group_description``.
    """
    result = connection.execute(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'alembic_version' AND column_name = 'version_num'"
        )
    )
    row = result.fetchone()
    if row and row[0] is not None and row[0] < 128:
        connection.execute(
            text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(128)"
            )
        )
        connection.commit()


def run_migrations_offline() -> None:
    url = _build_postgres_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_num_type=VERSION_NUM_TYPE,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _build_postgres_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _widen_version_column(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_num_type=VERSION_NUM_TYPE,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
