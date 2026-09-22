"""Streamlit dashboard for organism_hunter.

Run with: streamlit run dashboard/app.py

Lets you look up an organism's GBIF specimen records, optionally build/upload
a sourmash signature, and search SRA (Branchwater + STAT) for sequence-level
detections -- then view both on one map.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from organism_hunter import gbif, signatures
from organism_hunter import report as report_mod

st.set_page_config(page_title="Organism Hunter", layout="wide")
st.title("Organism Hunter")
st.caption(
    "GBIF specimen records vs. sequence-level detections in public SRA metagenomes "
    "(Branchwater sourmash search + NCBI STAT k-mer tables)."
)

with st.sidebar:
    st.header("Query")
    name = st.text_input("Organism name", placeholder="e.g. Amanita muscaria")
    max_occurrences = st.slider("Max GBIF occurrences to fetch", 50, 2000, 300, step=50)

    st.subheader("SRA signature (Branchwater)")
    uploaded_fasta = st.file_uploader("FASTA to build a sourmash signature from (optional)", type=["fasta", "fa", "fna"])
    uploaded_sig = st.file_uploader("...or a pre-built sourmash signature (.sig/.sig.zip)", type=["sig", "zip"])

    st.subheader("STAT (BigQuery)")
    stat_project = st.text_input("GCP billing project", value="", help="Leave blank to use $GOOGLE_CLOUD_PROJECT")
    run_stat = st.checkbox(
        "Run STAT k-mer search",
        value=False,
        help="Scans ~500 GB of BigQuery per run (~half the 1 TB/month free tier), billed to your GCP project.",
    )
    if run_stat:
        st.warning("STAT enabled: this will scan ~500 GB of BigQuery, billed to your GCP project.")
    run_branchwater = st.checkbox("Run Branchwater search", value=True)

    run = st.button("Search", type="primary")

if run and name:
    with st.spinner(f"Matching {name!r} in GBIF..."):
        try:
            taxon = gbif.match_taxon(name)
        except ValueError as e:
            st.error(str(e))
            st.stop()

    st.success(f"Matched **{taxon.scientific_name}** (GBIF key {taxon.usage_key}, rank {taxon.rank})")

    signature_path = None
    if uploaded_sig is not None:
        signature_path = Path("uploaded_signature.sig.zip")
        signature_path.write_bytes(uploaded_sig.read())
    elif uploaded_fasta is not None:
        fasta_path = Path("uploaded_query.fasta")
        fasta_path.write_bytes(uploaded_fasta.read())
        with st.spinner("Building sourmash signature..."):
            try:
                signature_path = signatures.build_signature(fasta_path)
            except RuntimeError as e:
                st.warning(f"Could not build signature: {e}")

    with st.spinner("Fetching GBIF occurrences and searching SRA (this can take a few minutes)..."):
        rep = report_mod.build_report(
            name,
            max_occurrences=max_occurrences,
            signature_path=signature_path,
            stat_project=stat_project or None,
            run_branchwater=run_branchwater,
            run_stat=run_stat,
        )

    for note in rep.notes:
        st.info(note)

    col1, col2 = st.columns(2)
    col1.metric("GBIF occurrences (total)", rep.occurrence_count_total)
    col1.metric("GBIF occurrences (fetched)", len(rep.occurrences))
    col2.metric("SRA sequence hits", len(rep.sra_hits))

    tab_map, tab_gbif, tab_sra = st.tabs(["Map", "GBIF records", "SRA hits"])

    with tab_map:
        geo = report_mod.combined_geojson(rep)
        kind_color = {"gbif_occurrence": "#1f77b4", "sra_hit": "#d62728"}
        points = []
        for f in geo["features"]:
            lon, lat = f["geometry"]["coordinates"]
            kind = f["properties"]["kind"]
            points.append({"lat": lat, "lon": lon, "kind": kind, "color": kind_color[kind]})
        if points:
            df = pd.DataFrame(points)
            st.map(df, latitude="lat", longitude="lon", color="color")
            st.caption("Blue = GBIF specimen/observation record. Red = geolocated SRA sequence hit.")
        else:
            st.write("No geolocated points to show.")

    with tab_gbif:
        df = pd.DataFrame([vars(o) for o in rep.occurrences])
        st.dataframe(df, use_container_width=True)

    with tab_sra:
        df = pd.DataFrame([vars(h) for h in rep.sra_hits])
        st.dataframe(df, use_container_width=True)
elif run:
    st.warning("Enter an organism name.")
