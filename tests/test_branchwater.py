"""Regression tests pinned to branchwater-client v0.6.3's real (undocumented) CSV output,
captured live against https://api.branchwater.sourmash.bio during a manual smoke test.
"""

from organism_hunter.branchwater import _parse_csv


def test_parse_csv_plain_output():
    csv_text = (
        "SRA accession,containment,query\n"
        "SRR1263009,0.9997423123174712,scer.sig\n"
        "SRR1262938,0.999656416423295,scer.sig\n"
    )
    hits = _parse_csv(csv_text)
    assert len(hits) == 2
    assert hits[0].accession == "SRR1263009"
    assert hits[0].source == "branchwater"
    assert abs(hits[0].score - 0.9997423123174712) < 1e-9


def test_parse_csv_full_output_with_null_literals_and_bracket_latlon():
    csv_text = (
        "acc,assay_type,bioproject,cANI,collection_date_sam,containment,"
        "geo_loc_name_country_calc,lat_lon,organism\n"
        'SRR15417138,WGS,PRJNA746613,0.96,null,0.41,USA,"[37.4335,-122.1754]",human gut metagenome\n'
        "ERR11474687,WGS,PRJEB62473,0.9,null,0.11,United Kingdom,null,human gut metagenome\n"
    )
    hits = _parse_csv(csv_text)
    assert len(hits) == 2

    a = hits[0]
    assert a.accession == "SRR15417138"
    assert a.score == 0.41
    assert a.bioproject == "PRJNA746613"
    assert a.library_strategy == "WGS"
    assert a.geo_loc_name == "USA"
    assert a.lat_lon == "[37.4335,-122.1754]"
    assert a.collection_date is None  # "null" literal -> None
    assert a.organism == "human gut metagenome"

    b = hits[1]
    assert b.lat_lon is None  # "null" literal -> None
