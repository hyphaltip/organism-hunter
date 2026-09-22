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
import io
import shutil
import subprocess
from pathlib import Path

from organism_hunter.config import (
    BRANCHWATER_CLIENT_BIN,
    BRANCHWATER_METADATA_SERVER,
    BRANCHWATER_SERVER,
)
from organism_hunter.models import SraHit


def search(
    signature_path: str | Path,
    threshold: float = 0.1,
    full: bool = True,
    server: str = BRANCHWATER_SERVER,
    metadata_server: str = BRANCHWATER_METADATA_SERVER,
) -> list[SraHit]:
    """Submit a signature to a Branchwater server and return parsed hits.

    `full=True` asks the client to also pull dataset metadata (geolocation,
    library info) for each hit rather than just accession + containment.
    """
    if shutil.which(BRANCHWATER_CLIENT_BIN) is None:
        raise RuntimeError(
            f"'{BRANCHWATER_CLIENT_BIN}' not found on PATH. Download a release from "
            "https://github.com/sourmash-bio/branchwater/releases and put it on PATH, "
            "or set BRANCHWATER_CLIENT_BIN to its full path."
        )

    cmd = [
        BRANCHWATER_CLIENT_BIN,
        "--sig",
        str(signature_path),
        "-s",
        server,
        "-m",
        metadata_server,
        "--threshold",
        str(threshold),
    ]
    if full:
        cmd.append("--full")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"branchwater-client failed: {result.stderr}")

    return _parse_csv(result.stdout)


def _parse_csv(csv_text: str) -> list[SraHit]:
    hits: list[SraHit] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        accession = row.get("acc") or row.get("accession") or row.get("SRA_accession")
        if not accession:
            continue
        score_raw = row.get("containment") or row.get("cANI") or row.get("f_match_query")
        hits.append(
            SraHit(
                accession=accession,
                source="branchwater",
                score=float(score_raw) if score_raw not in (None, "") else None,
                organism=row.get("organism"),
                bioproject=row.get("bioproject") or row.get("bioproject_acc"),
                biosample=row.get("biosample") or row.get("biosample_acc"),
                library_strategy=row.get("librarystrategy") or row.get("library_strategy"),
                library_source=row.get("librarysource") or row.get("library_source"),
                geo_loc_name=row.get("geo_loc_name") or row.get("geographic_location"),
                lat_lon=row.get("lat_lon"),
                collection_date=row.get("collection_date"),
            )
        )
    return hits
