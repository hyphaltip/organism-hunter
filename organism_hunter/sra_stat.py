"""Query NCBI's SRA Taxonomy Analysis Tool (STAT) k-mer tables on BigQuery.

STAT scans every submitted SRA run against a k-mer database and records what
taxa it found, independent of what the submitter *said* the run contained --
this is what lets it surface an organism inside unrelated metagenomes/
metatranscriptomes that were never labeled with that organism.

Tables live in the public `nih-sra-datastore` BigQuery project. Schemas below
were verified directly against the live tables:

  sra_tax_analysis_tool.taxonomy      0.4 GB   3.5M rows
      tax_id, parent_id, rank, sci_name, names<name, name_class>, ilevel,
      ileft, iright
      NOTE: the scientific-name column is `sci_name`, NOT `name`; `names` is a
      REPEATED record of synonyms/common names.

  sra_tax_analysis_tool.tax_analysis  1.55 TB  17.6 BILLION rows
      acc, tax_id, rank, name, total_count, self_count, ilevel, ileft, iright

  sra.metadata                        86 GB    44M rows
      37 columns; has `assay_type` (NOT `librarystrategy`) and has NO lat/lon
      column at all -- geography is country-level only
      (`geo_loc_name_country_calc`, `geo_loc_name_sam`). Coordinates exist only
      inside the raw `attributes`/`jattr` blobs, which are expensive to scan.

COST WARNING
------------
`tax_analysis` is neither partitioned nor clustered, so a `WHERE tax_id = ...`
filter does NOT reduce the bytes scanned -- BigQuery reads every selected
column across all 17.6B rows. Measured dry-run costs for a single taxon query:

    SELECT acc                               ->  365 GB
    SELECT acc, total_count                  ->  506 GB
    SELECT acc, tax_id, total_count, self_count -> 646 GB
    SELECT acc, tax_id, total_count, self_count, rank, name -> 1.13 TB

BigQuery's free tier is 1 TB/month, so *one* careless query can consume it and
start billing (~$6.25/TB after). Accordingly:
  - queries here select the minimum set of columns,
  - every job is submitted with `maximum_bytes_billed` set (default 1 TB) so an
    unexpectedly expensive query is REJECTED rather than silently billed,
  - `estimate_bytes()` runs a free dry run so callers can show the cost and
    confirm before spending anything.
"""

from __future__ import annotations

from organism_hunter import config
from organism_hunter.config import (
    BIGQUERY_PROJECT,
    MAX_BYTES_BILLED,
    SRA_METADATA_TABLE,
    STAT_DATASET,
)
from organism_hunter.models import SraHit

# Verified present in sra.metadata. `lat_lon_sam` deliberately absent -- it does
# not exist; STAT hits therefore carry country-level geography only and will not
# appear as points on a coordinate map (unlike Branchwater hits, whose metadata
# server does return lat_lon).
_CANDIDATE_METADATA_COLUMNS = [
    "acc",
    "organism",
    "bioproject",
    "biosample",
    "assay_type",
    "librarysource",
    "geo_loc_name_country_calc",
    "geo_loc_name_country_continent_calc",
    "geo_loc_name_sam",
    "collection_date_sam",
]


def _get_client(project: str | None):
    # Read through the module so tests/callers can toggle it at runtime, and so
    # every query path (including free dry runs) is gated by the same switch.
    if not config.STAT_ENABLED:
        raise RuntimeError(config.STAT_DISABLED_MESSAGE)
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


def _job_config(query_parameters=None, dry_run: bool = False, max_bytes: int | None = None):
    from google.cloud import bigquery

    return bigquery.QueryJobConfig(
        query_parameters=query_parameters or [],
        dry_run=dry_run,
        use_query_cache=not dry_run,
        # None means "no ceiling"; callers must opt into that explicitly.
        maximum_bytes_billed=(MAX_BYTES_BILLED if max_bytes is None else max_bytes),
    )


def estimate_bytes(query: str, query_parameters=None, project: str | None = None) -> int:
    """Dry-run a query and return bytes it would scan. Free -- bills nothing."""
    client = _get_client(project)
    job = client.query(query, job_config=_job_config(query_parameters, dry_run=True))
    return job.total_bytes_processed


