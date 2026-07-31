from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd


RALLY_ASSET_COLUMNS = [
    "asset_id",
    "ticker",
    "name",
    "category",
    "subcategory",
    "brand",
    "model",
    "year",
    "size",
    "material",
    "color",
    "hardware",
    "offering_date",
    "offering_market_cap_usd",
    "current_market_cap_usd",
    "acquisition_cost_usd",
    "last_trade_price",
    "bid_price",
    "ask_price",
    "share_count",
    "sec_filing_url",
    "status",
    "exit_date",
    "exit_price_per_share",
    "exit_market_cap_usd",
    "total_return_at_exit",
    "source_notes",
    "trading_state", "lifecycle_event_type", "lifecycle_event_status",
    "lifecycle_event_date", "status_updated_at", "buyout_offer_date",
    "buyout_offer_price_per_share", "buyout_offer_total_value",
    "buyout_reference_price", "buyout_reference_price_date", "buyout_premium_pct",
    "buyout_vote_yes_pct", "buyout_vote_no_pct", "buyout_vote_advisory_pct",
    "buyout_vote_as_of", "buyout_vote_provisional", "buyout_notes",
]

COMPARABLE_SALE_COLUMNS = [
    "comp_id",
    "source",
    "auction_name",
    "auction_url",
    "sale_date",
    "brand",
    "model",
    "size",
    "material",
    "color",
    "hardware",
    "condition",
    "year",
    "estimate_low_usd",
    "estimate_high_usd",
    "realized_price_usd",
    "currency",
    "title",
    "lot_url",
    "raw_text_path",
    "confidence_score",
]

ASSET_COMP_MATCH_COLUMNS = [
    "asset_id",
    "ticker",
    "comp_id",
    "rank",
    "similarity_score",
    "matched_fields",
    "realized_price_usd",
    "sale_date",
    "source",
    "title",
    "lot_url",
]

DECISION_COLUMNS = [
    *RALLY_ASSET_COLUMNS,
    "comp_count",
    "top_comp_count",
    "median_comp_sale_usd",
    "mean_comp_sale_usd",
    "estimate_weighted_value_usd",
    "estimated_nav_usd",
    "nav_low_usd",
    "nav_high_usd",
    "nav_confidence",
    "discount_to_secondary_nav",
    "premium_to_offering",
    "rally_return_since_offering",
    "comp_market_momentum_90d",
    "comp_market_momentum_180d",
    "comp_market_momentum_365d",
    "liquidity_score",
    "mispricing_score",
]

DIAGNOSTIC_COLUMNS = ["metric", "value", "notes"]

KNOWN_BRANDS = {
    "hermes": "Hermes",
    "hermès": "Hermes",
    "chanel": "Chanel",
    "louis vuitton": "Louis Vuitton",
    "goyard": "Goyard",
    "rolex": "Rolex",
    "patek philippe": "Patek Philippe",
    "audemars piguet": "Audemars Piguet",
}

MODEL_PATTERNS = (
    "Birkin",
    "Kelly",
    "Constance",
    "Lindy",
    "Picotin",
    "HAC",
    "Haut a Courroies",
    "Daytona",
    "Nautilus",
    "Royal Oak",
    "Submariner",
)

MATERIAL_PATTERNS = (
    "Porosus Crocodile",
    "Niloticus Crocodile",
    "Mississippiensis Alligator",
    "Crocodile",
    "Alligator",
    "Ostrich",
    "Lizard",
    "Togo",
    "Epsom",
    "Clemence",
    "Clémence",
    "Box",
    "Swift",
    "Evercolor",
    "Tadelakt",
    "Madame",
    "Chevre",
    "Chèvre",
    "Canvas",
    "Leather",
)

HARDWARE_PATTERNS = (
    "Gold Hardware",
    "Palladium Hardware",
    "Permabrass Hardware",
    "Brushed Gold Hardware",
    "Electrum Hardware",
    "Black PVD Hardware",
    "PVD Hardware",
    "Silver Hardware",
    "Brass Hardware",
    "Dark Silver Hardware",
)

