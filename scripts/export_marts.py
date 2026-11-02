"""Exporte les tables du schéma `marts` en Parquet dans data/marts/.

Ces fichiers (quelques Mo) sont versionnés : l'app Streamlit et Power BI les lisent
directement, sans avoir besoin de relancer tout le pipeline.
"""
import duckdb

from ingestion.config import DATA_DIR, DUCKDB_PATH

OUT = DATA_DIR / "marts"


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    tables = [r[0] for r in con.execute(
        "select table_name from duckdb_tables() where schema_name = 'marts' order by 1").fetchall()]
    for t in tables:
        con.execute(f"copy marts.{t} to '{OUT / t}.parquet' (format parquet, compression zstd)")
        print(f"export marts.{t}")
    con.close()


if __name__ == "__main__":
    run()
