"""Téléchargement des données climatologiques mensuelles Météo-France.

Un fichier CSV gzippé par département et par période. On ne garde que les
mois couverts par les séries SNCF et quelques indicateurs utiles.
Les fichiers "previous" (historique figé) ne sont retéléchargés que s'ils
manquent ; les fichiers "latest" sont rafraîchis à chaque exécution.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from ingestion.config import (
    DEPARTEMENTS, METEO_BASE, METEO_COLUMNS, METEO_PERIODS, METEO_START_MONTH, RAW_DIR,
)

log = logging.getLogger(__name__)
OUT_DIR = RAW_DIR / "meteo"


def _fetch(dep: str, period_key: str, force: bool) -> None:
    out = OUT_DIR / f"meteo_{period_key}_{dep}.parquet"
    if out.exists() and not force:
        return
    url = f"{METEO_BASE}/MENSQ_{dep}_{METEO_PERIODS[period_key]}.csv.gz"
    r = requests.get(url, timeout=180)
    if r.status_code == 404:
        log.warning("Météo : fichier absent %s", url)
        return
    r.raise_for_status()
    tmp_gz = out.with_suffix(".csv.gz")
    tmp_gz.write_bytes(r.content)
    df = pd.read_csv(
        tmp_gz, sep=";", usecols=lambda c: c in METEO_COLUMNS,
        dtype={"NUM_POSTE": str}, low_memory=False,
    )
    tmp_gz.unlink()
    df = df[df["AAAAMM"] >= METEO_START_MONTH]
    df.insert(0, "DEPARTEMENT", dep)
    df.to_parquet(out, index=False)


def run(refresh_history: bool = False) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [(d, "previous", refresh_history) for d in DEPARTEMENTS]
    jobs += [(d, "latest", True) for d in DEPARTEMENTS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda j: _fetch(*j), jobs))
    log.info("Météo : %d fichiers département disponibles", len(list(OUT_DIR.glob("*.parquet"))))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run()
