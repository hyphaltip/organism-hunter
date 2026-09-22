"""Query NCBI's SRA Taxonomy Analysis Tool (STAT) k-mer tables on BigQuery.

STAT scans every submitted SRA run against a k-mer database and records what
taxa it found, independent of what the submitter *said* the run contained --
this is what lets it surface an organism inside unrelated metagenomes/
metatranscriptomes that were never labeled with that organism.

Tables live in the public `nih-sra-datastore` BigQuery project:
  - sra_tax_analysis_tool.taxonomy      : tax_id <-> name (NCBI taxonomy)
  - sra_tax_analysis_tool.tax_analysis  : acc, tax_id, total_count, self_count
  - sra.metadata                        : full SRA run metadata, joinable on acc

Querying requires a Google Cloud project of your own with BigQuery enabled
(queries against public datasets are billed to *your* project, though the
first 1 TB/month is free). Set GOOGLE_CLOUD_PROJECT or pass project explicitly.

The `sra.metadata` schema is wide and has evolved over time with harvested
BioSample attribute columns (many have `_sam`/`_calc` suffixes and are not
guaranteed to exist for every run). Rather than hard-coding a column list that
may drift, `enrich_with_metadata` first checks which of a candidate set of
columns actually exist via INFORMATION_SCHEMA before building the SELECT.
"""

from __future__ import annotations

from organism_hunter.config import BIGQUERY_PROJECT, SRA_METADATA_TABLE, STAT_DATASET
from organism_hunter.models import SraHit

_CANDIDATE_METADATA_COLUMNS = [
    "acc",
    "organism",
    "bioproject",
    "biosample",
    "librarystrategy",
    "librarysource",
    "geo_loc_name_country_calc",
    "geo_loc_name_sam",
    "lat_lon_sam",
    "collection_date_sam",
]


def _get_client(project: str | None):
    try:
        from google.cloud import bigquery
    except ImportError as e:
        raise RuntimeError(
            "google-cloud-bigquery is required for STAT queries: "
            "pip install 'organism-hunter[bigquery]'"
        ) from e
    project = project or BIGQUERY_PROJECT
    if not project:
        raise RuntimeError(
            "No billing project set. Pass project=... or set GOOGLE_CLOUD_PROJECT "
            "to a Google Cloud project with BigQuery enabled."
        )
    return bigquery.Client(project=project)


def find_tax_id(name: str, project: str | None = None) -> int | None:
    """Look up the NCBI taxid STAT uses internally for a scientific name."""
    client = _get_client(project)
    query = f"""
        SELECT tax_id, name
        FROM `{STAT_DATASET}.taxonomy`
        WHERE LOWER(name) = LOWER(@name)
        LIMIT 1
    """
    from google.cloud import bigquery

    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("name", "STRING", name)]
        ),
    )
    rows = list(job.result())
    return rows[0]["tax_id"] if rows else None


def hits_for_tax_id(tax_id: int, limit: int = 500, project: str | None = None) -> list[SraHit]:
    """Return SRA runs with k-mer hits to `tax_id`, ranked by total k-mer count."""
    client = _get_client(project)
    from google.cloud import bigquery

    query = f"""
        SELECT acc, tax_id, total_count, self_count
        FROM `{STAT_DATASET}.tax_analysis`
        WHERE tax_id = @tax_id
        ORDER BY total_count DESC
        LIMIT @limit
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("tax_id", "INT64", tax_id),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
        ),
    )
    return [
        SraHit(
            accession=row["acc"],
            source="stat",
            kmer_count=row["total_count"],
            tax_id=row["tax_id"],
        )
        for row in job.result()
    ]


def _existing_metadata_columns(client, project: str | None) -> list[str]:
    dataset, table = SRA_METADATA_TABLE.rsplit(".", 1)
    query = f"""
        SELECT column_name
        FROM `{dataset}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = @table_name
    """
    from google.cloud import bigquery

    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", table)]
        ),
    )
    available = {row["column_name"] for row in job.result()}
    return [c for c in _CANDIDATE_METADATA_COLUMNS if c in available]


def enrich_with_metadata(hits: list[SraHit], project: str | None = None) -> list[SraHit]:
    """Fill in organism/bioproject/geolocation fields on STAT hits from sra.metadata."""
    if not hits:
        return hits
    client = _get_client(project)
    columns = _existing_metadata_columns(client, project)
    if "acc" not in columns:
        return hits  # schema drifted enough that we can't safely join

    from google.cloud import bigquery

    accessions = [h.accession for h in hits]
    query = f"""
        SELECT {", ".join(columns)}
        FROM `{SRA_METADATA_TABLE}`
        WHERE acc IN UNNEST(@accessions)
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("accessions", "STRING", accessions)
            ]
        ),
    )
    meta = {row["acc"]: dict(row.items()) for row in job.result()}

    for hit in hits:
        row = meta.get(hit.accession)
        if not row:
            continue
        hit.organism = row.get("organism", hit.organism)
        hit.bioproject = row.get("bioproject", hit.bioproject)
        hit.biosample = row.get("biosample", hit.biosample)
        hit.library_strategy = row.get("librarystrategy", hit.library_strategy)
        hit.library_source = row.get("librarysource", hit.library_source)
        hit.geo_loc_name = row.get("geo_loc_name_country_calc") or row.get("geo_loc_name_sam")
        hit.lat_lon = row.get("lat_lon_sam", hit.lat_lon)
        hit.collection_date = row.get("collection_date_sam", hit.collection_date)
    return hits
