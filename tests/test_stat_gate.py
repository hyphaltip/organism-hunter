"""The STAT/BigQuery backend is the only metered one, so it stays off unless
explicitly enabled. These tests pin that gate shut -- they must never reach
BigQuery, and they assert the failure happens *before* any client is built.
"""

import pytest

from organism_hunter import config, sra_stat


def test_stat_disabled_by_default_blocks_client_creation(monkeypatch):
    monkeypatch.setattr(config, "STAT_ENABLED", False)
    with pytest.raises(RuntimeError, match="disabled"):
        sra_stat._get_client("some-project")


def test_disabled_gate_blocks_every_query_entry_point(monkeypatch):
    """Including the free dry-run path: even the taxonomy lookup is billed."""
    monkeypatch.setattr(config, "STAT_ENABLED", False)
    for call in (
        lambda: sra_stat.find_tax_id("Saccharomyces cerevisiae"),
        lambda: sra_stat.estimate_hits_bytes(4932),
        lambda: sra_stat.hits_for_tax_id(4932),
        lambda: sra_stat.enrich_with_metadata([sra_stat.SraHit(accession="SRR1", source="stat")]),
    ):
        with pytest.raises(RuntimeError, match="disabled"):
            call()


def test_gate_is_read_at_call_time_not_import_time(monkeypatch):
    """Flipping the switch must take effect without reimporting the module."""
    monkeypatch.setattr(config, "STAT_ENABLED", True)
    # Now the gate passes, so it fails later -- on credentials/project, not the switch.
    with pytest.raises(RuntimeError) as excinfo:
        sra_stat._get_client(None)
    assert "disabled" not in str(excinfo.value)


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("YES", True),
                                            ("on", True), ("0", False), ("", False), ("no", False)])
def test_env_switch_parsing(value, expected):
    parsed = value.strip().lower() in ("1", "true", "yes", "on")
    assert parsed is expected
