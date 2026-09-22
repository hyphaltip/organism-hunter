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
local confirmation step.

`logan_blaster` is bioconda-only (not on PyPI, and it drives BLAST,
back_to_sequences, count_tig_coverage and jq), so it cannot live in the same
pip/uv environment as this package:

    mamba create -n logan_blaster -c conda-forge -c bioconda logan_blaster

Either activate that env, or leave it alone and point LOGAN_BLASTER_BIN at
`~/miniconda3/envs/logan_blaster/bin/logan_blaster`. Pointing at the binary is
not by itself sufficient -- logan_blaster shells out to its siblings
(back_to_sequences, blastn, count_logan_tig_coverage, jq) by bare name and
fails with "'back_to_sequences' could not be found" if they aren't on PATH --
so when given an explicit path, this module prepends that binary's directory
to PATH for the subprocess, which makes the unactivated case work.

Note it downloads each accession's assembly from S3 as it goes, so it is the
one part of this pipeline that moves real data: budget disk and time roughly
per accession, and use `limit` when spot-checking a long hit list.
"""

from __future__ import annotations

import csv
import os
import re
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
    accessions: list[str] | None = None,
    query_fasta: str | Path | None = None,
    use_unitigs: bool = False,
    out_dir: str | Path = "logan_verify",
    session: str | None = None,
    kmer_size: int | None = None,
    limit: int | None = None,
    accessions_file: str | Path | None = None,
    delete_intermediate: bool = False,
) -> Path:
    """Run logan_blaster to BLAST `query_fasta` against each accession's Logan assembly.

    Input modes, matching the tool itself (verified against the installed
    binary's --help, which is ahead of the project's GitHub README):
      - `accessions_file` + `query_fasta`: a .txt of one accession per line, or
        a .csv whose first column is the accession and whose first line is a
        header -- so a branchwater-search CSV can be passed straight through.
      - `accessions` (list) + `query_fasta`: written out to accessions.txt.
      - `session`: a Logan-Search kmviz id, which carries its own query/accessions.

    Defaults to contigs; `use_unitigs` passes -u (more sensitive, since unitigs
    preserve variation that contig assembly collapses).

    Returns the output directory.
    """
    # Validate arguments before checking for the tool, so a usage error doesn't
    # surface as a misleading "not installed" message.
    has_accessions = accessions_file is not None or bool(accessions)
    if not session and not (has_accessions and query_fasta):
        raise ValueError(
            "Provide either session=..., or a query_fasta plus accessions/accessions_file."
        )
    if shutil.which(LOGAN_BLASTER_BIN) is None:
        raise RuntimeError(
            f"'{LOGAN_BLASTER_BIN}' not found on PATH. Install with "
            "`mamba create -n logan_blaster -c conda-forge -c bioconda logan_blaster`, "
            "then either activate that env or set LOGAN_BLASTER_BIN to the binary's "
            "full path (it is not on PyPI, so pip/uv cannot install it)."
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [LOGAN_BLASTER_BIN, "-o", str(Path(out_dir).resolve())]
    if session:
        cmd += ["-s", session]
    else:
        if accessions_file is not None:
            acc_path = Path(accessions_file).resolve()
        else:
            acc_path = (out_dir / "accessions.txt").resolve()
            acc_path.write_text("\n".join(accessions) + "\n")
        cmd += ["-a", str(acc_path), "-q", str(Path(query_fasta).resolve())]
    if use_unitigs:
        cmd.append("-u")
    if delete_intermediate:
        cmd.append("-d")
    if kmer_size is not None:
        cmd += ["-k", str(kmer_size)]
    if limit is not None:
        cmd += ["-l", str(limit)]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=_env_with_sibling_tools())
    if result.returncode != 0:
        raise RuntimeError(f"logan_blaster failed: {result.stderr or result.stdout}")
    return out_dir


ACCESSION_RE = re.compile(r"^[SED]R[RXZ]\d+$", re.IGNORECASE)

#: Placeholders that legitimately appear in upstream output for "no value"
#: (Branchwater emits rows that are entirely "NP"). Skipped, not an error.
_SENTINELS = {"np", "null", "na", "n/a", "none", "-", ""}


def read_accessions(path: str | Path) -> list[str]:
    """Read SRA accessions from a .txt (one per line) or .csv (first column).

    logan_blaster nominally accepts a .csv directly, but its parser does not
    actually split on commas -- handed a branchwater-search CSV it treats each
    whole line as an accession and every lookup fails. So the first column is
    extracted here instead, with a header row skipped when the first cell is
    not accession-shaped.

    Sentinel placeholders ("NP", "null", ...) are dropped silently; anything
    else that isn't accession-shaped raises, since that usually means the wrong
    column or whole CSV lines are being passed through.
    """
    path = Path(path)
    rows: list[str] = []
    if path.suffix.lower() == ".csv":
        with open(path, newline="") as f:
            for row in csv.reader(f):
                if row and row[0].strip():
                    rows.append(row[0].strip())
    else:
        with open(path) as f:
            rows = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if rows and not ACCESSION_RE.match(rows[0]):
        rows = rows[1:]  # header line
    rows = [r for r in rows if r.lower() not in _SENTINELS]
    bad = [r for r in rows if not ACCESSION_RE.match(r)]
    if bad:
        raise ValueError(
            f"{len(bad)} entries in {path} are not SRA run accessions, e.g. {bad[:3]}. "
            "Expected a .txt of one accession per line or a .csv whose first column "
            "holds accessions."
        )
    return rows


def _env_with_sibling_tools() -> dict[str, str]:
    """Ensure logan_blaster's helper binaries are findable.

    It invokes back_to_sequences/blastn/count_logan_tig_coverage/jq by bare
    name, so when LOGAN_BLASTER_BIN points into an unactivated conda env we put
    that env's bin directory at the front of PATH.
    """
    env = dict(os.environ)
    resolved = shutil.which(LOGAN_BLASTER_BIN)
    if resolved:
        bin_dir = str(Path(resolved).resolve().parent)
        if bin_dir not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env
