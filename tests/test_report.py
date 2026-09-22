from organism_hunter.models import GbifOccurrence, OrganismReport, SraHit
from organism_hunter.report import _parse_lat_lon, combined_geojson


def test_parse_lat_lon_insdc_format():
    assert _parse_lat_lon("38.98 N 76.93 W") == (38.98, -76.93)
    assert _parse_lat_lon("38.98 S 76.93 E") == (-38.98, 76.93)


def test_parse_lat_lon_plain_decimal():
    assert _parse_lat_lon("38.98 -76.93") == (38.98, -76.93)


def test_parse_lat_lon_branchwater_bracket_format():
    """Real format seen from branchwater-client --full: a JSON array as a string."""
    assert _parse_lat_lon("[37.4335,-122.1754]") == (37.4335, -122.1754)


def test_parse_lat_lon_invalid_returns_none():
    assert _parse_lat_lon(None) is None
    assert _parse_lat_lon("garbage") is None


def test_combined_geojson_tags_kind_and_skips_ungeolocated_hits():
    report = OrganismReport(
        query="Amanita muscaria",
        occurrences=[
            GbifOccurrence(1, "A. muscaria", 37.7, -122.4, "US", "2024", "HUMAN_OBSERVATION", "inst", "cat", "ds"),
        ],
        sra_hits=[
            SraHit(accession="SRR1", source="branchwater", score=0.5, lat_lon="38.98 N 76.93 W"),
            SraHit(accession="SRR2", source="stat", kmer_count=100, lat_lon=None),
        ],
    )
    geo = combined_geojson(report)
    kinds = [f["properties"]["kind"] for f in geo["features"]]
    assert kinds.count("gbif_occurrence") == 1
    assert kinds.count("sra_hit") == 1  # SRR2 skipped, no coordinates
