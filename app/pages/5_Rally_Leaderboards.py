from __future__ import annotations

# ruff: noqa: E402 -- Streamlit pages establish repository paths before local imports.
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app"))

from app_data import render_data_diagnostics
from alt_asset_explorer.leaderboards import ARCHIVE_PATH, METRICS, current_source_version, load_archive, movement_table, rank_history_data

st.set_page_config(page_title="Rally Leaderboards Lab", layout="wide")
render_data_diagnostics()
st.title("Rally Leaderboards Lab")
st.caption("Point-in-time quarterly rankings over committed Rally research artifacts—not live listings or appraisals.")


@st.cache_data(show_spinner=False)
def cached_archive(source_version: str) -> pd.DataFrame:
    """Cache only while the complete canonical leaderboard input set is unchanged."""
    return load_archive(expected_source_version=source_version)


archive = cached_archive(current_source_version())
if archive.empty:
    st.info("Quarterly leaderboard history has not been initialized. Run `python scripts/build_quarterly_leaderboards.py --full-refresh`.")
    st.stop()
archive["snapshot_date"] = pd.to_datetime(archive["snapshot_date"])
archive["rank"] = pd.to_numeric(archive["rank"], errors="coerce")
archive["percentile_rank"] = pd.to_numeric(archive["percentile_rank"], errors="coerce")

with st.expander("Data status and methodology", expanded=False):
    status = st.columns(6)
    status[0].metric("Archive", ARCHIVE_PATH.name)
    status[1].metric("Latest snapshot", str(archive.snapshot_date.max().date()))
    status[2].metric("Snapshots", archive.snapshot_date.nunique())
    status[3].metric("Subjects", archive.subject_id.nunique())
    status[4].metric("Methodology", archive.methodology_version.iloc[-1])
    status[5].metric("Source version", archive.source_data_version.iloc[-1])
    st.warning("Historical rankings reflect assets currently cataloged in Rally Terminal. Adding newly cataloged historical assets can revise prior ranks. Current status metadata is not a point-in-time tradability history; eligibility is inferred from observations. Existing index prototypes are reused, and market capitalization uses available current share-count metadata, so historical market cap is an estimate where share counts changed.")

tab_current, tab_history, tab_movement = st.tabs(["Current Leaderboard", "Rank Over Time", "Movement"])
metric_options = list(METRICS)
type_options = sorted(archive.subject_type.dropna().unique())
snapshots = sorted(archive.snapshot_date.unique())

with tab_current:
    controls = st.columns(5)
    universe = controls[0].selectbox("Subject universe", ["Individual Rally asset", "All subjects", *[x for x in type_options if x != "Individual Rally asset"]])
    metric = controls[1].selectbox("Metric", metric_options, index=metric_options.index("trailing_1y_return"), format_func=lambda k: METRICS[k].display_name)
    snapshot = pd.Timestamp(controls[2].selectbox("Snapshot date", snapshots, index=len(snapshots)-1, format_func=lambda x: str(pd.Timestamp(x).date())))
    top_n = controls[3].number_input("Top N", 1, 200, 20)
    search = controls[4].text_input("Search")
    view = archive[(archive.metric_key == metric) & (archive.snapshot_date == snapshot)].copy()
    if universe != "All subjects": view = view[view.subject_type == universe]
    categories = st.multiselect("Category", sorted(view.category.dropna().astype(str).unique()))
    if categories: view = view[view.category.astype(str).isin(categories)]
    if search: view = view[view.subject_name.astype(str).str.contains(search, case=False, regex=False) | view.ticker.astype(str).str.contains(search, case=False, regex=False)]
    eligible = view[view.eligible].sort_values(["rank", "subject_id"]).head(int(top_n))
    previous = snapshots[snapshots.index(snapshot.to_datetime64())-1] if snapshots.index(snapshot.to_datetime64()) > 0 else None
    prior = archive[(archive.metric_key == metric) & (archive.snapshot_date == previous) & archive.eligible][["subject_id", "rank"]].rename(columns={"rank":"previous_rank"}) if previous is not None else pd.DataFrame(columns=["subject_id","previous_rank"])
    eligible = eligible.merge(prior, on="subject_id", how="left"); eligible["rank_change"] = eligible.previous_rank - eligible["rank"]
    cards = st.columns(6); cards[0].metric("Snapshot", str(snapshot.date())); cards[1].metric("Metric", METRICS[metric].display_name); cards[2].metric("Eligible", int(view.eligible.sum())); cards[3].metric("Excluded", int((~view.eligible).sum())); cards[4].metric("New entrants", int(eligible.previous_rank.isna().sum())); cards[5].metric("Data freshness", f"{pd.to_numeric(view.observation_age_days, errors='coerce').median():.0f}d median")
    display = eligible[["rank","previous_rank","rank_change","subject_name","ticker","subject_type","category","metric_value","percentile_rank","observation_count","effective_start_date","latest_observation_date","observation_age_days"]]
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.download_button("Download filtered leaderboard", display.to_csv(index=False), f"leaderboard-{snapshot.date()}-{metric}.csv", "text/csv")
    with st.expander("Exclusion diagnostics"):
        exclusions=view[~view.eligible][["subject_name","ticker","subject_type","exclusion_reason","observation_count","latest_observation_date","observation_age_days"]]
        st.dataframe(exclusions,use_container_width=True,hide_index=True); st.download_button("Download exclusions",exclusions.to_csv(index=False),f"leaderboard-exclusions-{snapshot.date()}-{metric}.csv","text/csv")
    category_summary=eligible[eligible.subject_type=="Individual Rally asset"].groupby("category",dropna=False).agg(category_leader=("subject_name","first"),category_median=("metric_value","median"),category_mean=("metric_value","mean"),eligible_constituents=("subject_id","nunique")).reset_index()
    if not category_summary.empty: st.subheader("Category summary"); st.dataframe(category_summary,use_container_width=True,hide_index=True)

