import responses

from organism_hunter import gbif
from organism_hunter.config import GBIF_API


@responses.activate
def test_match_taxon():
    responses.add(
        responses.GET,
        f"{GBIF_API}/species/match",
        json={
            "usageKey": 8168319,
            "scientificName": "Amanita muscaria (L.) Lam.",
            "canonicalName": "Amanita muscaria",
            "rank": "SPECIES",
            "status": "ACCEPTED",
            "confidence": 97,
            "matchType": "EXACT",
            "kingdom": "Fungi",
        },
        status=200,
    )
    taxon = gbif.match_taxon("Amanita muscaria")
    assert taxon.usage_key == 8168319
    assert taxon.canonical_name == "Amanita muscaria"
    assert taxon.kingdom == "Fungi"


@responses.activate
def test_match_taxon_no_match_raises():
    responses.add(responses.GET, f"{GBIF_API}/species/match", json={"confidence": 0}, status=200)
    try:
        gbif.match_taxon("not a real organism")
        assert False, "expected ValueError"
    except ValueError:
        pass


@responses.activate
def test_search_occurrences_single_page():
    responses.add(
        responses.GET,
        f"{GBIF_API}/occurrence/search",
        json={
            "count": 1,
            "endOfRecords": True,
            "results": [
                {
                    "key": 123,
                    "scientificName": "Amanita muscaria",
                    "decimalLatitude": 37.7,
                    "decimalLongitude": -122.4,
                    "country": "United States of America",
                    "eventDate": "2024-01-01",
                    "basisOfRecord": "HUMAN_OBSERVATION",
                    "institutionCode": "iNaturalist",
                    "catalogNumber": "abc",
                    "datasetKey": "ds1",
                }
            ],
        },
        status=200,
    )
    records, total = gbif.search_occurrences(8168319, max_records=10)
    assert total == 1
    assert len(records) == 1
    assert records[0].gbif_key == 123


def test_occurrences_to_geojson_skips_missing_coords():
    from organism_hunter.models import GbifOccurrence

    recs = [
        GbifOccurrence(1, "A", 1.0, 2.0, "US", "2024", "HUMAN_OBSERVATION", "inst", "cat", "ds"),
        GbifOccurrence(2, "A", None, None, "US", "2024", "HUMAN_OBSERVATION", "inst", "cat", "ds"),
    ]
    geo = gbif.occurrences_to_geojson(recs)
    assert len(geo["features"]) == 1
    assert geo["features"][0]["properties"]["gbifKey"] == 1
