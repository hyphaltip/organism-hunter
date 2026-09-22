"""organism-hunter: cross-reference GBIF specimen records with SRA sequence hits."""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

from organism_hunter import branchwater as branchwater_mod
from organism_hunter import gbif, logan, ncbi_refs, signatures
from organism_hunter import report as report_mod

console = Console()


@click.group()
def main():
    """Mine SRA sequence data and GBIF specimen records for a given organism."""


@main.command("gbif")
@click.argument("name")
@click.option("--max-records", default=300, show_default=True)
@click.option("--geojson", "geojson_out", type=click.Path(), help="Write occurrences as GeoJSON.")
@click.option("--csv", "csv_out", type=click.Path(), help="Write occurrences as CSV.")
def gbif_cmd(name: str, max_records: int, geojson_out: str | None, csv_out: str | None):
    """Look up specimen/observation records for NAME in GBIF."""
    taxon = gbif.match_taxon(name)
    console.print(f"Matched [bold]{taxon.scientific_name}[/bold] (key={taxon.usage_key}, "
                  f"confidence={taxon.confidence}, rank={taxon.rank})")
    occs, total = gbif.search_occurrences(taxon.usage_key, max_records=max_records)
    console.print(f"{total} total occurrences in GBIF; fetched {len(occs)}.")

    if geojson_out:
        with open(geojson_out, "w") as f:
            json.dump(gbif.occurrences_to_geojson(occs), f, indent=2)
        console.print(f"Wrote {geojson_out}")

    if csv_out:
        import csv as csv_module

        with open(csv_out, "w", newline="") as f:
            writer = csv_module.writer(f)
            writer.writerow(["key", "scientificName", "lat", "lon", "country", "eventDate", "basisOfRecord"])
            for o in occs:
                writer.writerow(
                    [o.gbif_key, o.scientific_name, o.decimal_latitude, o.decimal_longitude,
                     o.country, o.event_date, o.basis_of_record]
                )
        console.print(f"Wrote {csv_out}")

    if not geojson_out and not csv_out:
        table = Table(show_header=True)
        for col in ["key", "scientificName", "country", "eventDate", "basisOfRecord"]:
            table.add_column(col)
        for o in occs[:20]:
            table.add_row(str(o.gbif_key), o.scientific_name, o.country or "", o.event_date or "", o.basis_of_record or "")
        console.print(table)


@main.command("fetch-barcode")
@click.argument("name")
@click.option("--gene", default="COI", show_default=True)
@click.option("--max-records", default=20, show_default=True)
@click.option("-o", "--output", type=click.Path(), required=True)
def fetch_barcode_cmd(name: str, gene: str, max_records: int, output: str):
    """Fetch barcode/marker sequences (e.g. COI, ITS, 16S) for NAME from NCBI nuccore."""
    path = ncbi_refs.fetch_barcode_sequences(name, gene=gene, max_records=max_records, out_path=output)
    console.print(f"Wrote {path}")


@main.command("fetch-genome")
@click.argument("name_or_taxid")
@click.option("-o", "--output", type=click.Path(), required=True)
def fetch_genome_cmd(name_or_taxid: str, output: str):
    """Fetch a reference genome assembly for NAME_OR_TAXID via NCBI Datasets."""
    path = ncbi_refs.fetch_reference_genome(name_or_taxid, out_path=output)
    console.print(f"Wrote {path}")


@main.command("build-signature")
@click.argument("fasta_path", type=click.Path(exists=True))
@click.option("-o", "--output", type=click.Path())
@click.option("-k", default=21, show_default=True)
@click.option("--scaled", default=1000, show_default=True)
@click.option("--name", "sig_name", default=None)
def build_signature_cmd(fasta_path: str, output: str | None, k: int, scaled: int, sig_name: str | None):
    """Build a sourmash signature from FASTA_PATH for use as a Branchwater query."""
    path = signatures.build_signature(fasta_path, out_path=output, k=k, scaled=scaled, name=sig_name)
    console.print(f"Wrote {path}")


@main.command("branchwater-search")
@click.argument("signature_path", type=click.Path(exists=True))
@click.option("--threshold", default=0.1, show_default=True)
@click.option("-o", "--output", type=click.Path(), help="Write hits as CSV.")
def branchwater_search_cmd(signature_path: str, threshold: float, output: str | None):
    """Search public SRA metagenomes for SIGNATURE_PATH via Branchwater."""
    hits = branchwater_mod.search(signature_path, threshold=threshold)
    console.print(f"{len(hits)} hits.")
    _print_or_write_hits(hits, output)


