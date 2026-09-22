"""Shared data structures passed between modules and into reports."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaxonMatch:
    query: str
    usage_key: int
    scientific_name: str
    canonical_name: str
    rank: str
    status: str
    confidence: int
    match_type: str
    kingdom: str | None = None
    phylum: str | None = None
    taxon_class: str | None = None
    order: str | None = None
    family: str | None = None
    genus: str | None = None


@dataclass
class GbifOccurrence:
    gbif_key: int
    scientific_name: str
    decimal_latitude: float | None
    decimal_longitude: float | None
    country: str | None
    event_date: str | None
    basis_of_record: str | None
    institution_code: str | None
    catalog_number: str | None
    dataset_key: str | None
    associated_sequences: str | None = None


@dataclass
class SraHit:
    accession: str
    source: str  # "branchwater" | "stat"
    score: float | None = None  # containment / cANI for branchwater
    kmer_count: int | None = None  # total_count for STAT
    tax_id: int | None = None
    organism: str | None = None
    bioproject: str | None = None
    biosample: str | None = None
    library_strategy: str | None = None
    library_source: str | None = None
    geo_loc_name: str | None = None
    lat_lon: str | None = None
    collection_date: str | None = None


@dataclass
class OrganismReport:
    query: str
    taxon: TaxonMatch | None = None
    occurrences: list[GbifOccurrence] = field(default_factory=list)
    occurrence_count_total: int = 0
    sra_hits: list[SraHit] = field(default_factory=list)
    signature_path: str | None = None
    notes: list[str] = field(default_factory=list)
