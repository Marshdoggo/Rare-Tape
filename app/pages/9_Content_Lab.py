from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT=Path(__file__).resolve().parents[2]; ARCHIVE=ROOT/"data/processed/content_lab"
st.set_page_config(page_title="Content Lab | Rally Terminal",page_icon="◫",layout="wide")
st.title("Content Lab"); st.caption("Deterministic story discovery · evidence before narrative · not a live Rally feed or appraisal")

@st.cache_data(show_spinner=False)
def load_archive():
    leads=pd.read_csv(ARCHIVE/"story_leads.csv") if (ARCHIVE/"story_leads.csv").exists() else pd.DataFrame()
    evidence=json.loads((ARCHIVE/"story_evidence.json").read_text()) if (ARCHIVE/"story_evidence.json").exists() else {}
    return leads,evidence

leads,evidence=load_archive()
if leads.empty:
    st.info("No Content Lab archive is available. Run `python scripts/build_content_lab.py --all-quarters`."); st.stop()
periods=sorted(leads.period.dropna().unique(),reverse=True); period=st.sidebar.selectbox("Period",["Latest",*periods,"All historical quarters"])
families=sorted(leads.story_family.dropna().unique()); selected_families=st.sidebar.multiselect("Story families",families,default=families)
categories=sorted(x for x in leads.category.dropna().unique() if str(x).strip()); selected_categories=st.sidebar.multiselect("Categories",categories)
minimum_quality=st.sidebar.slider("Minimum evidence quality",0.0,1.0,0.25,.05); count=st.sidebar.selectbox("Number of leads",[10,20,50,"All"],index=1)
view=leads[leads.story_family.isin(selected_families)&(leads.data_quality_score>=minimum_quality)].copy()
if period=="Latest": view=view[view.period==periods[0]]
elif period!="All historical quarters": view=view[view.period==period]
if selected_categories: view=view[view.category.isin(selected_categories)]
view=view.sort_values(["content_score","story_id"],ascending=[False,True]); view=view if count=="All" else view.head(int(count)); view.insert(0,"Rank",range(1,len(view)+1))
st.metric("Evidence-backed leads",len(view)); table=view.rename(columns={"content_score":"Score","headline":"Story","story_family":"Type","primary_subject_name":"Subject","key_number":"Key number","data_quality_score":"Quality"})
st.dataframe(table[["Rank","Score","Story","Type","period","Subject","Key number","Quality"]],hide_index=True,use_container_width=True)
if view.empty: st.warning("No leads match these filters."); st.stop()
choice=st.selectbox("Open a story",view.story_id,format_func=lambda x:view.set_index("story_id").loc[x,"headline"]); row=view.set_index("story_id").loc[choice]; packet=evidence.get(choice,{})
st.subheader(row.headline); st.markdown(f"**Thesis.** {row.thesis}"); st.markdown(f"**Why it is interesting.** {row.why_interesting}")
left,right=st.columns([3,2])
with left:
    facts=pd.DataFrame(packet.get("facts",[])); st.markdown("#### Evidence"); st.dataframe(facts,hide_index=True,use_container_width=True)
    if len(facts) and "value" in facts: st.plotly_chart(px.bar(facts,x="metric",y="value",title="Evidence metrics"),use_container_width=True)
with right:
    st.markdown("#### Caveats"); caveats=packet.get("data_quality",{}).get("caveats",[]); st.write(caveats or ["No detector-specific caveat beyond canonical dataset limitations."])
    st.markdown("#### Follow-up research"); st.write(packet.get("unsupported_questions",[]))
    st.markdown("#### Suggested charts"); st.write(packet.get("suggested_visuals",[]))
with st.expander("Evidence packet (JSON)"): st.json(packet)
