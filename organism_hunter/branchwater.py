"""Search public SRA metagenomes for a signature via the Branchwater API.

Branchwater (https://branchwater.sourmash.bio) indexes ~1.1M public SRA
metagenomes with sourmash FracMinHash sketches and serves containment search
over them. There is no plain HTTP/JSON contract published for scripting
directly against `api.branchwater.sourmash.bio`; the supported programmatic
path is the `branchwater-client` CLI binary
(https://github.com/sourmash-bio/branchwater), which this module shells out
to and whose CSV output it parses into SraHit records.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import tempfile
from pathlib import Path

from organism_hunter.config import (
    BRANCHWATER_CLIENT_BIN,
    BRANCHWATER_METADATA_SERVER,
    BRANCHWATER_SERVER,
)
from organism_hunter.models import SraHit


def search(
    signature_path: str | Path,
    threshold: float | None = 0.1,
    full: bool = True,
    server: str = BRANCHWATER_SERVER,
    metadata_server: str = BRANCHWATER_METADATA_SERVER,
) -> list[SraHit]:
    """Submit a signature to a Branchwater server and return parsed hits.

    `full=True` asks the client to also pull dataset metadata (geolocation,
    library info) for each hit rather than just accession + containment.

    `branchwater-client` (as of v0.6.3) has no server-side `--threshold` flag,
    so filtering by minimum containment/score happens client-side here after
    the full result set comes back. Pass `threshold=None` to disable it.

    Output is written to a temp file rather than captured from stdout: the
    client interleaves its own JSON progress-log lines onto stdout ahead of
    the CSV when no `-o` is given, which corrupts a naive stdout parse.
    """
    if shutil.which(BRANCHWATER_CLIENT_BIN) is None:
        raise RuntimeError(
            f"'{BRANCHWATER_CLIENT_BIN}' not found on PATH. Download a release from "
            "https://github.com/sourmash-bio/branchwater/releases and put it on PATH, "
            "or set BRANCHWATER_CLIENT_BIN to its full path."
        )

    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "hits.csv"
        cmd = [
            BRANCHWATER_CLIENT_BIN,
            "--sig",
            str(signature_path),
            "-s",
            server,
            "-m",
            metadata_server,
            "-o",
            str(out_file),
        ]
        if full:
            cmd.append("--full")

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"branchwater-client failed: {result.stderr or result.stdout}")

        csv_text = out_file.read_text()

    hits = _parse_csv(csv_text)
    if threshold is not None:
        hits = [h for h in hits if h.score is None or h.score >= threshold]
    return hits


def _parse_csv(csv_text: str) -> list[SraHit]:
    """Parse branchwater-client's CSV output.

    Confirmed columns as of client v0.6.3:
      - without --full: "SRA accession", "containment", "query"
      - with --full:     "acc", "assay_type", "bioproject", "cANI",
                          "collection_date_sam", "containment",
                          "geo_loc_name_country_calc", "lat_lon", "organism"
    Both are handled defensively in case a future release adds/renames fields.
    """
    hits: list[SraHit] = []
    reader = csv.DictReader(csv_text.splitlines())
    for row in reader:
        accession = _none_if_null(
            row.get("acc")
            or row.get("SRA accession")
            or row.get("accession")
            or row.get("SRA_accession")
        )
        if not accession:
            continue  # includes rows that are entirely "NP"/null sentinels
        score_raw = row.get("containment") or row.get("cANI") or row.get("f_match_query")
        hits.append(
            SraHit(
                accession=accession,
                source="branchwater",
                score=float(score_raw) if score_raw not in _MISSING else None,
                organism=_none_if_null(row.get("organism")),
                bioproject=_none_if_null(row.get("bioproject") or row.get("bioproject_acc")),
                biosample=_none_if_null(row.get("biosample") or row.get("biosample_acc")),
                library_strategy=_none_if_null(
                    row.get("assay_type") or row.get("librarystrategy") or row.get("library_strategy")
                ),
                library_source=_none_if_null(row.get("librarysource") or row.get("library_source")),
                geo_loc_name=_none_if_null(
                    row.get("geo_loc_name_country_calc")
                    or row.get("geo_loc_name")
                    or row.get("geographic_location")
                ),
                lat_lon=_none_if_null(row.get("lat_lon")),
                collection_date=_none_if_null(
                    row.get("collection_date_sam") or row.get("collection_date")
                ),
            )
        )
    return hits


#: Sentinels branchwater-client's --full CSV uses for missing values: "null"
#: and "NP" (not provided). A row can have "NP" in *every* field including the
#: accession, which is unusable, so such rows are dropped entirely.
_MISSING = (None, "", "null", "NP")


def _none_if_null(value: str | None) -> str | None:
    return None if value in _MISSING else value
