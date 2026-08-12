"""Advanced deterministic detectors composed from canonical analytical primitives."""
from __future__ import annotations

import math
import pandas as pd

from alt_asset_explorer.correlation_lab import align_values, calculate_returns, correlation_matrices
from alt_asset_explorer.contribution import concentration_metrics
from alt_asset_explorer.indices import build_index_from_selection, summarize_contributions


QUESTIONS = {
    "correlation_regime": ["Did the physical collectible market exhibit the same decoupling?", "Was the change driven by one observation?", "Did liquidity change concurrently?", "Did a macro regime change coincide with it?"],
    "volatility_regime": ["Was the move driven by one transaction or persistent repricing?", "Did comparable assets behave similarly?", "Did observation frequency change?"],
    "rank_history": ["What changed between the two ranking dates?", "Did universe entry or dropout affect rank?", "Does percentile rank confirm the absolute-rank move?"],
    "streak": ["What sustained the streak?", "How rare is this streak in available history?", "Did liquidity remain comparable throughout?"],
    "fair_value": ["Have comparable auction results changed since valuation?", "Has provenance or condition information changed?", "Is the valuation stale?", "Does secondary-market evidence support the modeled gap?"],
    "index_attribution": ["Which constituents caused the concentration?", "Was leadership broad or narrow?", "Did the same assets dominate prior quarters?", "Was index performance representative?"],
    "index_weighting": ["Which large constituents drove the spread?", "How did the median constituent perform?", "Is the divergence persistent?"],
    "exit_benchmark": ["What would the same capital have earned in SPY?", "What was the category-index return?", "Was the premium external acquisition demand or secondary appreciation?"],
}


def _finish(lead, family: str, *, temporal=None):
    lead.research_questions = QUESTIONS[family]
    lead.unsupported_questions = QUESTIONS[family]
    lead.temporal_validity = temporal or {"as_of_safe": True, "cutoff": lead.as_of_date}
    lead.primary_angle = lead.story_type
    return lead