@main.command("stat-search")
@click.argument("name")
@click.option("--project", default=None, help="GCP billing project (defaults to $GOOGLE_CLOUD_PROJECT).")
@click.option("--limit", default=500, show_default=True)
@click.option("-o", "--output", type=click.Path(), help="Write hits as CSV.")
@click.option(
    "--estimate-only",
    is_flag=True,
    help="Show the tax_analysis cost via a free dry run and exit. (The taxonomy "
    "name->taxid lookup it needs first is a real query, but only ~120 MB.)",
)
@click.option("--yes", is_flag=True, help="Skip the cost confirmation prompt.")
def stat_search_cmd(name, project, limit, output, estimate_only, yes):
    """Search NCBI STAT k-mer taxonomy tables (BigQuery) for NAME's tax_id.

    The tax_analysis table is 1.55 TB / 17.6B rows and is not partitioned, so
    this scans ~500 GB no matter how small --limit is. BigQuery's free tier is
    1 TB/month, so the cost is shown and confirmed before anything is billed.
    """
    from organism_hunter import sra_stat

    try:
        tax_id = sra_stat.find_tax_id(name, project=project)
        if tax_id is None:
            console.print(f"No STAT tax_id found for {name!r}.")
            return
        console.print(f"tax_id={tax_id}")

        est = sra_stat.estimate_hits_bytes(tax_id, limit=limit, project=project)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    gb = est / 1e9
    console.print(
        f"[yellow]This query will scan {gb:,.1f} GB[/yellow] "
        f"({gb / 1000:.2f} TB, ~{gb / 10:.0f}% of a 1 TB free tier; "
        f"~${max(0.0, (est / 1024**4) * 6.25):,.2f} if the free tier is already used)."
    )
    if estimate_only:
        return
    if not yes and not click.confirm("Run it?", default=False):
        console.print("Aborted; nothing was billed.")
        return

    hits = sra_stat.hits_for_tax_id(tax_id, limit=limit, project=project)
    hits = sra_stat.enrich_with_metadata(hits, project=project)
    console.print(f"{len(hits)} hits.")
    _print_or_write_hits(hits, output)


@main.command("logan-verify")
@click.argument("accessions_file", type=click.Path(exists=True))
@click.argument("query_fasta", type=click.Path(exists=True))
@click.option("--unitigs", "use_unitigs", is_flag=True, help="Search unitigs instead of contigs (more sensitive; contigs are the default).")
@click.option("--limit", type=int, default=None, help="Only process the first N accessions (each one is downloaded from S3).")
@click.option("-k", "--kmer-size", type=int, default=None, help="K-mer size for recruitment (logan_blaster default: 17).")
@click.option("-o", "--out-dir", default="logan_verify", show_default=True)
def logan_verify_cmd(accessions_file, query_fasta, use_unitigs, limit, kmer_size, out_dir):
    """BLAST QUERY_FASTA against each accession's Logan assembly (local verification).

    ACCESSIONS_FILE is either one SRA accession per line (.txt), or a .csv whose
    first column holds accessions -- so a branchwater-search CSV works. Each
    accession's assembly is downloaded from the public Logan S3 bucket, so use
    --limit when spot-checking a long list.
    """
    try:
        accessions = logan.read_accessions(accessions_file)
        console.print(f"{len(accessions)} accessions; running {min(limit, len(accessions)) if limit else len(accessions)}.")
        out = logan.verify_hits(
            accessions=accessions,
            query_fasta=query_fasta,
            use_unitigs=use_unitigs,
            out_dir=out_dir,
            kmer_size=kmer_size,
            limit=limit,
        )
    except (RuntimeError, ValueError) as e:
        raise click.ClickException(str(e)) from e
    console.print(f"Results in {out}")


@main.command("report")
@click.argument("name")
@click.option("--signature", "signature_path", type=click.Path(exists=True), help="Pre-built sourmash signature for Branchwater search.")
@click.option("--max-occurrences", default=300, show_default=True)
@click.option("--threshold", default=0.1, show_default=True, help="Branchwater containment threshold.")
@click.option("--stat-project", default=None, help="GCP billing project for STAT/BigQuery.")
@click.option("--no-branchwater", is_flag=True)
@click.option("--with-stat", is_flag=True, help="Also run the STAT/BigQuery search (scans ~500 GB, billed to your GCP project).")
@click.option("-o", "--output", type=click.Path(), default="report.json", show_default=True)
@click.option("--geojson", "geojson_out", type=click.Path(), help="Also write a combined GeoJSON of GBIF + geolocated SRA hits.")
def report_cmd(name, signature_path, max_occurrences, threshold, stat_project, no_branchwater, with_stat, output, geojson_out):
    """Build a combined GBIF + SRA (Branchwater/STAT) report for NAME.

    STAT is opt-in via --with-stat because each run scans ~500 GB of BigQuery.
    """
    rep = report_mod.build_report(
        name,
        max_occurrences=max_occurrences,
        signature_path=signature_path,
        branchwater_threshold=threshold,
        stat_project=stat_project,
        run_branchwater=not no_branchwater,
        run_stat=with_stat,
    )
    report_mod.write_report(rep, output)
    console.print(f"Wrote {output}")
    console.print(f"GBIF: {rep.occurrence_count_total} total occurrences ({len(rep.occurrences)} fetched).")
    console.print(f"SRA hits: {len(rep.sra_hits)}.")
    for note in rep.notes:
        console.print(f"[yellow]note:[/yellow] {note}")

    if geojson_out:
        with open(geojson_out, "w") as f:
            json.dump(report_mod.combined_geojson(rep), f, indent=2)
        console.print(f"Wrote {geojson_out}")


def _print_or_write_hits(hits, output: str | None):
    if output:
        import csv as csv_module

        with open(output, "w", newline="") as f:
            writer = csv_module.writer(f)
            writer.writerow(["accession", "source", "score", "kmer_count", "organism", "geo_loc_name", "collection_date"])
            for h in hits:
                writer.writerow([h.accession, h.source, h.score, h.kmer_count, h.organism, h.geo_loc_name, h.collection_date])
        console.print(f"Wrote {output}")
    else:
        table = Table(show_header=True)
        for col in ["accession", "score", "kmer_count", "organism", "geo_loc_name"]:
            table.add_column(col)
        for h in hits[:20]:
            table.add_row(h.accession, str(h.score or ""), str(h.kmer_count or ""), h.organism or "", h.geo_loc_name or "")
        console.print(table)


if __name__ == "__main__":
    main()