def find_tax_id(name: str, project: str | None = None, include_synonyms: bool = True) -> int | None:
    """Look up the NCBI taxid STAT uses for a scientific name.

    Cheap (~120 MB scan): `taxonomy` is only 0.4 GB. With `include_synonyms`,
    also matches common names/synonyms in the repeated `names` record.
    """
    client = _get_client(project)
    from google.cloud import bigquery

    if include_synonyms:
        query = f"""
            SELECT tax_id, sci_name
            FROM `{STAT_DATASET}.taxonomy`
            WHERE LOWER(sci_name) = LOWER(@name)
               OR EXISTS (
                    SELECT 1 FROM UNNEST(names) AS n
                    WHERE LOWER(n.name) = LOWER(@name)
               )
            ORDER BY CASE WHEN LOWER(sci_name) = LOWER(@name) THEN 0 ELSE 1 END
            LIMIT 1
        """
    else:
        query = f"""
            SELECT tax_id, sci_name
            FROM `{STAT_DATASET}.taxonomy`
            WHERE LOWER(sci_name) = LOWER(@name)
            LIMIT 1
        """

    params = [bigquery.ScalarQueryParameter("name", "STRING", name)]
    job = client.query(query, job_config=_job_config(params))
    rows = list(job.result())
    return rows[0]["tax_id"] if rows else None


def _hits_query(limit_clause: bool = True) -> str:
    """Minimal-column query against tax_analysis. Every added column costs ~100+ GB."""
    return f"""
        SELECT acc, total_count
        FROM `{STAT_DATASET}.tax_analysis`
        WHERE tax_id = @tax_id
        ORDER BY total_count DESC
        {"LIMIT @limit" if limit_clause else ""}
    """


def estimate_hits_bytes(tax_id: int, limit: int = 500, project: str | None = None) -> int:
    """Free dry run: how many bytes would `hits_for_tax_id` scan? (~500 GB typical)"""
    from google.cloud import bigquery

    params = [
        bigquery.ScalarQueryParameter("tax_id", "INT64", tax_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    return estimate_bytes(_hits_query(), params, project=project)


def hits_for_tax_id(
    tax_id: int,
    limit: int = 500,
    project: str | None = None,
    max_bytes: int | None = None,
) -> list[SraHit]:
    """Return SRA runs with k-mer hits to `tax_id`, ranked by total k-mer count.

    EXPENSIVE: scans ~500 GB regardless of `limit` (see module docstring).
    Call `estimate_hits_bytes` first to show the cost. The job is capped at
    `max_bytes` (default `MAX_BYTES_BILLED`, 1 TB) and will fail rather than
    overrun it; pass `max_bytes=0` to remove the cap entirely.
    """
    client = _get_client(project)
    from google.cloud import bigquery

    params = [
        bigquery.ScalarQueryParameter("tax_id", "INT64", tax_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    cap = None if max_bytes is None else (None if max_bytes == 0 else max_bytes)
    job = client.query(_hits_query(), job_config=_job_config(params, max_bytes=cap))
    return [
        SraHit(
            accession=row["acc"],
            source="stat",
            kmer_count=row["total_count"],
            tax_id=tax_id,
        )
        for row in job.result()
    ]


def _existing_metadata_columns(client) -> list[str]:
    dataset, table = SRA_METADATA_TABLE.rsplit(".", 1)
    query = f"""
        SELECT column_name
        FROM `{dataset}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = @table_name
    """
    from google.cloud import bigquery

    params = [bigquery.ScalarQueryParameter("table_name", "STRING", table)]
    job = client.query(query, job_config=_job_config(params))
    available = {row["column_name"] for row in job.result()}
    return [c for c in _CANDIDATE_METADATA_COLUMNS if c in available]


def enrich_with_metadata(
    hits: list[SraHit], project: str | None = None, max_bytes: int | None = None
) -> list[SraHit]:
    """Fill in organism/bioproject/country fields on STAT hits from sra.metadata.

    Moderate cost: ~4.6 GB per call for the column set above. Note that
    sra.metadata has no coordinate column, so `lat_lon` stays None for STAT hits.
    """
    if not hits:
        return hits
    client = _get_client(project)
    columns = _existing_metadata_columns(client)
    if "acc" not in columns:
        return hits  # schema drifted enough that we can't safely join

    from google.cloud import bigquery

    accessions = [h.accession for h in hits]
    query = f"""
        SELECT {", ".join(columns)}
        FROM `{SRA_METADATA_TABLE}`
        WHERE acc IN UNNEST(@accessions)
    """
    params = [bigquery.ArrayQueryParameter("accessions", "STRING", accessions)]
    cap = None if max_bytes is None else (None if max_bytes == 0 else max_bytes)
    job = client.query(query, job_config=_job_config(params, max_bytes=cap))
    meta = {row["acc"]: dict(row.items()) for row in job.result()}

    for hit in hits:
        row = meta.get(hit.accession)
        if not row:
            continue
        hit.organism = row.get("organism", hit.organism)
        hit.bioproject = row.get("bioproject", hit.bioproject)
        hit.biosample = row.get("biosample", hit.biosample)
        hit.library_strategy = row.get("assay_type", hit.library_strategy)
        hit.library_source = row.get("librarysource", hit.library_source)
        hit.geo_loc_name = row.get("geo_loc_name_sam") or row.get("geo_loc_name_country_calc")
        collected = row.get("collection_date_sam")
        hit.collection_date = str(collected) if collected is not None else hit.collection_date
    return hits