SEC_HERMES_KEYWORDS = (
    "hermes",
    "birkin",
    "kelly",
    "faubourg",
    "picnic",
)

TICKER_ALIASES = {"BIRKINBLEU": "BIRKINBLU"}

CATEGORY_KEYWORDS = (
    ("watches", ("rolex", "patek", "audemars", "omega", "watch", "daytona", "nautilus", "royal oak", "submariner")),
    ("cards", ("card", "rookie", "topps", "fleer", "pokemon", "psa", "bgs", "charizard", "jordan", "lebron")),
    ("comics", ("comic", "comics", "marvel", "dc ", "batman", "superman", "spider-man", "x-men", "cgc")),
    ("books", ("first edition", "book", "novel", "inscribed", "signed 1st", "gatsby", "tolkien", "hemingway")),
    ("cars", ("ferrari", "porsche", "lamborghini", "mercedes", "bmw", "ford", "car", "automobile")),
    ("wine", ("wine", "bordeaux", "bourgogne", "dujac", "romanee", "chateau", "champagne", "bottle")),
    ("art", ("warhol", "basquiat", "print", "painting", "artwork", "artist", "lithograph")),
    ("natural_history", ("meteorite", "fossil", "dinosaur", "triceratops", "megalodon", "lunar")),
    ("memorabilia", ("game worn", "game-used", "signed", "autograph", "jersey", "glove", "bat", "boots", "uniform")),
    ("other", ("cryptopunk", "bored ape", "mutant ape", "nft", "meebit", "curio card")),
    ("other", ("video game", "nintendo", "nes", "snes", "playstation", "game boy", "sealed game")),
)


def _ascii(value: object) -> str:
    if pd.isna(value):
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    return normalized.encode("ascii", "ignore").decode("ascii")


