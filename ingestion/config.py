"""Configuration centrale de l'ingestion."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DUCKDB_PATH = DATA_DIR / "ponctualite.duckdb"

# --- SNCF open data (plateforme Opendatasoft, API Explore v2.1) ---
SNCF_API = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets"
SNCF_DATASETS = {
    # id du jeu de données -> nom de la table brute
    "regularite-mensuelle-tgv-aqst": "tgv_regularite",
    "regularite-mensuelle-ter": "ter_regularite",
    "regularite-mensuelle-intercites": "intercites_regularite",
    "frequentation-gares": "frequentation_gares",
}

# --- Météo-France : données climatologiques mensuelles par département ---
METEO_BASE = "https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/MENS"
# Les fichiers "previous" changent une fois par an, les "latest" chaque jour.
METEO_PERIODS = {"previous": "previous-1950-2024", "latest": "latest-2025-2026"}
METEO_START_MONTH = 201301  # début des séries SNCF
METEO_COLUMNS = [
    "NUM_POSTE", "NOM_USUEL", "LAT", "LON", "ALTI", "AAAAMM",
    "RR",        # cumul de précipitations (mm)
    "NBJRR10",   # nb jours avec pluie >= 10 mm
    "TM", "TN", "TX",  # températures moyennes (°C)
    "NBJGELEE",  # nb jours de gel
    "NBJTX30",   # nb jours de chaleur (TX >= 30°C)
    "NBJFF16",   # nb jours de vent fort (rafales >= 16 m/s)
]
DEPARTEMENTS = [f"{i:02d}" for i in range(1, 96)]  # Corse = "20" chez Météo-France
