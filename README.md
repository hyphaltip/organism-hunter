# organism-hunter

Cross-reference **GBIF** specimen/observation records for an organism with
**sequence-level detections** of that organism buried in public SRA
metagenomes/metatranscriptomes it was never labeled as containing.

Two questions, one tool:
1. Where has this organism been physically **collected or observed**? (GBIF)
2. Where has its **DNA turned up** in someone else's sequencing run? (SRA, via
   k-mer/sketch search, independent of what the submitter said the run was)

## Backends

| Backend | What it does | Access |
|---|---|---|
| [GBIF API](https://www.gbif.org/developer/summary) | Specimen/observation occurrence records | Public REST, no auth |
| [Branchwater](https://branchwater.sourmash.bio) | Sourmash containment search of your signature against ~1.1M public SRA metagenomes | `branchwater-client` CLI, no auth |
| [NCBI STAT](https://www.ncbi.nlm.nih.gov/sra/docs/sra-cloud-based-taxonomy-analysis-table/) | k-mer taxonomy hits across *all* SRA runs, via BigQuery public tables | Your own GCP project (billed, 1TB/mo free) |
| [Logan](https://github.com/IndexThePlanet/Logan) | Assembled unitigs/contigs for ~26M SRA accessions, for local BLAST-style confirmation of candidate hits | Public S3 (`s3://logan-pub`); [Logan-Search](https://logan-search.org) dashboard is web-only, no REST API |

Branchwater and STAT answer "which SRA runs might contain this organism,
fast, at scale." Logan answers "let me actually align my query against that
specific run's assembly to confirm it," once you have a short candidate list.

## Install

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"          # core + tests
uv pip install -e ".[bigquery]"     # + STAT/BigQuery support
uv pip install -e ".[dashboard]"    # + Streamlit UI
```

```bash
uv pip install -e ".[signatures]"   # + sourmash, for building query signatures
```

`branchwater-client` and `logan_blaster` are Rust/compiled binaries, not pip
packages:
- **branchwater-client**: download the archive for your platform from the
  [releases page](https://github.com/sourmash-bio/branchwater/releases)
  (e.g. `branchwater-client-aarch64-apple-darwin.tar.xz` for Apple Silicon),
  `tar xJf` it, and put the extracted `branchwater-client` binary on PATH. On
  macOS, Gatekeeper quarantines downloaded binaries; if it refuses to run,
  clear that with `xattr -d com.apple.quarantine /path/to/branchwater-client`.
- **logan_blaster**: see [pierrepeterlongo/logan_blaster](https://github.com/pierrepeterlongo/logan_blaster)

For STAT/BigQuery:

```bash
gcloud auth application-default login          # once; writes ADC credentials
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
gcloud services enable bigquery.googleapis.com --project=YOUR_PROJECT_ID
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID    # add to ~/.zshrc to persist
```

Verify the setup without spending anything (dry runs are free):

```bash
organism-hunter stat-search "Saccharomyces cerevisiae" --estimate-only
```

`GOOGLE_CLOUD_PROJECT` is read by `organism_hunter/config.py`; every STAT
command also accepts `--project`/`--stat-project` if you'd rather not export
it. For higher NCBI E-utilities rate limits, optionally set `NCBI_API_KEY` and
`NCBI_EMAIL`.

## CLI usage

```bash
# 1. What GBIF specimen/observation records exist?
organism-hunter gbif "Amanita muscaria" --geojson occurrences.geojson

# 2. Get something to search SRA with: either your own FASTA, a barcode
#    pulled from NCBI, or a reference genome.
organism-hunter fetch-barcode "Amanita muscaria" --gene ITS -o its.fasta
organism-hunter build-signature its.fasta -o its.sig

# 3. Search SRA metagenomes for that signature.
organism-hunter branchwater-search its.sig -o branchwater_hits.csv

# 4. Or search all of SRA by k-mer taxonomy (needs GOOGLE_CLOUD_PROJECT set).
organism-hunter stat-search "Amanita muscaria" -o stat_hits.csv

# 5. Confirm a candidate hit by aligning against its actual Logan assembly.
organism-hunter logan-verify branchwater_hits_accessions.txt its.fasta

# Or do 1+3+4 together and get one combined report + map:
organism-hunter report "Amanita muscaria" --signature its.sig \
    --stat-project my-gcp-project -o report.json --geojson combined.geojson
```

## Dashboard

```bash
streamlit run dashboard/app.py
```

Search box for an organism name, optional FASTA/signature upload, and a map
showing GBIF occurrences (blue) alongside geolocated SRA sequence hits (red).

## Library usage

```python
from organism_hunter import gbif, report

taxon = gbif.match_taxon("Amanita muscaria")
occurrences, total = gbif.search_occurrences(taxon.usage_key, max_records=500)

rep = report.build_report("Amanita muscaria", signature_path="its.sig",
                           stat_project="my-gcp-project")
report.write_report(rep, "report.json")
```

## Verified smoke test

*Saccharomyces cerevisiae* is a good end-to-end smoke test: a tiny (~12 Mb)
genome that sketches in seconds, and a near-ubiquitous low-level contaminant
of public metagenomes, so a real run should never come back with zero SRA
hits. This exact sequence was run live against production GBIF, NCBI, and
Branchwater servers while building this tool:

```bash
organism-hunter fetch-genome "Saccharomyces cerevisiae" -o scer.fasta   # 12.3 MB, 17 sequences
organism-hunter build-signature scer.fasta -o scer.sig --name "Saccharomyces cerevisiae S288C"
organism-hunter branchwater-search scer.sig -o hits.csv                # 5,355 hits above containment 0.1
organism-hunter report "Saccharomyces cerevisiae" --signature scer.sig \
    --no-stat --max-occurrences 50 -o report.json --geojson combined.geojson
```

`combined.geojson` came back with 7 GBIF collection points and 2,021
geolocated SRA hits -- e.g. an anaerobic digester metagenome from Greece never
labeled as containing yeast. That's the actual payoff of this tool: sequence
evidence of an organism's presence somewhere GBIF has no record of it.

STAT/BigQuery wasn't exercised in this run (no GCP project configured); it's
architecturally identical to Branchwater above once `GOOGLE_CLOUD_PROJECT` is set.

## Notes on the SRA backends

- **STAT** table/column names were verified directly against the live BigQuery
  tables (not just NCBI's
  [blog post](https://ncbiinsights.ncbi.nlm.nih.gov/2020/04/27/sra-cloud-taxtables/) /
  [docs page](https://www.ncbi.nlm.nih.gov/sra/docs/sra-cloud-based-taxonomy-analysis-table/),
  which omit several details):
  - the taxonomy table's scientific-name column is **`sci_name`**, not `name`;
    `names` is a repeated record of synonyms/common names (matched too).
  - `sra.metadata` has **`assay_type`**, not `librarystrategy`, and has **no
    lat/lon column at all** — STAT geography is country-level only, so STAT
    hits do not appear as points on the combined map (Branchwater hits do,
    because its own metadata server returns coordinates).
  - `sra.metadata`'s harvested-BioSample columns drift, so
    `enrich_with_metadata` still checks `INFORMATION_SCHEMA.COLUMNS` first.

### ⚠️ STAT query costs (read before enabling)

`sra_tax_analysis_tool.tax_analysis` is **1.55 TB across 17.6 billion rows**
and is neither partitioned nor clustered — so `WHERE tax_id = ...` does *not*
reduce bytes scanned, and neither does `LIMIT`. Measured dry-run costs for one
taxon lookup:

| Query | Scanned |
|---|---|
| `SELECT acc` | 365 GB |
| `SELECT acc, total_count` (what this tool uses) | 506 GB |
| `SELECT acc, tax_id, total_count, self_count` | 646 GB |
| `+ rank, name` | 1.13 TB |

BigQuery's free tier is 1 TB/month, so **a single careless query can consume
it** (~$6.25/TB after). Guards built in as a result:

- STAT is **opt-in**: `report --with-stat`, and off by default in the dashboard.
- `stat-search` prints the exact cost from a **free dry run** and asks for
  confirmation; `--estimate-only` shows cost and exits, `--yes` skips the prompt.
- Every job sets `maximum_bytes_billed` (default 1 TiB, override with
  `ORGANISM_HUNTER_MAX_BYTES_BILLED`) so a surprise query **fails instead of
  billing**.
- Queries select the minimum columns needed; the `taxonomy` lookup is cheap
  (~120 MB) since that table is only 0.4 GB.
- **Branchwater** has no documented plain-HTTP contract for scripted search;
  this project shells out to the official `branchwater-client` binary and
  parses its CSV output. Verified live against v0.6.3 and `api.branchwater.sourmash.bio`:
  - it wants a plain `.sig` (uncompressed JSON); a `.sig.zip` container fails
    to parse client-side, hence `signatures.build_signature`'s default output.
  - there is no `--threshold` flag in this release, so `branchwater.search()`
    filters by containment/cANI client-side after the full result comes back.
  - `--full` and non-`--full` output different CSV headers (`acc` vs.
    `"SRA accession"`; `assay_type` instead of a strategy/source split; missing
    fields render as the literal string `"null"`; `lat_lon` comes back as a
    `"[lat,lon]"` string) — all handled in `_parse_csv`/`_parse_lat_lon`.
  If a future release changes any of this, update
  `organism_hunter/branchwater.py::_parse_csv`.
- **Logan-Search** (the hosted k-mer index/dashboard) has no REST API as of
  this writing, so it isn't called automatically. `organism_hunter.logan`
  covers the part that *is* scriptable: BLASTing a query against a known
  accession's public Logan assembly for confirmation.

## Tests

```bash
pytest
```

Tests cover GBIF (mocked HTTP) and the report/geojson logic. Branchwater,
STAT, and Logan modules depend on external binaries/credentials and are
exercised via unit tests on their pure-Python bits only (CSV parsing, column
detection, URL building) rather than live network/BigQuery calls.
