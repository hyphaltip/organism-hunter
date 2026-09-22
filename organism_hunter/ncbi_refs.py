"""Fetch reference sequences from NCBI to build sourmash signatures from.

Two complementary paths, since taxa vary widely in what's available:
- `fetch_barcode_sequences`: short marker/barcode sequences (COI, ITS, 16S, rbcL...)
  via E-utilities esearch+efetch against the `nuccore` database. Works even for
  poorly-sequenced organisms that only have barcode records.
- `fetch_reference_genome`: a full assembly FASTA via the NCBI Datasets API, for
  taxa that have one. Gives sourmash something much more specific to sketch.

Both are best-effort: callers should fall back to a user-supplied FASTA when
NCBI has nothing usable for their organism.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import requests

from organism_hunter.config import (
    HTTP_TIMEOUT,
    NCBI_API_KEY,
    NCBI_DATASETS_API,
    NCBI_EMAIL,
    NCBI_EUTILS,
)


def _eutils_params(extra: dict) -> dict:
    params = dict(extra)
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    if NCBI_EMAIL:
        params["email"] = NCBI_EMAIL
    return params


def fetch_barcode_sequences(
    organism_name: str,
    gene: str = "COI",
    max_records: int = 20,
    out_path: str | Path | None = None,
) -> Path:
    """Search nuccore for `"<organism_name>"[Organism] AND <gene>[Gene]` and save FASTA.

    NCBI asks for no more than 3 requests/sec without an api_key (10/sec with
    one); we sleep briefly between the esearch and efetch calls to be polite.
    """
    term = f'"{organism_name}"[Organism] AND {gene}[Gene]'
    search = requests.get(
        f"{NCBI_EUTILS}/esearch.fcgi",
        params=_eutils_params({"db": "nuccore", "term": term, "retmax": max_records, "retmode": "json"}),
        timeout=HTTP_TIMEOUT,
    )
    search.raise_for_status()
    ids = search.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        raise ValueError(f"No nuccore records found for {organism_name!r} gene={gene!r}")

    time.sleep(0.35 if not NCBI_API_KEY else 0.1)
    fetch = requests.get(
        f"{NCBI_EUTILS}/efetch.fcgi",
        params=_eutils_params({"db": "nuccore", "id": ",".join(ids), "rettype": "fasta", "retmode": "text"}),
        timeout=HTTP_TIMEOUT,
    )
    fetch.raise_for_status()

    out_path = Path(out_path) if out_path else Path(f"{organism_name.replace(' ', '_')}_{gene}.fasta")
    out_path.write_text(fetch.text)
    return out_path


def fetch_reference_genome(taxon_name_or_id: str, out_path: str | Path | None = None) -> Path:
    """Download the FASTA for a representative/reference assembly of a taxon via NCBI Datasets.

    Uses the "genome download" endpoint, which returns a zip archive containing
    one FASTA per assembly; only the first assembly found is kept.
    """
    resp = requests.get(
        f"{NCBI_DATASETS_API}/genome/taxon/{taxon_name_or_id}/dataset_report",
        params={"filters.reference_only": "true", "page_size": 1},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    reports = resp.json().get("reports", [])
    if not reports:
        raise ValueError(f"No reference assembly found for taxon {taxon_name_or_id!r}")
    accession = reports[0]["accession"]

    dl = requests.get(
        f"{NCBI_DATASETS_API}/genome/accession/{accession}/download",
        params={"include_annotation_type": "GENOME_FASTA"},
        timeout=HTTP_TIMEOUT,
        stream=True,
    )
    dl.raise_for_status()

    out_path = Path(out_path) if out_path else Path(f"{accession}.fasta")
    with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
        fasta_names = [n for n in zf.namelist() if n.endswith(".fna")]
        if not fasta_names:
            raise ValueError(f"Downloaded dataset for {accession} contained no .fna FASTA file")
        with zf.open(fasta_names[0]) as src, open(out_path, "wb") as dst:
            dst.write(src.read())
    return out_path
