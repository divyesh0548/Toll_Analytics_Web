"""Shared insert helpers for plaza analytics fact tables."""

from __future__ import annotations

from psycopg2 import sql
from psycopg2.extras import execute_values


def fetch_existing_keys(conn, table_name: str, key_columns: list[str], rows: list[dict]) -> set[tuple]:
    if not rows:
        return set()

    keys = [tuple(row[column] for column in key_columns) for row in rows]
    columns_sql = sql.SQL(", ").join(sql.Identifier(column) for column in key_columns)
    query = sql.SQL(
        "SELECT {columns} FROM {table} WHERE ({columns}) IN %s"
    ).format(columns=columns_sql, table=sql.Identifier(table_name))

    with conn.cursor() as cursor:
        cursor.execute(query.as_string(conn), (tuple(keys),))
        return {tuple(record) for record in cursor.fetchall()}


def insert_new_rows(
    conn,
    table_name: str,
    data_columns: list[str],
    key_columns: list[str],
    rows: list[dict],
    *,
    label: str,
) -> tuple[int, int]:
    """Skip rows whose natural key already exists; insert the rest."""
    if not rows:
        return 0, 0

    existing_keys = fetch_existing_keys(conn, table_name, key_columns, rows)
    rows_to_insert: list[dict] = []
    skipped = 0

    for row in rows:
        key = tuple(row[column] for column in key_columns)
        if key in existing_keys:
            skipped += 1
            continue
        rows_to_insert.append(row)

    if skipped:
        print(f"  {label}: skipped {skipped} existing row(s)")

    if not rows_to_insert:
        return 0, skipped

    insert_sql = sql.SQL("INSERT INTO {table} ({fields}) VALUES %s").format(
        table=sql.Identifier(table_name),
        fields=sql.SQL(", ").join(sql.Identifier(column) for column in data_columns),
    )
    values = [tuple(row[column] for column in data_columns) for row in rows_to_insert]
    with conn.cursor() as cursor:
        execute_values(cursor, insert_sql.as_string(conn), values)
    conn.commit()
    print(f"  {label}: inserted {len(rows_to_insert)} row(s)")
    return len(rows_to_insert), skipped
