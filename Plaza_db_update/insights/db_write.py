"""Shared upsert helpers for plaza analytics fact tables."""

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


def upsert_rows(
    conn,
    table_name: str,
    data_columns: list[str],
    key_columns: list[str],
    rows: list[dict],
    *,
    label: str,
    always_replace_columns: list[str] | None = None,
) -> tuple[int, int]:
    """
    Insert new rows; on natural-key conflict, update metric columns only when
    the new value is greater (otherwise keep existing). Text/name columns listed
    in always_replace_columns are always refreshed.
    """
    if not rows:
        return 0, 0

    existing_keys = fetch_existing_keys(conn, table_name, key_columns, rows)
    update_columns = [column for column in data_columns if column not in key_columns]
    if not update_columns:
        raise ValueError(
            f"{label}: no non-key columns to update for table '{table_name}'."
        )

    always = {
        str(column).strip()
        for column in (always_replace_columns or ["plaza_name"])
        if str(column).strip()
    }
    assignments = []
    for column in update_columns:
        col_id = sql.Identifier(column)
        if column in always:
            assignments.append(
                sql.SQL("{col} = EXCLUDED.{col}").format(col=col_id)
            )
            continue
        # Greater-only for metrics; fill when existing is NULL.
        assignments.append(
            sql.SQL(
                """
                {col} = CASE
                    WHEN EXCLUDED.{col} IS NULL THEN {table}.{col}
                    WHEN {table}.{col} IS NULL THEN EXCLUDED.{col}
                    WHEN EXCLUDED.{col} > {table}.{col} THEN EXCLUDED.{col}
                    ELSE {table}.{col}
                END
                """
            ).format(col=col_id, table=sql.Identifier(table_name))
        )

    insert_sql = sql.SQL(
        """
        INSERT INTO {table} ({fields}) VALUES %s
        ON CONFLICT ({conflict_keys}) DO UPDATE SET {assignments}
        """
    ).format(
        table=sql.Identifier(table_name),
        fields=sql.SQL(", ").join(sql.Identifier(column) for column in data_columns),
        conflict_keys=sql.SQL(", ").join(
            sql.Identifier(column) for column in key_columns
        ),
        assignments=sql.SQL(", ").join(assignments),
    )

    values = [tuple(row[column] for column in data_columns) for row in rows]
    with conn.cursor() as cursor:
        execute_values(cursor, insert_sql.as_string(conn), values)
    conn.commit()

    updated = sum(
        1
        for row in rows
        if tuple(row[column] for column in key_columns) in existing_keys
    )
    inserted = len(rows) - updated
    print(
        f"  {label}: upserted {len(rows)} row(s) "
        f"(inserted={inserted}, conflict_keys={updated}; "
        f"metrics update only when new > existing)"
    )
    return inserted, updated


def insert_new_rows(
    conn,
    table_name: str,
    data_columns: list[str],
    key_columns: list[str],
    rows: list[dict],
    *,
    label: str,
) -> tuple[int, int]:
    """Deprecated alias — use upsert_rows (greater-only updates on conflict)."""
    return upsert_rows(
        conn,
        table_name,
        data_columns,
        key_columns,
        rows,
        label=label,
    )