def _norm(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and re.fullmatch(r"\d+\.0", value.strip()):
        value = value.strip()[:-2]
    return re.sub(r"\s+", " ", _ascii(value).strip().lower())


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return float(parsed) if pd.notna(parsed) else None


def _date(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.date().isoformat() if pd.notna(parsed) else None


def _first(row: pd.Series, *names: str):
    for name in names:
        value = row.get(name)
        if pd.notna(value) and str(value).strip():
            return value
    return None


def _contains(text: str, pattern: str) -> bool:
    return _ascii(pattern).lower() in _ascii(text).lower()


def parse_collectible_title(title: object, fallback_brand: object = None) -> dict[str, object]:
    text = _ascii(title)
    lowered = _norm(title)
    brand = ""
    for needle, canonical in KNOWN_BRANDS.items():
        if needle in lowered:
            brand = canonical
            break
    if not brand and fallback_brand is not None and str(fallback_brand).strip():
        brand = str(fallback_brand).strip()

    model = next((pattern for pattern in MODEL_PATTERNS if _contains(text, pattern)), "")
    material = next((pattern for pattern in MATERIAL_PATTERNS if _contains(text, pattern)), "")
    hardware = next((pattern for pattern in HARDWARE_PATTERNS if _contains(text, pattern)), "")

    size = ""
    if model:
        match = re.search(rf"\b{re.escape(_ascii(model))}\s+(?P<size>\d{{2,3}})\b", text, re.I)
        if match:
            size = match.group("size")
    if not size:
        match = re.search(r"\b(?P<size>\d{2,3})\s*cm\b", text, re.I)
        if match:
            size = match.group("size")

    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    year = int(years[-1]) if years else None

    first_stop = len(text)
    for stop in (material, model):
        if stop:
            match = re.search(rf"\b{re.escape(_ascii(stop))}\b", text, re.I)
            if match:
                first_stop = min(first_stop, match.start())
    color = text[:first_stop].strip(" ,")
    color = re.sub(r"^(Limited Edition|Vintage|Rare|A Rare)\s+", "", color, flags=re.I).strip()
    color = re.sub(r"^(19\d{2}|20\d{2})\s+", "", color).strip()
    if brand and color.lower().startswith(brand.lower()):
        color = color[len(brand) :].strip(" ,")
    color = re.sub(r"^\d{2,3}\s*cm\s+", "", color, flags=re.I).strip()

    return {
        "brand": brand,
        "model": model,
        "year": year,
        "size": size,
        "material": material,
        "color": color[:80],
        "hardware": hardware,
    }


def _latest_prices(price_history: pd.DataFrame) -> pd.DataFrame:
    if price_history.empty:
        return pd.DataFrame(columns=["asset_id", "last_trade_price", "bid_price", "ask_price", "latest_market_cap_usd"])
    prices = price_history.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices = prices.sort_values(["asset_id", "date"])
    latest = prices.groupby("asset_id", as_index=False).tail(1)
    return latest.rename(columns={"last": "last_trade_price", "bid": "bid_price", "ask": "ask_price", "market_cap_usd": "latest_market_cap_usd"})[
        ["asset_id", "last_trade_price", "bid_price", "ask_price", "latest_market_cap_usd"]
    ]


def _find_sec_match(asset: pd.Series, sec_series: pd.DataFrame) -> pd.Series | None:
    if sec_series.empty:
        return None
    ticker = _norm(asset.get("ticker")).upper()
    if ticker and "series_name" in sec_series:
        candidates = sec_series[sec_series["series_name"].map(_ticker_from_series) == ticker]
        if not candidates.empty:
            return candidates.iloc[-1]

    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", _norm(asset.get("name")))
        if len(token) >= 4 and token not in {"rally", "series", "skeleton", "fossil"}
    ]
    best = None
    best_score = 0
    for _, row in sec_series.iterrows():
        sec_text = " ".join(_norm(row.get(name)) for name in ("series_name", "asset_name"))
        score = sum(1 for token in tokens if token and token in sec_text)
        if score > best_score:
            best = row
            best_score = score
    return best if best_score >= 2 else None


def _find_exit(asset: pd.Series, exits: pd.DataFrame) -> pd.Series | None:
    if exits.empty:
        return None
    direct = exits[exits.get("asset_id", pd.Series(dtype=str)).astype(str) == str(asset.get("asset_id"))]
    if not direct.empty:
        return direct.iloc[-1]
    series = _norm(asset.get("series_name"))
    if series and "series_name" in exits:
        matched = exits[exits["series_name"].map(_norm) == series]
        if not matched.empty:
            return matched.iloc[-1]
    return None


def _ticker_from_series(series_name: object) -> str:
    match = re.search(r"#([A-Za-z0-9]+)\b", str(series_name))
    ticker = match.group(1).upper() if match else _norm(series_name).upper()
    return TICKER_ALIASES.get(ticker, ticker)


def _subcategory(parsed: dict[str, object], title: object) -> str:
    model = _norm(parsed.get("model"))
    if parsed.get("brand") == "Hermes" or any(word in _norm(title) for word in SEC_HERMES_KEYWORDS):
        return f"hermes_{model}" if model else "hermes_other"
    return "uncategorized"


def infer_rally_category(title: object) -> str:
    text = _norm(title)
    if any(word in text for word in SEC_HERMES_KEYWORDS) or any(brand in text for brand in ("chanel", "louis vuitton", "goyard")):
        return "handbags"
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "other"


def infer_rally_subcategory(title: object, parsed: dict[str, object], category: str) -> str:
    text = _norm(title)
    if category == "handbags":
        return _subcategory(parsed, title)
    if category == "watches" and parsed.get("brand"):
        model = _norm(parsed.get("model")) or "watch"
        return f"{_norm(parsed.get('brand')).replace(' ', '_')}_{model}"
    for keyword in ("pokemon", "jordan", "lebron", "charizard", "ferrari", "porsche", "cryptopunk", "bored ape", "warhol"):
        if keyword in text:
            return keyword.replace(" ", "_")
    return category


def _is_descriptive_sec_asset(row: pd.Series) -> bool:
    text = " ".join(_norm(row.get(name)) for name in ("series_name", "asset_name"))
    asset_name = _norm(row.get("asset_name"))
    return bool(asset_name and not asset_name.startswith("series #") and not text.startswith("nan"))


def _sec_asset_id(ticker: str) -> str:
    return f"sec-rally-{ticker.lower()}"


def _sec_asset_rows(sec_series: pd.DataFrame, exits: pd.DataFrame, existing_tickers: set[str]) -> list[dict]:
    if sec_series.empty:
        return []
    rows: list[dict] = []
    candidates = sec_series[sec_series.apply(_is_descriptive_sec_asset, axis=1)].copy()
    candidates["_ticker"] = candidates["series_name"].map(_ticker_from_series)
    candidates = candidates[~candidates["_ticker"].isin(existing_tickers)]
    candidates["_quality"] = candidates.apply(
        lambda row: (
            1 if _norm(row.get("asset_name")) and not _norm(row.get("asset_name")).startswith("series #") else 0
        )
        + (1 if (_num(row.get("shares")) or 0) >= 100 else 0)
        + (1 if (_num(row.get("offering_price")) or 0) < 10000 else 0)
        + (1 if _norm(row.get("status")) == "exit" else 0),
        axis=1,
    )
    candidates = candidates.sort_values(["_ticker", "_quality"]).drop_duplicates(subset=["_ticker"], keep="last")

    for _, sec in candidates.iterrows():
        ticker = sec["_ticker"]
        parsed = parse_collectible_title(sec.get("asset_name"))
        category = infer_rally_category(sec.get("asset_name"))
        exit_row = _find_exit(pd.Series({"series_name": sec.get("series_name"), "asset_id": _sec_asset_id(ticker)}), exits)
        status_raw = _norm(sec.get("status"))
        status = "exited" if status_raw == "exit" or exit_row is not None else ("trading" if status_raw in {"closed", ""} else status_raw)
        offering_price = _num(sec.get("offering_price"))
        shares = _num(sec.get("shares"))
        rows.append(
            {
                "asset_id": _sec_asset_id(ticker),
                "ticker": ticker,
                "name": sec.get("asset_name") or sec.get("series_name"),
                "category": category,
                "subcategory": infer_rally_subcategory(sec.get("asset_name"), parsed, category),
                "brand": parsed["brand"] or ("Hermes" if category == "handbags" and any(word in _norm(sec.get("asset_name")) for word in SEC_HERMES_KEYWORDS) else ""),
                "model": parsed["model"],
                "year": parsed["year"],
                "size": parsed["size"],
                "material": parsed["material"],
                "color": parsed["color"],
                "hardware": parsed["hardware"],
                "offering_date": _date(sec.get("filing_date")),
                "offering_market_cap_usd": offering_price * shares if offering_price and shares else None,
                "current_market_cap_usd": None,
                "acquisition_cost_usd": _num(sec.get("acquisition_cost")),
                "last_trade_price": None,
                "bid_price": None,
                "ask_price": None,
                "share_count": shares,
                "sec_filing_url": sec.get("filing_url"),
                "status": status,
                "exit_date": _date(exit_row.get("sale_date")) if exit_row is not None else None,
                "exit_market_cap_usd": _num(exit_row.get("sale_price")) if exit_row is not None else None,
                "source_notes": "Synthesized from cached SEC offering tables; current live trading fields require Rally app/API data.",
            }
        )
    return rows


def build_rally_asset_universe(
    assets: pd.DataFrame,
    price_history: pd.DataFrame,
    sec_series: pd.DataFrame,
    exits: pd.DataFrame,
    *,
    include_sec_context: bool = False,
) -> pd.DataFrame:
    latest = _latest_prices(price_history)
    merged = assets.merge(latest, on="asset_id", how="left") if not assets.empty else pd.DataFrame()
    rows: list[dict] = []
    existing_tickers: set[str] = set()
    for _, asset in merged.iterrows():
        ticker = str(asset.get("ticker")).upper()
        existing_tickers.add(ticker)
        parsed = parse_collectible_title(asset.get("name"))
        sec = _find_sec_match(asset, sec_series)
        exit_row = _find_exit(asset, exits)
        shares = _num(sec.get("shares")) if sec is not None and _num(sec.get("shares")) else _num(asset.get("shares"))
        offering_price = _num(sec.get("offering_price")) if sec is not None and _num(sec.get("offering_price")) else _num(asset.get("offering_price"))
        market_cap = _num(asset.get("market_cap_usd")) or _num(asset.get("latest_market_cap_usd"))
        status_raw = _norm(asset.get("status")) or "trading"
        status = "trading" if status_raw in {"active", "live", "trading"} else status_raw
        if exit_row is not None:
            status = "exited"
        exit_price = _num(exit_row.get("exit_price_per_share")) if exit_row is not None else _num(asset.get("exit_price_per_share"))
        exit_value = _num(exit_row.get("exit_total_value")) if exit_row is not None else _num(asset.get("exit_value_total"))
        total_return = (
            exit_value / shares / offering_price - 1
            if exit_value and shares and offering_price
            else None
        )
        rows.append(
            {
                "asset_id": asset.get("asset_id"),
                "ticker": asset.get("ticker"),
                "name": asset.get("name"),
                "category": asset.get("category"),
                "subcategory": asset.get("subcategory"),
                "brand": parsed["brand"],
                "model": parsed["model"],
                "year": parsed["year"],
                "size": parsed["size"],
                "material": parsed["material"],
                "color": parsed["color"],
                "hardware": parsed["hardware"],
                "offering_date": _date(asset.get("offering_date")),
                "offering_market_cap_usd": offering_price * shares if offering_price and shares else None,
                "current_market_cap_usd": market_cap,
                "acquisition_cost_usd": _num(sec.get("acquisition_cost")) if sec is not None else None,
                "last_trade_price": _num(asset.get("last_trade_price")) or _num(asset.get("last_price_usd")),
                "bid_price": _num(asset.get("bid_price")),
                "ask_price": _num(asset.get("ask_price")),
                "share_count": shares,
                "sec_filing_url": sec.get("filing_url") if sec is not None else asset.get("source_url"),
                "status": status,
                "exit_date": _date(exit_row.get("sale_date")) if exit_row is not None else None,
                "exit_price_per_share": exit_price,
                "exit_market_cap_usd": exit_value,
                "total_return_at_exit": total_return,
                "source_notes": asset.get("notes") or asset.get("source_url"),
                **{field: asset.get(field) for field in RALLY_ASSET_COLUMNS if field.startswith("lifecycle_") or field.startswith("buyout_") or field in {"trading_state", "status_updated_at"}},
            }
        )
    if include_sec_context:
        rows.extend(_sec_asset_rows(sec_series, exits, existing_tickers))
    return pd.DataFrame(rows, columns=RALLY_ASSET_COLUMNS)


def build_comparable_sales_universe(comps: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, comp in comps.iterrows():
        title = _first(comp, "title", "notes", "subcategory") or ""
        parsed = parse_collectible_title(title, fallback_brand=comp.get("brand"))
        rows.append(
            {
                "comp_id": comp.get("comp_id"),
                "source": comp.get("source"),
                "auction_name": comp.get("auction_name"),
                "auction_url": _first(comp, "auction_url", "source_url"),
                "sale_date": _date(_first(comp, "date", "sale_date")),
                "brand": _first(comp, "brand") or parsed["brand"],
                "model": _first(comp, "model") or parsed["model"],
                "size": _first(comp, "size") or parsed["size"],
                "material": _first(comp, "material") or parsed["material"],
                "color": _first(comp, "color") or parsed["color"],
                "hardware": _first(comp, "hardware") or parsed["hardware"],
                "condition": comp.get("condition"),
                "year": _num(_first(comp, "year")) or parsed["year"],
                "estimate_low_usd": _num(comp.get("estimate_low_usd")),
                "estimate_high_usd": _num(comp.get("estimate_high_usd")),
                "realized_price_usd": _num(_first(comp, "price_usd", "realized_price_usd")),
                "currency": comp.get("currency") or "USD",
                "title": title,
                "lot_url": _first(comp, "lot_url", "source_url"),
                "raw_text_path": comp.get("raw_text_path"),
                "confidence_score": _num(_first(comp, "confidence_score", "exactness_score", "source_confidence")) or 0.5,
            }
        )
    out = pd.DataFrame(rows, columns=COMPARABLE_SALE_COLUMNS)
    if not out.empty:
        out["confidence_score"] = pd.to_numeric(out["confidence_score"], errors="coerce").fillna(0.5).clip(0, 1)
    return out


def _field_match(a: object, b: object) -> bool:
    return bool(_norm(a) and _norm(a) == _norm(b))


def similarity_score(asset: pd.Series, comp: pd.Series) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []
    weights = {
        "brand": 0.25,
        "model": 0.25,
        "size": 0.15,
        "material": 0.15,
        "color": 0.08,
        "hardware": 0.07,
    }
    for field, weight in weights.items():
        if _field_match(asset.get(field), comp.get(field)):
            score += weight
            matched.append(field)
    asset_year = _num(asset.get("year"))
    comp_year = _num(comp.get("year"))
    if asset_year and comp_year:
        distance = abs(asset_year - comp_year)
        if distance <= 2:
            score += 0.05
            matched.append("year")
        elif distance <= 10:
            score += max(0.01, 0.05 * (1 - distance / 10))
            matched.append("year_near")
    return round(min(score, 1.0), 4), matched


def match_assets_to_comps(rally_assets: pd.DataFrame, comps: pd.DataFrame, *, top_n: int = 20, min_score: float = 0.20) -> pd.DataFrame:
    rows: list[dict] = []
    priced = comps[pd.to_numeric(comps.get("realized_price_usd"), errors="coerce").notna()] if not comps.empty else comps
    for _, asset in rally_assets.iterrows():
        matches: list[dict] = []
        for _, comp in priced.iterrows():
            score, fields = similarity_score(asset, comp)
            if score >= min_score:
                matches.append(
                    {
                        "asset_id": asset.get("asset_id"),
                        "ticker": asset.get("ticker"),
                        "comp_id": comp.get("comp_id"),
                        "similarity_score": score,
                        "matched_fields": ", ".join(fields),
                        "realized_price_usd": _num(comp.get("realized_price_usd")),
                        "sale_date": comp.get("sale_date"),
                        "source": comp.get("source"),
                        "title": comp.get("title"),
                        "lot_url": comp.get("lot_url"),
                    }
                )
        matches = sorted(matches, key=lambda row: (row["similarity_score"], row["realized_price_usd"] or 0), reverse=True)[:top_n]
        for rank, row in enumerate(matches, start=1):
            row["rank"] = rank
            rows.append(row)
    return pd.DataFrame(rows, columns=ASSET_COMP_MATCH_COLUMNS)


def _weighted_average(values: pd.Series, weights: pd.Series) -> float | None:
    values = pd.to_numeric(values, errors="coerce")
    weights = pd.to_numeric(weights, errors="coerce").fillna(0)
    valid = values.notna() & (weights > 0)
    if not valid.any():
        return None
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def _momentum(asset_matches: pd.DataFrame, days: int, as_of: date) -> float | None:
    if asset_matches.empty:
        return None
    dated = asset_matches.copy()
    dated["sale_date"] = pd.to_datetime(dated["sale_date"], errors="coerce")
    dated = dated.dropna(subset=["sale_date", "realized_price_usd"])
    if len(dated) < 4:
        return None
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=days)
    recent = dated[dated["sale_date"] >= cutoff]["realized_price_usd"]
    prior = dated[dated["sale_date"] < cutoff]["realized_price_usd"]
    if len(recent) < 2 or len(prior) < 2:
        return None
    return float(recent.median() / prior.median() - 1) if prior.median() else None


def estimate_secondary_navs(rally_assets: pd.DataFrame, comps: pd.DataFrame, matches: pd.DataFrame, *, as_of: date | None = None) -> pd.DataFrame:
    as_of = as_of or date.today()
    comp_prices = comps.set_index("comp_id") if not comps.empty else pd.DataFrame()
    rows: list[dict] = []
    for _, asset in rally_assets.iterrows():
        asset_matches = matches[matches["asset_id"] == asset.get("asset_id")].copy() if not matches.empty else pd.DataFrame()
        if not asset_matches.empty and not comp_prices.empty:
            asset_matches = asset_matches.merge(comp_prices[["estimate_low_usd", "estimate_high_usd", "confidence_score"]], left_on="comp_id", right_index=True, how="left")
        prices = pd.to_numeric(asset_matches.get("realized_price_usd", pd.Series(dtype=float)), errors="coerce").dropna()
        weights = pd.to_numeric(asset_matches.get("similarity_score", pd.Series(dtype=float)), errors="coerce").fillna(0)
        confidence = pd.to_numeric(asset_matches.get("confidence_score", pd.Series(dtype=float)), errors="coerce").fillna(0.5)
        estimate_mid = None
        if not asset_matches.empty and {"estimate_low_usd", "estimate_high_usd"}.issubset(asset_matches.columns):
            estimate_mid = (pd.to_numeric(asset_matches["estimate_low_usd"], errors="coerce") + pd.to_numeric(asset_matches["estimate_high_usd"], errors="coerce")) / 2
        estimate_weight = weights * confidence
        if estimate_mid is not None:
            estimate_weight = estimate_weight * estimate_mid.notna().map({True: 1.1, False: 1.0})
        weighted_value = _weighted_average(asset_matches.get("realized_price_usd", pd.Series(dtype=float)), estimate_weight) if not asset_matches.empty else None
        median_value = float(prices.median()) if not prices.empty else None
        mean_value = float(prices.mean()) if not prices.empty else None
        estimated_nav = weighted_value or median_value or mean_value
        nav_low = float(prices.quantile(0.25)) if len(prices) >= 4 else (float(prices.min()) if not prices.empty else None)
        nav_high = float(prices.quantile(0.75)) if len(prices) >= 4 else (float(prices.max()) if not prices.empty else None)
        avg_similarity = float(weights.mean()) if not weights.empty else 0.0
        avg_confidence = float(confidence.mean()) if not confidence.empty else 0.0
        nav_confidence = round(min(0.95, avg_similarity * avg_confidence * min(1.0, len(prices) / 5)), 4) if len(prices) else 0.0
        current_cap = _num(asset.get("current_market_cap_usd"))
        offering_cap = _num(asset.get("offering_market_cap_usd"))
        discount = current_cap / estimated_nav - 1 if current_cap and estimated_nav else None
        premium = current_cap / offering_cap - 1 if current_cap and offering_cap else None
        bid = _num(asset.get("bid_price"))
        ask = _num(asset.get("ask_price"))
        spread = (ask - bid) / ((ask + bid) / 2) if bid and ask and ask >= bid else None
        liquidity_score = round(max(0.1, min(0.9, 0.65 - (spread or 0.20))), 4)
        if estimated_nav and len(prices):
            cheapness = max(0.0, -(discount or 0.0))
            expensive_penalty = max(0.0, discount or 0.0) * 0.25
            mispricing_score = round(max(0.0, min(100.0, cheapness * 70 + nav_confidence * 25 + liquidity_score * 5 - expensive_penalty * 30)), 2)
        else:
            mispricing_score = 0.0
        rows.append(
            {
                **asset.to_dict(),
                "comp_count": int(len(prices)),
                "top_comp_count": int(len(asset_matches)),
                "median_comp_sale_usd": median_value,
                "mean_comp_sale_usd": mean_value,
                "estimate_weighted_value_usd": weighted_value,
                "estimated_nav_usd": estimated_nav,
                "nav_low_usd": nav_low,
                "nav_high_usd": nav_high,
                "nav_confidence": nav_confidence,
                "discount_to_secondary_nav": discount,
                "premium_to_offering": premium,
                "rally_return_since_offering": premium,
                "comp_market_momentum_90d": _momentum(asset_matches, 90, as_of),
                "comp_market_momentum_180d": _momentum(asset_matches, 180, as_of),
                "comp_market_momentum_365d": _momentum(asset_matches, 365, as_of),
                "liquidity_score": liquidity_score,
                "mispricing_score": mispricing_score,
            }
        )
    return pd.DataFrame(rows, columns=DECISION_COLUMNS)


def build_data_diagnostics(rally_assets: pd.DataFrame, comps: pd.DataFrame, decision: pd.DataFrame, import_errors_path: Path) -> pd.DataFrame:
    invalid_rows = pd.read_csv(import_errors_path) if import_errors_path.exists() else pd.DataFrame()
    duplicate_keys = comps.duplicated(subset=["source", "auction_name", "title", "sale_date", "realized_price_usd"], keep=False) if not comps.empty else pd.Series(dtype=bool)
    rows = [
        {"metric": "rally_assets", "value": len(rally_assets), "notes": "Unified Rally investable asset rows"},
        {"metric": "comparable_sales", "value": len(comps), "notes": "Unified comparable sale rows"},
        {"metric": "assets_with_no_comps", "value": int((decision.get("comp_count", pd.Series(dtype=float)).fillna(0) == 0).sum()), "notes": "Rally assets without matched realized sale comps"},
        {"metric": "comps_missing_sale_price", "value": int(comps.get("realized_price_usd", pd.Series(dtype=float)).isna().sum()), "notes": "Comps missing realized sale price"},
        {"metric": "comps_missing_estimate", "value": int((comps.get("estimate_low_usd", pd.Series(dtype=float)).isna() | comps.get("estimate_high_usd", pd.Series(dtype=float)).isna()).sum()), "notes": "Comps missing estimate low or high"},
        {
            "metric": "comps_missing_size_material_color",
            "value": int((comps.get("size", pd.Series(dtype=str)).fillna("").eq("") | comps.get("material", pd.Series(dtype=str)).fillna("").eq("") | comps.get("color", pd.Series(dtype=str)).fillna("").eq("")).sum()),
            "notes": "Comps missing at least one matching attribute",
        },
        {"metric": "rows_with_invalid_dates", "value": len(invalid_rows), "notes": str(import_errors_path)},
        {"metric": "duplicate_possible_lots", "value": int(duplicate_keys.sum()), "notes": "Same source, auction, title, date, and sale price"},
    ]
    return pd.DataFrame(rows, columns=DIAGNOSTIC_COLUMNS)


def build_ai_report_context(decision: pd.DataFrame, matches: pd.DataFrame, diagnostics: pd.DataFrame, *, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    ranked = decision.sort_values("mispricing_score", ascending=False).head(20) if not decision.empty else pd.DataFrame()
    return {
        "as_of": as_of.isoformat(),
        "purpose": "Rally-first alternative asset universe with secondary comp NAV support.",
        "diagnostics": diagnostics.to_dict(orient="records"),
        "top_assets": ranked.to_dict(orient="records"),
        "match_counts": matches.groupby("ticker").size().reset_index(name="matched_comp_count").to_dict(orient="records") if not matches.empty else [],
    }


def write_ai_report_context(context: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, indent=2, default=str), encoding="utf-8")
