"""Tests for the Logan verification wrapper.

These cover the pure-Python parts only -- `verify_hits` itself shells out to
logan_blaster, which downloads assemblies from S3.
"""

import pytest

from organism_hunter import logan


def test_read_accessions_from_txt(tmp_path):
    p = tmp_path / "accs.txt"
    p.write_text("SRR1263009\nERR11474687\n\n# a comment\nDRR000001\n")
    assert logan.read_accessions(p) == ["SRR1263009", "ERR11474687", "DRR000001"]


def test_read_accessions_from_branchwater_csv(tmp_path):
    """logan_blaster's own CSV mode doesn't split on commas, so we do it."""
    p = tmp_path / "hits.csv"
    p.write_text(
        "accession,source,score,kmer_count,organism,geo_loc_name,collection_date\n"
        "SRR15417138,branchwater,0.41,,human gut metagenome,USA,\n"
        "ERR11474687,branchwater,0.11,,human gut metagenome,United Kingdom,\n"
    )
    assert logan.read_accessions(p) == ["SRR15417138", "ERR11474687"]


def test_read_accessions_skips_NP_sentinel_rows(tmp_path):
    """Branchwater emits rows that are entirely "NP"; skip them, don't fail."""
    p = tmp_path / "hits.csv"
    p.write_text(
        "accession,organism\n"
        "SRR15417138,human gut metagenome\n"
        "NP,NP\n"
        "NP,NP\n"
    )
    assert logan.read_accessions(p) == ["SRR15417138"]


def test_read_accessions_rejects_non_accessions(tmp_path):
    """Guards against silently feeding whole CSV lines to logan_blaster."""
    p = tmp_path / "bad.txt"
    p.write_text("SRR15417138,branchwater,0.41,human gut metagenome\nnot_an_accession\n")
    with pytest.raises(ValueError, match="not SRA run accessions"):
        logan.read_accessions(p)


def test_verify_hits_requires_query_or_session():
    with pytest.raises(ValueError, match="session"):
        logan.verify_hits(accessions=["SRR1"], query_fasta=None)


def test_s3_url_builders():
    assert logan.unitigs_url("SRR1263009").endswith("SRR1263009/SRR1263009.unitigs.fa.zst")
    assert logan.contigs_url("SRR1263009").endswith("SRR1263009/SRR1263009.contigs.fa.zst")
