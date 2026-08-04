from __future__ import annotations
import json, sys
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'app'))
from app_data import get_canonical_market, render_data_diagnostics
from alt_asset_explorer.valuation_library.storage import library_assets, load_asset_files, save_json, ingest_report, regenerate_manifest, build_report_package, asset_dir
from alt_asset_explorer.valuation_library.engine import run_valuation
from alt_asset_explorer.valuation_library.models import Factors, Research

st.set_page_config(page_title='Valuation Library', layout='wide')
render_data_diagnostics()
st.title('Asset Valuation Library')
st.caption('Manual ChatGPT intake, deterministic valuation, and browsable asset-level reports. Research only; not an appraisal service.')

def manifests():
    rows=[]
    for aid in library_assets():
        m=regenerate_manifest(aid).model_dump(mode='json')
        val=load_asset_files(aid).get('valuation',{})
        res=val.get('results',{}) if isinstance(val,dict) else {}
        mc=val.get('market_comparison',{}) if isinstance(val,dict) else {}
        rows.append({'asset_id':aid,'asset':m.get('display_name') or aid,'symbol':(m.get('rally_match') or {}).get('ticker'),'category':(m.get('rally_match') or {}).get('category'),'status':m.get('publication_status'),'research_date':m.get('research_date'),'base_fair_value':res.get('base_value_usd'),'conservative_value':res.get('conservative_value_usd'),'optimistic_value':res.get('optimistic_value_usd'),'confidence':res.get('confidence_score'),'current_rally_value':mc.get('last_observed_market_value_usd'),'premium_discount_to_base':mc.get('premium_discount_to_base_pct'),'methodology':m.get('methodology_version'),'report_available':m.get('files_present',{}).get('report'), 'warnings':'; '.join(m.get('warnings',[]))})
    return pd.DataFrame(rows)

tab_library, tab_detail, tab_intake, tab_report = st.tabs(['Research Library','Asset Valuation Detail','Data Intake and Validation','Report Intake and Display'])
with tab_library:
    df=manifests()
    if df.empty: st.info('No valuation-library assets yet.')
    else:
        c1,c2,c3,c4=st.columns(4)
        q=c1.text_input('Search asset or symbol')
        cats=['All']+sorted([x for x in df['category'].dropna().unique()])
        cat=c2.selectbox('Category',cats)
        statuses=['All']+sorted(df['status'].dropna().unique())
        status=c3.selectbox('Workflow status',statuses)
        report=c4.selectbox('Report availability',['All','Available','Missing'])
        f=df.copy()
        if q: f=f[f.astype(str).agg(' '.join,axis=1).str.contains(q,case=False,na=False)]
        if cat!='All': f=f[f['category'].eq(cat)]
        if status!='All': f=f[f['status'].eq(status)]
        if report!='All': f=f[f['report_available'].eq(report=='Available')]
        st.dataframe(f, use_container_width=True, hide_index=True)
with tab_detail:
    ids=library_assets(); aid=st.selectbox('Select valuation-library asset', ids) if ids else None
    if aid:
        files=load_asset_files(aid); m=regenerate_manifest(aid)
        st.subheader(m.display_name or aid); st.json(m.model_dump(mode='json'), expanded=False)
        if files.get('valuation'):
            v=files['valuation']; st.markdown('### Generated valuation summary (authoritative structured output)')
            cols=st.columns(4); r=v.get('results',{})
            cols[0].metric('Conservative', f"${r.get('conservative_value_usd'):,.0f}" if r.get('conservative_value_usd') else 'Unavailable')
            cols[1].metric('Base', f"${r.get('base_value_usd'):,.0f}" if r.get('base_value_usd') else 'Unavailable')
            cols[2].metric('Optimistic', f"${r.get('optimistic_value_usd'):,.0f}" if r.get('optimistic_value_usd') else 'Unavailable')
            cols[3].metric('Confidence', f"{r.get('confidence_score',0):.0%}")
            st.warning('\n'.join(v.get('warnings',[])) or 'No valuation warnings.')
        if files.get('factors'):
            st.markdown('### Observed facts, analyst judgments, and factors'); st.json(files['factors'], expanded=False)
        if files.get('research'):
            st.markdown('### Research evidence and comparable sales'); st.dataframe(pd.DataFrame(files['research'].get('comparable_sales',[])), use_container_width=True)
        if files.get('valuation'):
            st.markdown('### Calculation trace'); st.json(files['valuation'].get('calculation_trace',[]), expanded=False)
        if files.get('report'):
            st.markdown('### Report preview'); st.markdown(files['report'], unsafe_allow_html=False)
        for kind,fn in [('factors','factors.json'),('research','research.json'),('valuation','valuation.json'),('report','report.md')]:
            if kind in files: st.download_button(f'Download {fn}', json.dumps(files[kind],indent=2) if kind!='report' else files[kind], file_name=fn, key=f'dl-{aid}-{fn}')
        st.download_button('Download ChatGPT Report Package', build_report_package(aid), file_name=f'{aid}_chatgpt_report_package.zip')
with tab_intake:
    cm=get_canonical_market().asset_master
    options=sorted(set(cm['ticker'].astype(str)) | set(library_assets())) if not cm.empty else library_assets()
    selected=st.selectbox('Select existing Rally ticker or valuation asset ID', options, key='intake_asset')
    factors_txt=st.text_area('Paste factors.json', height=220)
    research_txt=st.text_area('Paste research.json', height=220)
    overwrite=st.checkbox('Overwrite existing files with timestamped revision backups')
    if st.button('Validate intake JSON'):
        try:
            f=Factors.model_validate(json.loads(factors_txt)); r=Research.model_validate(json.loads(research_txt)); st.success('Both JSON documents are valid.'); st.json({'factors_asset_id':f.asset_id,'research_asset_id':r.asset_id})
        except Exception as e: st.error(str(e))
    if st.button('Save valid JSON and run valuation'):
        try:
            f=json.loads(factors_txt); r=json.loads(research_txt); aid=f['asset_id']; save_json(aid,'factors',f,overwrite=overwrite); save_json(aid,'research',r,overwrite=overwrite); val=run_valuation(aid,write=True); st.success(f'Wrote valuation.json for {aid}: {val.valuation_status}'); st.json(val.model_dump(mode='json'))
        except Exception as e: st.error(str(e))
with tab_report:
    aid=st.selectbox('Select asset for report.md', library_assets(), key='report_asset') if library_assets() else None
    if aid:
        report_txt=st.text_area('Paste report.md', height=320)
        uploaded=st.file_uploader('Or upload report.md', type=['md'])
        if uploaded: report_txt=uploaded.read().decode('utf-8')
        st.markdown('### Preview'); st.markdown(report_txt, unsafe_allow_html=False)
        if st.button('Save report.md'):
            try: ingest_report(aid, report_txt, overwrite=True); st.success(f'Saved {asset_dir(aid)/"report.md"}')
            except Exception as e: st.error(str(e))
