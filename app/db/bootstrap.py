from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def bootstrap_database(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    if "resources" in existing_tables:
        columns = {column["name"] for column in inspector.get_columns("resources")}
        statements: list[str] = []
        if "provider" not in columns:
            statements.append("ALTER TABLE resources ADD COLUMN provider VARCHAR(32) NOT NULL DEFAULT 'simulated'")
        if "external_id" not in columns:
            statements.append("ALTER TABLE resources ADD COLUMN external_id VARCHAR(255)")
        if "instance_type" not in columns:
            statements.append("ALTER TABLE resources ADD COLUMN instance_type VARCHAR(64)")
        if "cloud_state" not in columns:
            statements.append("ALTER TABLE resources ADD COLUMN cloud_state VARCHAR(64)")
        if "tags_json" not in columns:
            statements.append("ALTER TABLE resources ADD COLUMN tags_json TEXT NOT NULL DEFAULT '{}'")
        _run_statements(engine, statements)

    if "metrics" in existing_tables:
        columns = {column["name"] for column in inspector.get_columns("metrics")}
        statements = []
        if "network_in" not in columns:
            statements.append("ALTER TABLE metrics ADD COLUMN network_in DOUBLE PRECISION NOT NULL DEFAULT 0")
        if "network_out" not in columns:
            statements.append("ALTER TABLE metrics ADD COLUMN network_out DOUBLE PRECISION NOT NULL DEFAULT 0")
        _run_statements(engine, statements)

    if "cost_records" in existing_tables:
        columns = {column["name"] for column in inspector.get_columns("cost_records")}
        statements = []
        if "cost_per_hour" not in columns:
            statements.append("ALTER TABLE cost_records ADD COLUMN cost_per_hour DOUBLE PRECISION NOT NULL DEFAULT 0")
        if "usage_hours" not in columns:
            statements.append("ALTER TABLE cost_records ADD COLUMN usage_hours DOUBLE PRECISION NOT NULL DEFAULT 0")
        _run_statements(engine, statements)


def _run_statements(engine: Engine, statements: list[str]) -> None:
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
