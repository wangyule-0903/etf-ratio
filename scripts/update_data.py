#!/usr/bin/env python3
"""Fetch ChiNext ETF / Dividend ETF prices and write ratio dashboard data."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

# 创业板 ETF / 红利 ETF
CHINEXT = {"code": "159915", "name": "创业板ETF", "secid": "0.159915"}
DIVIDEND = {"code": "510880", "name": "红利ETF", "secid": "1.510880"}

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "docs" / "data.json"

CST = timezone(timedelta(hours=8))


def fetch_etf_history(secid: str) -> pd.DataFrame:
    """Pull daily adjusted close from East Money."""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "beg": "20100101",
        "end": "20500101",
        "lmt": "1000000",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        raise RuntimeError(f"No kline data for secid={secid}: {payload}")

    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append({"date": parts[0], "close": float(parts[2])})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def percentile_rank(series: pd.Series, value: float) -> float:
    """Percent of historical observations strictly below current value."""
    clean = series.dropna()
    if clean.empty:
        return float("nan")
    return float((clean < value).mean() * 100)


def verdict_from_percentile(pct: float) -> dict:
    """
    Ratio = ChiNext / Dividend.
    High percentile => ChiNext relatively expensive / Dividend relatively cheap.
    """
    if math.isnan(pct):
        return {
            "label": "数据不足",
            "cheap": None,
            "expensive": None,
            "bias": "unknown",
            "hint": "历史数据不足，暂无法判断。",
        }
    if pct >= 80:
        return {
            "label": "创业板相对高估 · 红利相对低估",
            "cheap": "红利ETF",
            "expensive": "创业板ETF",
            "bias": "dividend",
            "hint": "比值处于历史高位，风格上更偏向红利ETF。",
        }
    if pct <= 20:
        return {
            "label": "创业板相对低估 · 红利相对高估",
            "cheap": "创业板ETF",
            "expensive": "红利ETF",
            "bias": "chinext",
            "hint": "比值处于历史低位，风格上更偏向创业板ETF。",
        }
    return {
        "label": "相对均衡",
        "cheap": None,
        "expensive": None,
        "bias": "neutral",
        "hint": "比值处于中间区间，可维持均衡配置或观望。",
    }


def build_payload() -> dict:
    chin_df = fetch_etf_history(CHINEXT["secid"]).rename(columns={"close": "chinext"})
    div_df = fetch_etf_history(DIVIDEND["secid"]).rename(columns={"close": "dividend"})
    merged = chin_df.join(div_df, how="inner").dropna()
    if merged.empty:
        raise RuntimeError("No overlapping trading days between the two ETFs")

    merged["ratio"] = merged["chinext"] / merged["dividend"]
    latest = merged.iloc[-1]
    pct = percentile_rank(merged["ratio"], float(latest["ratio"]))
    verdict = verdict_from_percentile(pct)

    # Keep chart light for mobile: last ~10 years daily points is fine (~2500)
    chart_df = merged.tail(2600)
    history = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "ratio": round(float(row.ratio), 4),
            "chinext": round(float(row.chinext), 3),
            "dividend": round(float(row.dividend), 3),
        }
        for idx, row in chart_df.iterrows()
    ]

    now = datetime.now(CST)
    return {
        "updatedAt": now.isoformat(timespec="seconds"),
        "asOf": latest.name.strftime("%Y-%m-%d"),
        "pair": {
            "numerator": CHINEXT,
            "denominator": DIVIDEND,
            "formula": f"{CHINEXT['name']} ÷ {DIVIDEND['name']}",
        },
        "latest": {
            "ratio": round(float(latest["ratio"]), 4),
            "chinext": round(float(latest["chinext"]), 3),
            "dividend": round(float(latest["dividend"]), 3),
            "percentile": round(pct, 1),
        },
        "stats": {
            "days": int(len(merged)),
            "start": merged.index.min().strftime("%Y-%m-%d"),
            "end": merged.index.max().strftime("%Y-%m-%d"),
            "min": round(float(merged["ratio"].min()), 4),
            "max": round(float(merged["ratio"].max()), 4),
            "median": round(float(merged["ratio"].median()), 4),
            "p20": round(float(merged["ratio"].quantile(0.2)), 4),
            "p80": round(float(merged["ratio"].quantile(0.8)), 4),
        },
        "thresholds": {"low": 20, "high": 80},
        "verdict": verdict,
        "history": history,
    }


def main() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    DATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Wrote {DATA_PATH} | asOf={payload['asOf']} "
        f"ratio={payload['latest']['ratio']} "
        f"pct={payload['latest']['percentile']}% "
        f"verdict={payload['verdict']['label']}"
    )


if __name__ == "__main__":
    main()
