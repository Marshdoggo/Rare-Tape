from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Iterable
import math
import pandas as pd

from alt_asset_explorer.benchmark_lab import validate_benchmark_history
from .models import StoryLead
from .scoring import ScoringConfig, deduplicate_and_rank


def _dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True, format="mixed").dt.tz_localize(None).dt.normalize()


def quarter_label(value: object) -> str:
    p = pd.Timestamp(value).to_period("Q")
    return f"{p.year}Q{p.quarter}"


def discover_quarters(observations: pd.DataFrame, minimum_assets: int = 2) -> list[str]:
    if observations.empty: return []
    frame = observations.copy(); frame["period_end"] = _dates(frame["period_end"]); frame["observed_at"] = _dates(frame["observed_at"])
    frame = frame[frame["period_end"].notna() & frame["observed_at"].notna() & frame["observed_at"].le(frame["period_end"])]
    counts = frame.groupby(frame["period_end"].dt.to_period("Q"))["asset_id"].nunique()
    return [f"{p.year}Q{p.quarter}" for p in counts[counts >= minimum_assets].index.sort_values()]


@dataclass
class DiscoveryResult:
    period: str
    raw_candidates: int
    quality_candidates: int
    deduplicated_candidates: int
    slate: list[StoryLead]


class ContentLabEngine:
    def __init__(self, assets: pd.DataFrame, observations: pd.DataFrame, *, benchmarks: pd.DataFrame | None = None,
                 liquidity: pd.DataFrame | None = None, exits: pd.DataFrame | None = None,
                 valuations: list[dict] | None = None, config: ScoringConfig | None = None):
        self.assets = assets.copy(); self.observations = observations.copy(); self.benchmarks = benchmarks.copy() if benchmarks is not None else pd.DataFrame()
        self.liquidity = liquidity.copy() if liquidity is not None else pd.DataFrame(); self.exits = exits.copy() if exits is not None else pd.DataFrame()
        self.valuations = valuations or []; self.config = config or ScoringConfig()
        self.observations["observed_at"] = _dates(self.observations["observed_at"]); self.observations["period_end"] = _dates(self.observations["period_end"])
        self.observations["price_per_share"] = pd.to_numeric(self.observations["price_per_share"], errors="coerce")
        self.asset_meta = self.assets.drop_duplicates("asset_id").set_index("asset_id", drop=False)

    @property
    def quarters(self) -> list[str]: return discover_quarters(self.observations)

    def _period(self, label: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        p = pd.Period(label, freq="Q"); start, nominal_end = p.start_time.normalize(), p.end_time.normalize()
        known = self.observations.loc[self.observations["observed_at"].between(start, nominal_end), "observed_at"].max()
        # A future quarter-end label is a QTD period only through its latest actual evidence date.
        end = min(nominal_end, known) if pd.notna(known) else nominal_end
        return start, end

    def _snapshots(self, end: pd.Timestamp) -> pd.DataFrame:
        # Temporal integrity is based on actual evidence date, never a later authored period label.
        x = self.observations[self.observations["observed_at"].le(end) & self.observations["price_per_share"].gt(0)].copy()
        x = x.sort_values(["asset_id", "observed_at", "period_end"]).groupby("asset_id", as_index=False).tail(1)
        x["age_days"] = (end - x["observed_at"]).dt.days
        return x[x["age_days"].le(self.config.stale_days)]

    def _lead(self, family: str, kind: str, period: str, start: pd.Timestamp, end: pd.Timestamp, subject_id: str,
              headline: str, thesis: str, facts: list[dict], metrics: dict, scores: dict, quality: float,
              *, subject_type: str = "asset", category: str = "", caveats: list[str] | None = None,
              charts: list[str] | None = None, secondary: list[dict[str, str]] | None = None) -> StoryLead:
        meta = self.asset_meta.loc[subject_id] if subject_type == "asset" and subject_id in self.asset_meta.index else {}
        name = str(meta.get("asset_name", meta.get("ticker", subject_id))) if hasattr(meta, "get") else subject_id
        category = category or (str(meta.get("category", "")) if hasattr(meta, "get") else "")
        token = sha1(f"{period}|{family}|{kind}|{subject_id}".encode()).hexdigest()[:12]
        questions = ["Was this move broad or subject-specific?", "Did observation frequency or liquidity affect the measured result?", "What external comparable-market evidence could confirm or challenge the signal?"]
        return StoryLead(token, period, start.date().isoformat(), end.date().isoformat(), end.date().isoformat(), "contemporaneous", family, kind, headline, thesis,
            subject_type, subject_id, name, category, secondary or [], facts, metrics, {"observations": int(metrics.get("observations", 0))}, scores, 0, round(quality, 3),
            "The measured result is unusual relative to the available point-in-time comparison set.", "The engine identifies coincidence and extremeness, not causation.", caveats or [], [thesis], questions, charts or ["price history"], questions,
            ["Chart post", "Newsletter", "Research note"], ["Rally Market Review"], ["data/normalized/price_observations.csv", "data/normalized/assets.csv"])

    def _asset_returns(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        a, b = self._snapshots(start - pd.Timedelta(days=1)), self._snapshots(end)
        frame = a[["asset_id", "price_per_share", "observed_at"]].merge(b[["asset_id", "price_per_share", "observed_at", "age_days"]], on="asset_id", suffixes=("_start", "_end"))
        frame["return"] = frame["price_per_share_end"] / frame["price_per_share_start"] - 1
        return frame.replace([math.inf, -math.inf], pd.NA).dropna(subset=["return"])

    def discover(self, period: str, *, limit: int | None = 20, families: Iterable[str] | None = None) -> DiscoveryResult:
        start, end = self._period(period); returns = self._asset_returns(start, end); leads: list[StoryLead] = []
        allowed = set(families or [])
        def enabled(x: str) -> bool: return not allowed or x in allowed
        if not returns.empty:
            returns["pct"] = returns["return"].rank(pct=True); n = len(returns)
            if enabled("extreme_movers"):
                for _, r in pd.concat([returns.nsmallest(min(5,n), "return"), returns.nlargest(min(5,n), "return")]).drop_duplicates("asset_id").iterrows():
                    direction = "gained" if r["return"] >= 0 else "lost"; ext = abs(float(r["pct"])-.5)*2
                    q = min(1., .35 + .1 * min(int((self.observations.asset_id == r.asset_id).sum()), 6))
                    thesis=f"{self._name(r.asset_id)} {direction} {abs(r['return']):.1%} during {period}, ranking in the {'top' if r['return'] >= 0 else 'bottom'} of {n} eligible assets."
                    leads.append(self._lead("extreme_movers", direction, period,start,end,r.asset_id, f"{self._name(r.asset_id)} {direction} {abs(r['return']):.1%}", thesis,[{"metric":"quarter_return","subject":r.asset_id,"value":float(r["return"])}],{"quarter_return":float(r["return"]),"cross_section_percentile":float(r["pct"]),"eligible_assets":n,"observations":int((self.observations.asset_id==r.asset_id).sum())},{"extremeness":ext,"magnitude":min(1,abs(float(r["return"]))/ .5),"novelty":ext,"narrative":.9},q,charts=["leaderboard","price history"]))
            joined=returns.merge(self.assets[["asset_id","category"]],on="asset_id",how="left")
            cats=joined.groupby("category")["return"].agg(["mean","median","count"]).query("count >= 2").reset_index()
            if enabled("category") and not cats.empty:
                for _,r in pd.concat([cats.nlargest(2,"mean"),cats.nsmallest(2,"mean")]).drop_duplicates("category").iterrows():
                    direction="gained" if r["mean"]>=0 else "lost"; sid=f"category:{r.category}"
                    thesis=f"{r.category.title()} assets averaged a {r['mean']:+.1%} return in {period} across {int(r['count'])} eligible assets."
                    leads.append(self._lead("category","category_return",period,start,end,sid,f"{r.category.title()} averaged {r['mean']:+.1%}",thesis,[{"metric":"mean_asset_return","subject":sid,"value":float(r["mean"])}],{"mean_return":float(r["mean"]),"median_return":float(r["median"]),"observations":int(r["count"])},{"magnitude":min(1,abs(float(r["mean"]))/ .3),"breadth":min(1,float(r["count"])/10),"narrative":.9},min(1,.45+float(r["count"])/20),subject_type="category",category=str(r.category),charts=["category return comparison","distribution/histogram"]))
            if enabled("dispersion_breadth") and n >= 4:
                positive=float((returns["return"]>0).mean()); mean=float(returns["return"].mean()); median=float(returns["return"].median()); dispersion=float(returns["return"].std())
                thesis=f"{positive:.0%} of {n} eligible assets rose in {period}; the mean return was {mean:+.1%} versus a {median:+.1%} median."
                leads.append(self._lead("dispersion_breadth","market_breadth",period,start,end,"rally-market",f"Only {positive:.0%} of eligible assets rose",thesis,[{"metric":"percent_positive","subject":"rally-market","value":positive},{"metric":"mean_return","subject":"rally-market","value":mean}],{"percent_positive":positive,"mean_return":mean,"median_return":median,"dispersion":dispersion,"observations":n},{"contrast":min(1,abs(mean-median)/.15),"breadth":abs(positive-.5)*2,"magnitude":min(1,dispersion/.4),"narrative":.95},min(1,.6+n/100),subject_type="market",charts=["breadth","distribution/histogram"]))
            if enabled("cross_asset_contrast"):
                for cat,g in joined.groupby("category"):
                    if len(g)<2: continue
                    hi,lo=g.loc[g["return"].idxmax()],g.loc[g["return"].idxmin()]; spread=float(hi["return"]-lo["return"])
                    if spread < .20: continue
                    thesis=f"Within {cat}, {self._name(hi.asset_id)} beat {self._name(lo.asset_id)} by {spread:.1%} in {period}."
                    leads.append(self._lead("cross_asset_contrast","category_pair",period,start,end,hi.asset_id,f"A {spread:.1%} split inside {cat}",thesis,[{"metric":"return_spread","subject":hi.asset_id,"value":spread}],{"return_spread":spread,"observations":2},{"contrast":min(1,spread/.6),"magnitude":min(1,spread/.6),"narrative":.9},.65,category=str(cat),secondary=[{"type":"asset","id":str(lo.asset_id),"name":self._name(lo.asset_id)}],charts=["normalized indexed comparison","scatterplot"]))
        if enabled("drawdown_recovery"):
            current=self._snapshots(end)
            for _,r in current.iterrows():
                hist=self.observations[(self.observations.asset_id==r.asset_id)&(self.observations.observed_at<=end)&self.observations.price_per_share.gt(0)]
                if len(hist)<3: continue
                peak=float(hist.price_per_share.max()); dd=float(r.price_per_share/peak-1)
                if dd <= -.25 or r.price_per_share >= peak:
                    kind="deep_drawdown" if dd<0 else "new_high"; thesis=f"{self._name(r.asset_id)} ended {period} {abs(dd):.1%} {'below its prior peak' if dd<0 else 'at a dataset-period high'}."
                    leads.append(self._lead("drawdown_recovery",kind,period,start,end,r.asset_id,thesis,thesis,[{"metric":"drawdown_from_peak","subject":r.asset_id,"value":dd}],{"drawdown":dd,"peak_price":peak,"observations":len(hist)},{"magnitude":min(1,abs(dd)/.7),"extremeness":min(1,abs(dd)/.7),"persistence":min(1,len(hist)/12),"narrative":.85},min(1,.45+len(hist)/20),charts=["drawdown curve","price history"]))
        if enabled("benchmark_divergence") and not returns.empty and not self.benchmarks.empty:
            try: bench=validate_benchmark_history(self.benchmarks,allow_empty=True)
            except Exception: bench=pd.DataFrame()
            spy=bench[(bench.ticker=="SPY")&(bench.date<=end)] if not bench.empty else pd.DataFrame()
            if not spy.empty:
                s0=spy[spy.date<start].tail(1); s1=spy.tail(1)
                if not s0.empty:
                    br=float(s1.adjusted_close.iloc[0]/s0.adjusted_close.iloc[0]-1)
                    for _,r in returns.assign(gap=lambda x:x["return"]-br).reindex(returns.assign(gap=lambda x:x["return"]-br).gap.abs().nlargest(4).index).iterrows():
                        gap=float(r["return"]-br); thesis=f"{self._name(r.asset_id)} returned {r['return']:+.1%} while SPY returned {br:+.1%}, a {gap:+.1%} spread in {period}."
                        leads.append(self._lead("benchmark_divergence","spy_divergence",period,start,end,r.asset_id,f"{self._name(r.asset_id)} diverged from SPY by {gap:+.1%}",thesis,[{"metric":"asset_return","subject":r.asset_id,"value":float(r["return"])},{"metric":"SPY_return","subject":"SPY","value":br},{"metric":"relative_spread","subject":r.asset_id,"value":gap}],{"relative_spread":gap,"benchmark_return":br,"observations":2},{"contrast":min(1,abs(gap)/.5),"magnitude":min(1,abs(gap)/.5),"narrative":.95},.72,secondary=[{"type":"benchmark","id":"SPY","name":"S&P 500 ETF"}],charts=["benchmark-relative performance","normalized indexed comparison"]))
        if enabled("liquidity_staleness"):
            current=self._snapshots(end)
            for _,r in current.nlargest(min(4,len(current)),"age_days").iterrows():
                if r.age_days<60: continue
                thesis=f"{self._name(r.asset_id)}'s latest usable mark was {int(r.age_days)} days old at {period} end, limiting volatility and return interpretation."
                leads.append(self._lead("liquidity_staleness","stale_mark",period,start,end,r.asset_id,f"A {int(r.age_days)}-day-old price mark",thesis,[{"metric":"stale_age_days","subject":r.asset_id,"value":int(r.age_days)}],{"stale_age_days":int(r.age_days),"observations":int((self.observations.asset_id==r.asset_id).sum())},{"magnitude":min(1,r.age_days/self.config.stale_days),"novelty":.7,"narrative":.9},max(.3,1-r.age_days/(self.config.stale_days*1.5)),caveats=["Sparse observations can make measured volatility appear artificially low."],charts=["observation timeline","price history"]))
        if enabled("exit_buyout") and not self.exits.empty and "exit_effective_date" in self.exits:
            x=self.exits.copy(); x["exit_effective_date"]=_dates(x["exit_effective_date"]); x=x[x.exit_effective_date.between(start,end)]
            for _,r in x.iterrows():
                ret=pd.to_numeric(r.get("realized_return"),errors="coerce")
                if pd.isna(ret): continue
                thesis=f"{self._name(r.asset_id)} recorded a confirmed {ret:+.1%} exit return in {period}."
                leads.append(self._lead("exit_buyout","realized_exit",period,start,end,r.asset_id,thesis,thesis,[{"metric":"realized_exit_return","subject":r.asset_id,"value":float(ret)}],{"realized_return":float(ret),"observations":1},{"magnitude":min(1,abs(float(ret))/.7),"novelty":.9,"narrative":.95},.9,caveats=[] if bool(r.get("is_confirmed")) else ["Exit is not marked confirmed."],charts=["exit return vs offering","price history"]))
        # Valuation artifacts are deliberately ignored unless dated and officially available.
        quality=[x for x in leads if x.data_quality_score>=self.config.minimum_data_quality]
        slate=deduplicate_and_rank(leads,self.config,limit)
        return DiscoveryResult(period,len(leads),len(quality),len(deduplicate_and_rank(leads,self.config,None)),slate)

    def discover_all(self, *, limit_per_quarter: int = 20) -> list[DiscoveryResult]:
        return [self.discover(q,limit=limit_per_quarter) for q in self.quarters]

    def get_story(self, story_id: str, results: Iterable[DiscoveryResult]) -> StoryLead | None:
        return next((s for r in results for s in r.slate if s.story_id==story_id),None)

    def _name(self, asset_id: str) -> str:
        if asset_id not in self.asset_meta.index: return str(asset_id)
        r=self.asset_meta.loc[asset_id]; return str(r.get("asset_name") or r.get("ticker") or asset_id)
