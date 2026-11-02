"""Chargement des fichiers bruts (Parquet) dans le schéma `raw` de DuckDB."""
import logging

import duckdb

from ingestion.config import DUCKDB_PATH, RAW_DIR, SNCF_DATASETS

log = logging.getLogger(__name__)


def run() -> None:
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))
    con.execute("create schema if not exists raw")
    for table in SNCF_DATASETS.values():
        path = RAW_DIR / "sncf" / f"{table}.parquet"
        con.execute(
            f"create or replace table raw.{table} as "
            f"select *, current_timestamp as _loaded_at from read_parquet('{path}')"
        )
    meteo_glob = RAW_DIR / "meteo" / "*.parquet"
    con.execute(
        "create or replace table raw.meteo_mensuelle as "
        f"select *, current_timestamp as _loaded_at from read_parquet('{meteo_glob}', union_by_name=true)"
    )
    for (name, n) in con.execute(
        "select table_name, estimated_size from duckdb_tables() where schema_name='raw' order by 1"
    ).fetchall():
        log.info("raw.%-25s %8d lignes", name, n)
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run()
