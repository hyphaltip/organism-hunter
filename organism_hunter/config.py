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
