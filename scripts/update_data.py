#!/usr/bin/env python3
"""Fetch ChiNext / CSI Dividend index prices and write ratio dashboard data."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests

# 创业板指数 / 中证红利指数
CHINEXT = {
    "code": "399006",
    "name": "创业板指数",
    "secid": "0.399006",
    "tx": "sz399006",
}
DIVIDEND = {
    "code": "000922",
    "name": "中证红利",
    "secid": "1.000922",
    "tx": "sh000922",
}

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "docs" / "data.json"

CST = timezone(timedelta(hours=8))
SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
)


def _parse_tx_rows(rows: list) -> pd.DataFrame:
    """Tencent day row: date, open, close, high, low, volume."""
    records = []
    for row in rows:
        if not row or len(row) < 3:
            continue
        records.append({"date": row[0], "close": float(row[2])})
    if not records:
        return pd.DataFrame(columns=["close"]).rename_axis("date")
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates("date").set_index("date").sort_index()


def fetch_tencent_chunk(tx_code: str, start: str, end: str, limit: int = 2000) -> list:
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{tx_code},day,{start},{end},{limit},"}
    resp = SESSION.get(url, params=params, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    node = (payload.get("data") or {}).get(tx_code) or {}
    return node.get("day") or node.get("qfqday") or []


def fetch_tencent_history(tx_code: str, retries: int = 5) -> pd.DataFrame:
    """Pull daily closes from Tencent in date chunks."""
    windows = [
        ("2010-01-01", "2014-12-31"),
        ("2015-01-01", "2018-12-31"),
        ("2019-01-01", "2022-12-31"),
        ("2023-01-01", "2050-01-01"),
    ]
    last_error: Exception | None = None
    frames: list[pd.DataFrame] = []

    for start, end in windows:
        for attempt in range(1, retries + 1):
            try:
                rows = fetch_tencent_chunk(tx_code, start, end)
                if not rows:
                    # Fallback single-shot recent history endpoint
                    url = (
                        "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
                        f"?param={tx_code},day,,,2000,"
                    )
                    resp = SESSION.get(url, timeout=60)
                    resp.raise_for_status()
                    node = (resp.json().get("data") or {}).get(tx_code) or {}
                    rows = node.get("day") or []
                part = _parse_tx_rows(rows)
                if not part.empty:
                    frames.append(part)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                sleep_s = min(2**attempt, 20)
                print(
                    f"[warn] tencent {tx_code} {start}~{end} "
                    f"attempt {attempt}/{retries} failed: {exc}; sleep {sleep_s}s"
                )
                time.sleep(sleep_s)
        else:
            raise RuntimeError(
                f"Failed to fetch {tx_code} window {start}~{end}"
            ) from last_error

    if not frames:
        raise RuntimeError(f"No tencent data for {tx_code}") from last_error

    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def fetch_eastmoney_history(secid: str, retries: int = 3) -> pd.DataFrame:
    """Fallback: East Money kline API."""
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
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = SESSION.get(url, params=params, headers=headers, timeout=90)
            resp.raise_for_status()
            payload = resp.json()
            klines = (payload.get("data") or {}).get("klines") or []
            if not klines:
                raise RuntimeError(f"No kline data for secid={secid}")
            rows = []
            for line in klines:
                parts = line.split(",")
                rows.append({"date": parts[0], "close": float(parts[2])})
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date").sort_index()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"East Money failed for {secid}") from last_error


def fetch_index_history(meta: dict) -> pd.DataFrame:
    try:
        return fetch_tencent_history(meta["tx"])
    except Exception as tx_err:
        print(f"[warn] tencent failed for {meta['code']}: {tx_err}; try eastmoney")
        return fetch_eastmoney_history(meta["secid"])


def percentile_rank(series: pd.Series, value: float) -> float:
    clean = series.dropna()
    if clean.empty:
        return float("nan")
    return float((clean < value).mean() * 100)


def verdict_from_percentile(pct: float) -> dict:
    """
    Ratio = ChiNext / CSI Dividend.
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
            "label": "创业板相对高估 · 中证红利相对低估",
            "cheap": "中证红利",
            "expensive": "创业板指数",
            "bias": "dividend",
            "hint": "比值处于历史高位，风格上更偏向中证红利。",
        }
    if pct <= 20:
        return {
            "label": "创业板相对低估 · 中证红利相对高估",
            "cheap": "创业板指数",
            "expensive": "中证红利",
            "bias": "chinext",
            "hint": "比值处于历史低位，风格上更偏向创业板指数。",
        }
    return {
        "label": "相对均衡",
        "cheap": None,
        "expensive": None,
        "bias": "neutral",
        "hint": "比值处于中间区间，可维持均衡配置或观望。",
    }


def build_payload() -> dict:
    chin_df = fetch_index_history(CHINEXT).rename(columns={"close": "chinext"})
    div_df = fetch_index_history(DIVIDEND).rename(columns={"close": "dividend"})
    merged = chin_df.join(div_df, how="inner").dropna()
    if merged.empty:
        raise RuntimeError("No overlapping trading days between the two indices")

    merged["ratio"] = merged["chinext"] / merged["dividend"]
    latest = merged.iloc[-1]
    pct = percentile_rank(merged["ratio"], float(latest["ratio"]))
    verdict = verdict_from_percentile(pct)

    chart_df = merged.tail(2600)
    history = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "ratio": round(float(row.ratio), 4),
            "chinext": round(float(row.chinext), 2),
            "dividend": round(float(row.dividend), 2),
        }
        for idx, row in chart_df.iterrows()
    ]

    now = datetime.now(CST)
    return {
        "updatedAt": now.isoformat(timespec="seconds"),
        "asOf": latest.name.strftime("%Y-%m-%d"),
        "pair": {
            "numerator": {
                "code": CHINEXT["code"],
                "name": CHINEXT["name"],
                "secid": CHINEXT["secid"],
            },
            "denominator": {
                "code": DIVIDEND["code"],
                "name": DIVIDEND["name"],
                "secid": DIVIDEND["secid"],
            },
            "formula": f"{CHINEXT['name']} ÷ {DIVIDEND['name']}",
        },
        "latest": {
            "ratio": round(float(latest["ratio"]), 4),
            "chinext": round(float(latest["chinext"]), 2),
            "dividend": round(float(latest["dividend"]), 2),
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
