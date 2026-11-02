"""Point d'entrée unique : ingestion -> chargement -> dbt -> ML -> export.

    python pipeline.py              # tout le pipeline
    python pipeline.py --skip-ingest  # retransforme sans retélécharger
"""
import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from ingestion import load_duckdb, meteo, sncf

ROOT = Path(__file__).parent
log = logging.getLogger("pipeline")


def dbt_build() -> None:
    env = {**os.environ, "DBT_PROFILES_DIR": str(ROOT / "transform")}
    dbt = Path(sys.executable).with_name("dbt")
    subprocess.run([str(dbt), "build"], cwd=ROOT / "transform", env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--refresh-meteo-history", action="store_true")
    args = parser.parse_args()

    if not args.skip_ingest:
        sncf.run()
        meteo.run(refresh_history=args.refresh_meteo_history)
    load_duckdb.run()
    dbt_build()

    from ml import forecast
    forecast.run()

    from scripts import export_marts
    export_marts.run()
    log.info("Pipeline terminé.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    main()