with tab_history:
    c=st.columns(4); history_metric=c[0].selectbox("Ranking metric",metric_options,index=metric_options.index("trailing_1y_return"),format_func=lambda k:METRICS[k].display_name,key="history_metric"); history_type=c[1].selectbox("Subject universe",type_options,key="history_type")
    eligible_latest=archive[(archive.metric_key==history_metric)&(archive.snapshot_date==archive.snapshot_date.max())&archive.eligible&(archive.subject_type==history_type)].sort_values("rank")
    choices=archive[archive.subject_type==history_type][["subject_id","subject_name","ticker"]].drop_duplicates().sort_values("subject_name"); labels=dict(zip(choices.subject_id,choices.subject_name.astype(str)+" · "+choices.ticker.astype(str)))
    selected=c[2].multiselect("Selected subjects",choices.subject_id,default=eligible_latest.subject_id.head(5).tolist(),format_func=lambda x:labels.get(x,x)); mode=c[3].radio("Rank display",["Absolute rank","Percentile rank"])
    history=rank_history_data(archive,history_metric,selected); y="rank" if mode=="Absolute rank" else "percentile_rank"
    fig=px.line(history,x="snapshot_date",y=y,color="subject_name",markers=True,hover_data=["metric_value","percentile_rank","eligible_universe_size","rank_change","observation_count","exclusion_reason"])
    if mode=="Absolute rank": fig.update_yaxes(autorange="reversed",title="Rank (1 is best)")
    else: fig.update_yaxes(tickformat=".0%",title="Percentile (best approaches 100%)")
    fig.update_traces(connectgaps=False)
    fig.update_layout(legend_title_text="Subject"); st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False})
    st.caption("Missing and ineligible quarters are gaps; lines are not interpolated. Percentile = (eligible universe size − rank) / (eligible universe size − 1); a one-subject universe is 100%.")
    st.download_button("Download rank history",history.to_csv(index=False),f"rank-history-{history_metric}.csv","text/csv")

with tab_movement:
    c=st.columns(3); move_metric=c[0].selectbox("Metric",metric_options,index=metric_options.index("trailing_1y_return"),format_func=lambda k:METRICS[k].display_name,key="move_metric"); start=pd.Timestamp(c[1].selectbox("Start quarter",snapshots,index=max(0,len(snapshots)-2),format_func=lambda x:str(pd.Timestamp(x).date()))); end=pd.Timestamp(c[2].selectbox("End quarter",snapshots,index=len(snapshots)-1,format_func=lambda x:str(pd.Timestamp(x).date())))
    if start>=end: st.warning("Choose an end quarter after the start quarter.")
    else:
        movement=movement_table(archive,start,end,move_metric); st.dataframe(movement.sort_values("rank_change",ascending=False,na_position="last"),use_container_width=True,hide_index=True); st.download_button("Download movement table",movement.to_csv(index=False),f"movement-{start.date()}-{end.date()}-{move_metric}.csv","text/csv")

st.download_button("Download complete quarterly state archive (CSV)", archive.to_csv(index=False), "quarterly_leaderboard_history.csv", "text/csv")
