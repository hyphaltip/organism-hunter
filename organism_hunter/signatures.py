"""Build sourmash signatures ("signature sequences") for use as Branchwater queries.

Shells out to the `sourmash` CLI rather than using its Python API, so this
module has no import-time dependency on sourmash being pip-installed in the
same environment as organism_hunter -- it only needs to be on PATH when a
signature is actually built.

Branchwater's public index (as of this writing) is built at k=21, scaled=1000,
so signatures built here default to matching parameters -- a signature built
at a different k/scaled will simply return no hits, not an error.

Output defaults to a plain `.sig` (uncompressed JSON), not `.sig.zip`:
`branchwater-client --sig` (as of v0.6.3) fails to parse the zip container
("expected value at line 1 column 1", i.e. it tries to JSON-parse zip bytes)
even though sourmash itself reads/writes `.sig.zip` happily.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from organism_hunter.config import SOURMASH_BIN


def build_signature(
    fasta_path: str | Path,
    out_path: str | Path | None = None,
    k: int = 21,
    scaled: int = 1000,
    name: str | None = None,
) -> Path:
    """Run `sourmash sketch dna` on a FASTA file to produce a query signature."""
    if shutil.which(SOURMASH_BIN) is None:
        raise RuntimeError(
            f"'{SOURMASH_BIN}' not found on PATH. Install with `pip install sourmash` "
            "or `conda install -c bioconda sourmash`."
        )
    fasta_path = Path(fasta_path)
    out_path = Path(out_path) if out_path else fasta_path.with_suffix(".sig")

    cmd = [
        SOURMASH_BIN,
        "sketch",
        "dna",
        "-p",
        f"k={k},scaled={scaled}",
        "-o",
        str(out_path),
        str(fasta_path),
    ]
    if name:
        cmd += ["--name", name]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"sourmash sketch failed: {result.stderr}")
    return out_path
