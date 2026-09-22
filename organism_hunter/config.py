"""Centralized defaults for external service endpoints and local cache locations.

Nothing here requires secrets to import. Optional credentials (GCP project for
BigQuery, an NCBI E-utilities API key) are read from the environment lazily by
the modules that need them, not at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

GBIF_API = "https://api.gbif.org/v1"

NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_DATASETS_API = "https://api.ncbi.nlm.nih.gov/datasets/v2"
NCBI_API_KEY = os.environ.get("NCBI_API_KEY")  # optional, raises E-utilities rate limit 3->10 req/s
NCBI_EMAIL = os.environ.get("NCBI_EMAIL")  # recommended by NCBI usage policy

# BigQuery public dataset published by NCBI for the SRA Taxonomy Analysis Tool (STAT).
# See https://www.ncbi.nlm.nih.gov/sra/docs/sra-cloud-based-taxonomy-analysis-table/
BIGQUERY_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")  # billing project, must be yours
STAT_DATASET = "nih-sra-datastore.sra_tax_analysis_tool"
SRA_METADATA_TABLE = "nih-sra-datastore.sra.metadata"

# Hard ceiling on bytes any single BigQuery job may bill, so an unexpectedly
# expensive query fails fast instead of silently eating the 1 TB/month free
# tier (a single unfiltered tax_analysis scan can exceed it -- see sra_stat).
MAX_BYTES_BILLED = int(os.environ.get("ORGANISM_HUNTER_MAX_BYTES_BILLED") or 1024**4)  # 1 TiB

# Master kill switch for the STAT/BigQuery backend, OFF by default: it is the
# only metered backend (GBIF, Branchwater and Logan are free), and even its
# cheap taxonomy lookup is a billed query. Nothing in this package will talk to
# BigQuery until this is explicitly turned on.
STAT_ENABLED = (os.environ.get("ORGANISM_HUNTER_ENABLE_STAT") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
STAT_DISABLED_MESSAGE = (
    "STAT/BigQuery is disabled (it is the only backend that costs money: a single "
    "tax_analysis query scans ~500 GB of a 1 TB/month free tier). Enable it with "
    "ORGANISM_HUNTER_ENABLE_STAT=1. GBIF, Branchwater and Logan are unaffected."
)

BRANCHWATER_SERVER = os.environ.get("BRANCHWATER_SERVER", "https://api.branchwater.sourmash.bio")
BRANCHWATER_METADATA_SERVER = os.environ.get(
    "BRANCHWATER_METADATA_SERVER", "https://branchwater.sourmash.bio"
)
BRANCHWATER_CLIENT_BIN = os.environ.get("BRANCHWATER_CLIENT_BIN", "branchwater-client")

SOURMASH_BIN = os.environ.get("SOURMASH_BIN", "sourmash")
LOGAN_BLASTER_BIN = os.environ.get("LOGAN_BLASTER_BIN", "logan_blaster")
LOGAN_S3_UNITIGS = "s3://logan-pub/u"
LOGAN_S3_CONTIGS = "s3://logan-pub/c"
LOGAN_SEARCH_DASHBOARD = "https://logan-search.org/dashboard"

CACHE_DIR = Path(os.environ.get("ORGANISM_HUNTER_CACHE", Path.home() / ".cache" / "organism_hunter"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HTTP_TIMEOUT = 30
