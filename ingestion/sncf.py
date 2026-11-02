"""Téléchargement des jeux de données SNCF (open data) au format Parquet."""
import logging

import requests

from ingestion.config import RAW_DIR, SNCF_API, SNCF_DATASETS

log = logging.getLogger(__name__)


def download_dataset(dataset_id: str, table: str) -> None:
    out = RAW_DIR / "sncf" / f"{table}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"{SNCF_API}/{dataset_id}/exports/parquet"
    with requests.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        tmp = out.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.replace(out)
    log.info("SNCF %-35s -> %s (%.0f Ko)", dataset_id, out.name, out.stat().st_size / 1024)


def run() -> None:
    for dataset_id, table in SNCF_DATASETS.items():
        download_dataset(dataset_id, table)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run()
