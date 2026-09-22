"""GBIF specimen/occurrence record lookups.

Wraps the public GBIF REST API (https://api.gbif.org/v1) directly with
`requests` rather than pygbif, so the only dependency is `requests` and the
exact fields returned are explicit and easy to extend.
"""

from __future__ import annotations

import requests

from organism_hunter.config import GBIF_API, HTTP_TIMEOUT
from organism_hunter.models import GbifOccurrence, TaxonMatch


def match_taxon(name: str) -> TaxonMatch:
    """Resolve a free-text name to a GBIF backbone taxon (fuzzy matched)."""
    resp = requests.get(f"{GBIF_API}/species/match", params={"name": name}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    d = resp.json()
    if "usageKey" not in d:
        raise ValueError(f"GBIF could not match a taxon to {name!r}: {d}")
    return TaxonMatch(
        query=name,
        usage_key=d["usageKey"],
        scientific_name=d.get("scientificName", ""),
        canonical_name=d.get("canonicalName", d.get("scientificName", "")),
        rank=d.get("rank", ""),
        status=d.get("status", ""),
        confidence=d.get("confidence", 0),
        match_type=d.get("matchType", ""),
        kingdom=d.get("kingdom"),
        phylum=d.get("phylum"),
        taxon_class=d.get("class"),
        order=d.get("order"),
        family=d.get("family"),
        genus=d.get("genus"),
    )


def _occurrence_page(taxon_key: int, offset: int, limit: int, has_coordinate: bool | None) -> dict:
    params: dict[str, object] = {"taxonKey": taxon_key, "offset": offset, "limit": limit}
    if has_coordinate is not None:
        params["hasCoordinate"] = str(has_coordinate).lower()
    resp = requests.get(f"{GBIF_API}/occurrence/search", params=params, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def search_occurrences(
    taxon_key: int,
    max_records: int = 300,
    has_coordinate: bool | None = None,
    page_size: int = 300,
) -> tuple[list[GbifOccurrence], int]:
    """Page through GBIF occurrence records for a taxon key.

    Returns (records fetched up to max_records, total count reported by GBIF).
    GBIF caps offset+limit at 100,000 for the plain search endpoint; use the
    occurrence download API (not implemented here) for exhaustive bulk pulls.
    """
    page_size = min(page_size, 300)
    records: list[GbifOccurrence] = []
    offset = 0
    total = 0
    while len(records) < max_records:
        limit = min(page_size, max_records - len(records))
        data = _occurrence_page(taxon_key, offset, limit, has_coordinate)
        total = data.get("count", 0)
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            records.append(
                GbifOccurrence(
                    gbif_key=r.get("key"),
                    scientific_name=r.get("scientificName", ""),
                    decimal_latitude=r.get("decimalLatitude"),
                    decimal_longitude=r.get("decimalLongitude"),
                    country=r.get("country"),
                    event_date=r.get("eventDate"),
                    basis_of_record=r.get("basisOfRecord"),
                    institution_code=r.get("institutionCode"),
                    catalog_number=r.get("catalogNumber"),
                    dataset_key=r.get("datasetKey"),
                    associated_sequences=r.get("associatedSequences"),
                )
            )
        offset += limit
        if data.get("endOfRecords", True):
            break
    return records, total


def occurrences_to_geojson(records: list[GbifOccurrence]) -> dict:
    """Build a GeoJSON FeatureCollection from occurrence records that have coordinates."""
    features = []
    for r in records:
        if r.decimal_latitude is None or r.decimal_longitude is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r.decimal_longitude, r.decimal_latitude]},
                "properties": {
                    "gbifKey": r.gbif_key,
                    "scientificName": r.scientific_name,
                    "country": r.country,
                    "eventDate": r.event_date,
                    "basisOfRecord": r.basis_of_record,
                    "institutionCode": r.institution_code,
                    "catalogNumber": r.catalog_number,
                    "datasetKey": r.dataset_key,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