def detect(engine, period, start, end, returns, enabled):
    leads = []
    if enabled("correlation_regime") and not engine.benchmarks.empty:
        bench=engine.benchmarks.copy(); bench["date"]=pd.to_datetime(bench.date,errors="coerce").dt.normalize()
        spy=bench[(bench.ticker.eq("SPY"))&bench.date.le(end)].set_index("date").adjusted_close
        for cat,group in engine.assets.groupby("category"):
            ids=set(group.asset_id.astype(str)); raw=engine.observations[(engine.observations.asset_id.astype(str).isin(ids))&engine.observations.observed_at.le(end)]
            if raw.empty or spy.empty: continue
            category=raw.groupby("period_end").price_per_share.mean().sort_index()
            grid=pd.date_range(min(category.index.min(),spy.index.min()),end,freq="QE")
            values,_=align_values({str(cat):category,"SPY":spy},grid,max_staleness_days=engine.config.stale_days)
            rr=calculate_returns(values); window=max(4,engine.config.minimum_correlation_observations)
            if len(rr.dropna()) < window*2: continue
            old=correlation_matrices(rr.dropna().iloc[-window*2:-window],minimum_overlap=window)
            new=correlation_matrices(rr.dropna().iloc[-window:],minimum_overlap=window)
            oc=float(old.correlations.loc[str(cat),"SPY"]); nc=float(new.correlations.loc[str(cat),"SPY"])
            if not math.isfinite(oc) or not math.isfinite(nc) or abs(nc-oc)<.5: continue
            regime=lambda x: "strongly positive" if x>=.5 else "positive" if x>=.2 else "strongly negative" if x<=-.5 else "negative" if x<=-.2 else "near-zero"
            thesis=f"{str(cat).title()} showed a possible correlation regime shift with SPY, from {regime(oc)} ({oc:+.2f}) to {regime(nc)} ({nc:+.2f}) across comparable {window}-return windows."
            lead=engine._lead("correlation_regime","possible_regime_shift",period,start,end,f"category:{cat}",thesis,thesis,[{"metric":"prior_correlation","subject":str(cat),"value":oc},{"metric":"recent_correlation","subject":str(cat),"value":nc}],{"prior_correlation":oc,"recent_correlation":nc,"correlation_delta":nc-oc,"overlap":window,"window_length":window,"effective_sampling_density":"quarterly","observations":window*2},{"regime_change":min(1,abs(nc-oc)/1.2),"historical_rarity":min(1,abs(nc-oc)),"narrative":.95},.8,subject_type="category",category=str(cat),caveats=["Descriptive correlation over sparse quarterly marks does not establish a stable economic relationship."],charts=["rolling correlation line","before-vs-after scatter","normalized price series"])
            leads.append(_finish(lead,"correlation_regime"))
    # Volatility uses authored, irregular observations; no daily-frequency assumption.
    if enabled("volatility_regime"):
        for aid, hist in engine.observations[engine.observations.observed_at.le(end)].sort_values("observed_at").groupby("asset_id"):
            values = hist.drop_duplicates("observed_at", keep="last").set_index("observed_at").price_per_share
            r = values.pct_change(fill_method=None).dropna()
            if len(r) < 8: continue
            recent, prior = r.tail(4), r.iloc[-8:-4]
            if len(prior) < 4 or prior.std() <= 0: continue
            vol, old = float(recent.std()), float(prior.std()); ratio = vol / old
            historical = r.rolling(4).std().dropna(); pct = float((historical <= vol).mean())
            density = min(1.0, len(recent) / 4)
            if not (ratio >= 1.75 or ratio <= .55 or pct >= .95): continue
            kind = "expansion" if ratio > 1 else "compression"
            thesis = f"{engine._name(aid)} showed possible volatility {kind}: recent four-observation volatility was {vol:.1%}, {ratio:.1f}× the preceding window and at its {pct:.0%} historical percentile."
            lead=engine._lead("volatility_regime",kind,period,start,end,aid,thesis,thesis,[{"metric":"recent_volatility","subject":aid,"value":vol},{"metric":"volatility_ratio","subject":aid,"value":ratio}],{"recent_volatility":vol,"prior_volatility":old,"volatility_ratio":ratio,"historical_percentile":pct,"observations":len(r)},{"regime_change":min(1,abs(math.log(max(ratio,.01)))/1.4),"historical_rarity":abs(pct-.5)*2,"narrative":.9},.55+.35*density,caveats=["Volatility uses observation-to-observation returns; sparse marks can conceal intraperiod movement."],charts=["rolling volatility","price history with regime shading","volatility percentile"])
            leads.append(_finish(lead,"volatility_regime"))

    # Asset quarterly streaks are evaluated only through the selected cutoff.
    if enabled("streak"):
        for aid,h in engine.observations[engine.observations.observed_at.le(end)].sort_values("observed_at").groupby("asset_id"):
            q=h.drop_duplicates("period_end",keep="last").set_index("period_end").price_per_share.pct_change(fill_method=None).dropna()
            if q.empty: continue
            sign=1 if q.iloc[-1]>0 else -1; streak=0
            for v in reversed(q.tolist()):
                if v*sign>0: streak+=1
                else: break
            if streak < 3: continue
            kind="positive_streak" if sign>0 else "negative_streak"; verb="risen" if sign>0 else "declined"
            thesis=f"{engine._name(aid)} has {verb} for {streak} consecutive observed quarters through {period}."
            lead=engine._lead("streak",kind,period,start,end,aid,thesis,thesis,[{"metric":"streak_length","subject":aid,"value":streak}],{"streak_length":streak,"streak_start":q.index[-streak].date().isoformat(),"observations":len(q)},{"persistence":min(1,streak/6),"historical_rarity":min(1,(streak-1)/5),"narrative":.9},min(.95,.5+len(q)/30),charts=["quarterly return strip","price history"])
            leads.append(_finish(lead,"streak"))

    if enabled("rank_history") and not engine.leaderboards.empty:
        lb=engine.leaderboards.copy(); lb["snapshot_date"]=pd.to_datetime(lb.snapshot_date,errors="coerce").dt.normalize()
        lb=lb[(lb.snapshot_date<=end)&lb.eligible.fillna(False)]
        metric="latest_quarter_return" if "latest_quarter_return" in set(lb.metric_key) else "total_return"
        snaps=sorted(lb.loc[lb.metric_key.eq(metric),"snapshot_date"].unique())
        if len(snaps)>=2:
            prev,cur=snaps[-2:]; x=lb[(lb.metric_key==metric)&lb.snapshot_date.isin([prev,cur])]
            wide=x.pivot_table(index="subject_id",columns="snapshot_date",values=["rank","percentile_rank","eligible_universe_size"],aggfunc="last").dropna(subset=[("rank",prev),("rank",cur)])
            for sid,row in wide.iterrows():
                delta=float(row[("percentile_rank",cur)]-row[("percentile_rank",prev)])
                if abs(delta)<.35: continue
                aid=str(sid).removeprefix("asset:"); old,new=int(row[("rank",prev)]),int(row[("rank",cur)])
                direction="improved" if new<old else "fell"
                thesis=f"{engine._name(aid)} {direction} from rank #{old} to #{new}; percentile rank changed {delta:+.0%} as of {pd.Timestamp(cur).date()}."
                lead=engine._lead("rank_history","rank_jump",period,start,end,aid,thesis,thesis,[{"metric":"previous_rank","subject":aid,"value":old},{"metric":"current_rank","subject":aid,"value":new}],{"previous_rank":old,"current_rank":new,"percentile_rank_change":delta,"universe_size":int(row[("eligible_universe_size",cur)]),"observations":2},{"rank_change":min(1,abs(delta)),"magnitude":min(1,abs(delta)),"narrative":.9},.85,charts=["rank-over-time","percentile-rank line","bump chart"])
                leads.append(_finish(lead,"rank_history"))

    if enabled("fair_value"):
        snap=engine._snapshots(end).set_index("asset_id")
        for v in engine.valuations:
            effective=pd.Timestamp(v.effective_date)
            if effective>end or v.asset_id not in snap.index: continue
            result=v.payload.get("results",{}); base=pd.to_numeric(result.get("base_value_usd"),errors="coerce")
            shares=pd.to_numeric(engine.asset_meta.loc[v.asset_id].get("share_count",engine.asset_meta.loc[v.asset_id].get("shares_outstanding")),errors="coerce")
            if pd.isna(base) or pd.isna(shares): continue
            market=float(snap.loc[v.asset_id,"price_per_share"])*float(shares); gap=float(base/market-1)
            if abs(gap)<.2: continue
            thesis=f"{engine._name(v.asset_id)}'s contemporaneous market value was {abs(gap):.1%} {'below' if gap>0 else 'above'} the experimental base fair-value estimate available on {effective.date()}."
            metrics={"market_value":market,"conservative_value":result.get("conservative_value_usd"),"base_value":float(base),"optimistic_value":result.get("optimistic_value_usd"),"base_gap_percent":gap,"valuation_confidence":result.get("confidence_score"),"valuation_effective_date":effective.date().isoformat(),"valuation_age_days":(end-effective).days,"observations":1}
            lead=engine._lead("fair_value","valuation_gap",period,start,end,v.asset_id,thesis,thesis,[{"metric":"market_value","subject":v.asset_id,"value":market},{"metric":"base_fair_value","subject":v.asset_id,"value":float(base)}],metrics,{"valuation_gap":min(1,abs(gap)),"magnitude":min(1,abs(gap)),"narrative":.95},float(result.get("confidence_score") or .4),caveats=["Fair value is an experimental comparable-sales estimate, not a definitive appraisal."],charts=["market value with bear/base/bull bands","valuation spectrum"])
            leads.append(_finish(lead,"fair_value",temporal={"as_of_safe":True,"valuation_effective_date":effective.date().isoformat(),"date_source":v.date_source,"date_confidence":v.date_confidence}))

    if enabled("exit_benchmark") and not engine.exits.empty and not engine.benchmarks.empty:
        ex=engine.exits.copy(); ex["exit_effective_date"]=pd.to_datetime(ex.exit_effective_date,errors="coerce").dt.normalize()
        ex=ex[ex.exit_effective_date.between(start,end)&ex.is_confirmed.fillna(False)]
        spy=engine.benchmarks[engine.benchmarks.ticker.eq("SPY")].copy(); spy["date"]=pd.to_datetime(spy.date,errors="coerce").dt.normalize()
        for _,row in ex.iterrows():
            aid=str(row.asset_id); realized=pd.to_numeric(row.get("realized_return"),errors="coerce")
            if aid not in engine.asset_meta.index or pd.isna(realized): continue
            inception=pd.to_datetime(engine.asset_meta.loc[aid].get("offering_date"),errors="coerce")
            available=spy[spy.date.le(row.exit_effective_date)]
            before=available[available.date.ge(inception)] if pd.notna(inception) else pd.DataFrame()
            if before.empty: continue
            b0,b1=float(before.iloc[0].adjusted_close),float(available.iloc[-1].adjusted_close); br=b1/b0-1; excess=float(realized)-br
            thesis=f"{engine._name(aid)} returned {float(realized):+.1%} at its confirmed exit versus SPY's {br:+.1%} over the matched holding period, an excess return of {excess:+.1%}."
            lead=engine._lead("exit_benchmark","holding_period_spy",period,start,end,aid,thesis,thesis,[{"metric":"realized_total_return","subject":aid,"value":float(realized)},{"metric":"SPY_holding_period_return","subject":"SPY","value":br}],{"realized_return":float(realized),"benchmark_return":br,"excess_return":excess,"holding_period_start":inception.date().isoformat(),"holding_period_end":row.exit_effective_date.date().isoformat(),"observations":2},{"benchmark_excess":min(1,abs(excess)/.5),"contrast":min(1,abs(excess)/.5),"narrative":.95},.9,caveats=["Benchmark endpoints use the first available close on/after offering and last close on/before exit."],charts=["normalized growth-of-$100 comparison","holding-period return bars"])
            leads.append(_finish(lead,"exit_benchmark",temporal={"as_of_safe":True,"exit_effective_date":row.exit_effective_date.date().isoformat(),"confirmed_exit":True}))

    # Canonical index construction and contribution outputs drive weighting/attribution.
    if (enabled("index_attribution") or enabled("index_weighting")) and not returns.empty:
        obs=engine.observations[engine.observations.observed_at.le(end)].copy()
        obs=obs.rename(columns={"observed_at":"date","price_per_share":"last"})
        shares=engine.assets.set_index("asset_id").get("share_count",engine.assets.set_index("asset_id").get("shares_outstanding",pd.Series(dtype=float)))
        obs["market_cap_usd"]=obs["last"]*obs.asset_id.map(shares)
        for cat,ids in [("all",engine.assets.asset_id.astype(str).tolist()),*[(str(c),g.asset_id.astype(str).tolist()) for c,g in engine.assets.groupby("category")]]:
            eq=build_index_from_selection(obs,asset_ids=ids,weighting_method="equal",start_date=start-pd.Timedelta(days=190),end_date=end)
            mc=build_index_from_selection(obs,asset_ids=ids,weighting_method="market_cap",start_date=start-pd.Timedelta(days=190),end_date=end)
            if len(eq.series)<2 or len(mc.series)<2: continue
            er=float(eq.series.iloc[-1].index_level/eq.series.iloc[-2].index_level-1); mr=float(mc.series.iloc[-1].index_level/mc.series.iloc[-2].index_level-1); spread=mr-er
            if enabled("index_weighting") and (abs(spread)>=.08 or er*mr<0):
                thesis=f"The {cat} market-cap index returned {mr:+.1%} versus {er:+.1%} equal-weighted, a {spread:+.1%} concentration spread in {period}."
                lead=engine._lead("index_weighting","equal_vs_market_cap",period,start,end,f"index:{cat}",thesis,thesis,[{"metric":"market_cap_return","subject":cat,"value":mr},{"metric":"equal_weight_return","subject":cat,"value":er}],{"market_cap_return":mr,"equal_weight_return":er,"spread":spread,"constituent_breadth":int(eq.series.iloc[-1].constituent_count),"observations":2},{"contrast":min(1,abs(spread)/.25),"concentration":min(1,abs(spread)/.25),"narrative":.95},.8,subject_type="index",category=cat,charts=["indexed performance comparison","weighting spread line","constituent-return distribution"])
                leads.append(_finish(lead,"index_weighting"))
            if enabled("index_attribution") and not mc.contributions.empty:
                last_date=mc.series.iloc[-1].date; c=mc.contributions[mc.contributions.date.eq(last_date)]
                summary=summarize_contributions(c,engine.assets).rename(columns={"contribution_points":"contribution"}); cm=concentration_metrics(summary)
                if len(summary)>=3 and cm["positive_top_3"]>=.65:
                    thesis=f"Three constituents produced {cm['positive_top_3']:.0%} of positive {cat} market-cap index contribution in {period}."
                    lead=engine._lead("index_attribution","winner_concentration",period,start,end,f"index:{cat}",thesis,thesis,[{"metric":"top_3_positive_share","subject":cat,"value":cm["positive_top_3"]}],{**cm,"constituent_count":len(summary),"observations":len(summary)},{"concentration":cm["positive_top_3"],"breadth":min(1,len(summary)/10),"narrative":.95},.85,subject_type="index",category=cat,charts=["contribution waterfall","horizontal contribution bars","cumulative contribution curve"])
                    leads.append(_finish(lead,"index_attribution"))
    return leads
