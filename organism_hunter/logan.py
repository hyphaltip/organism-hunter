"""Sequence-level verification of candidate SRA hits against Logan assemblies.

Logan (s3://logan-pub) holds pre-assembled unitigs/contigs for ~26M SRA
accessions. Logan-Search (https://logan-search.org) exposes a k-mer index over
these but, as of this writing, only through a web dashboard/email-results
workflow with no documented REST API -- so it is not wrapped here as an
automated call. What *is* scriptable is the verification step once you
already have candidate accessions (from Branchwater or STAT): download that
accession's unitigs/contigs from the public S3 bucket and BLAST your query
against just that file, which `logan_blaster`
(https://github.com/pierrepeterlongo/logan_blaster) automates.

This module builds the S3 URLs and shells out to `logan_blaster` for that
local confirmation step; it does not submit anything over the network.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from organism_hunter.config import (
    LOGAN_BLASTER_BIN,
    LOGAN_S3_CONTIGS,
    LOGAN_S3_UNITIGS,
    LOGAN_SEARCH_DASHBOARD,
)


def unitigs_url(accession: str) -> str:
    return f"{LOGAN_S3_UNITIGS}/{accession}/{accession}.unitigs.fa.zst"


def contigs_url(accession: str) -> str:
    return f"{LOGAN_S3_CONTIGS}/{accession}/{accession}.contigs.fa.zst"


def manual_search_instructions(query_fasta: str | Path) -> str:
    """Logan-Search has no REST API; point the user at the dashboard for a first pass."""
    return (
        f"Logan-Search is web-only: upload {query_fasta} (FASTA, <=2.5kb) at "
        f"{LOGAN_SEARCH_DASHBOARD} to get a ranked list of SRA accessions containing "
        "your query sequence's k-mers. Feed the resulting accessions into "
        "logan.verify_hits() here for local BLAST confirmation."
    )


def verify_hits(
    accessions: list[str],
    query_fasta: str | Path,
    use_contigs: bool = False,
    out_dir: str | Path = "logan_verify",
) -> Path:
    """Run logan_blaster to BLAST `query_fasta` against each accession's Logan assembly.

    Returns the output directory containing per-accession BLAST results.
    """
    if shutil.which(LOGAN_BLASTER_BIN) is None:
        raise RuntimeError(
            f"'{LOGAN_BLASTER_BIN}' not found on PATH. Install from "
            "https://github.com/pierrepeterlongo/logan_blaster."
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    acc_file = out_dir / "accessions.txt"
    acc_file.write_text("\n".join(accessions) + "\n")

    cmd = [
        LOGAN_BLASTER_BIN,
        "--query",
        str(query_fasta),
        "--accessions",
        str(acc_file),
        "--out",
        str(out_dir),
    ]
    if use_contigs:
        cmd.append("--contigs")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"logan_blaster failed: {result.stderr}")
    return out_dir
