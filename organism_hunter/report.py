"""Orchestrate GBIF + SRA lookups into a single OrganismReport, and export it."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from organism_hunter import branchwater as branchwater_mod
from organism_hunter import gbif
from organism_hunter.models import OrganismReport


def build_report(
    query: str,
    max_occurrences: int = 300,
    signature_path: str | Path | None = None,
    branchwater_threshold: float = 0.1,
    stat_project: str | None = None,
    run_branchwater: bool = True,
    run_stat: bool = True,
) -> OrganismReport:
    """Resolve a name in GBIF, pull occurrences, and (optionally) search SRA.

    STAT and Branchwater are best-effort: a missing GCP project or missing
    branchwater-client binary is recorded as a note rather than raising, so a
    partial report is still produced.
    """
    report = OrganismReport(query=query)

    taxon = gbif.match_taxon(query)
    report.taxon = taxon

    occurrences, total = gbif.search_occurrences(taxon.usage_key, max_records=max_occurrences)
    report.occurrences = occurrences
    report.occurrence_count_total = total

    if signature_path:
        report.signature_path = str(signature_path)

    if run_branchwater:
        if signature_path is None:
            report.notes.append("Branchwater skipped: no signature_path provided.")
        else:
            try:
                hits = branchwater_mod.search(signature_path, threshold=branchwater_threshold)
                report.sra_hits.extend(hits)
            except RuntimeError as e:
                report.notes.append(f"Branchwater skipped: {e}")

    if run_stat:
        try:
            from organism_hunter import sra_stat

            tax_id = sra_stat.find_tax_id(taxon.canonical_name, project=stat_project)
            if tax_id is None:
                report.notes.append(f"STAT skipped: no tax_id found for {taxon.canonical_name!r}.")
            else:
                hits = sra_stat.hits_for_tax_id(tax_id, project=stat_project)
                hits = sra_stat.enrich_with_metadata(hits, project=stat_project)
                report.sra_hits.extend(hits)
        except RuntimeError as e:
            report.notes.append(f"STAT skipped: {e}")

    return report


def report_to_dict(report: OrganismReport) -> dict:
    return dataclasses.asdict(report)


def write_report(report: OrganismReport, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.write_text(json.dumps(report_to_dict(report), indent=2, default=str))
    return out_path


def _parse_lat_lon(lat_lon: str | None) -> tuple[float, float] | None:
    """Parse lat_lon strings in the formats actually seen in the wild:

    - INSDC-style: "38.98 N 76.93 W"
    - Plain decimal: "38.98 -76.93"
    - Branchwater's --full CSV: "[37.4335,-122.1754]" (a JSON array as a string)
    """
    if not lat_lon:
        return None
    lat_lon = lat_lon.strip()
    if lat_lon.startswith("[") and lat_lon.endswith("]"):
        try:
            lat, lon = json.loads(lat_lon)
            return float(lat), float(lon)
        except (ValueError, TypeError):
            return None
    tokens = lat_lon.split()
    try:
        if len(tokens) == 4:
            lat = float(tokens[0]) * (1 if tokens[1].upper() == "N" else -1)
            lon = float(tokens[2]) * (1 if tokens[3].upper() == "E" else -1)
            return lat, lon
        if len(tokens) == 2:
            return float(tokens[0]), float(tokens[1])
    except ValueError:
        return None
    return None


def combined_geojson(report: OrganismReport) -> dict:
    """GBIF specimen points and geolocated SRA sequence-hit points, tagged by kind.

    This is the map that answers the original question directly: where has the
    organism been *collected* (GBIF) versus where has its sequence turned up in
    *someone else's* sample (SRA hit with a geo_loc_name/lat_lon)?
    """
    features = list(gbif.occurrences_to_geojson(report.occurrences)["features"])
    for f in features:
        f["properties"]["kind"] = "gbif_occurrence"

    for hit in report.sra_hits:
        latlon = _parse_lat_lon(hit.lat_lon)
        if latlon is None:
            continue
        lat, lon = latlon
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "kind": "sra_hit",
                    "accession": hit.accession,
                    "source": hit.source,
                    "score": hit.score,
                    "kmer_count": hit.kmer_count,
                    "organism": hit.organism,
                    "geo_loc_name": hit.geo_loc_name,
                    "collection_date": hit.collection_date,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
