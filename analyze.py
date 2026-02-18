import os
import pandas as pd
from datetime import timedelta

# ── Configurações ────────────────────────────────────────────────────────────
DATA_CACHE_DIR = "data_cache"
SIGNALS_DIR    = "signals"

THRESHOLDS     = [0.01, 0.02]               # 1% e 2%

# Stops finos: aplicados sobre o preço de entrada
FINE_SL        = [0.0020, 0.0050, 0.0075]  # 0.20%, 0.50%, 0.75%
FINE_SG        = [0.0020, 0.0050, 0.0075]

# Stops amplos: aplicados sobre o preço de entrada
BROAD_SL       = [0.10, 0.25, 0.50]        # 10%, 25%, 50%
BROAD_SG       = [0.10, 0.25, 0.50, 1.00]  # 10%, 25%, 50%, 100%
# ─────────────────────────────────────────────────────────────────────────────


def _stop_levels(entry: float, direction: str) -> dict:
    """Calcula todos os níveis de stop loss e stop gain para uma entrada."""
    sign_sl = +1 if direction == "SELL" else -1  # SL vai contra a posição
    sign_sg = -1 if direction == "SELL" else +1  # SG vai a favor

    result = {}
    for pct in FINE_SL:
        label = f"SL_{pct*100:.2f}pct".replace(".", "_")
        result[label] = round(entry * (1 + sign_sl * pct), 2)
    for pct in FINE_SG:
        label = f"SG_{pct*100:.2f}pct".replace(".", "_")
        result[label] = round(entry * (1 + sign_sg * pct), 2)
    for pct in BROAD_SL:
        label = f"SL_{int(pct*100)}pct"
        result[label] = round(entry * (1 + sign_sl * pct), 2)
    for pct in BROAD_SG:
        label = f"SG_{int(pct*100)}pct"
        result[label] = round(entry * (1 + sign_sg * pct), 2)
    return result


def _make_signal(ticker, analysis_type, ref_price, ref_datetime,
                 today_open, direction, threshold_pct) -> dict:
    """Monta o dict de um sinal e anexa os stops."""
    entry = today_open
    row = {
        "Ticker":          ticker,
        "Analysis_Type":   analysis_type,
        "Reference_Price": round(ref_price, 2),
        "Reference_DT":    ref_datetime,
        "Today_Open":      round(today_open, 2),
        "Signal":          direction,
        "Threshold_pct":   f"{int(threshold_pct*100)}%",
        "Entry_Price":     round(entry, 2),
    }
    row.update(_stop_levels(entry, direction))
    return row


def _check_signals(ticker, analysis_type, ref_price, ref_datetime, today_open) -> list:
    """Verifica se hoje_open cruza algum threshold em relação a ref_price."""
    signals = []
    for thr in THRESHOLDS:
        sell_level = ref_price * (1 + thr)
        buy_level  = ref_price * (1 - thr)
        if today_open >= sell_level:
            signals.append(_make_signal(
                ticker, analysis_type, ref_price, ref_datetime,
                today_open, "SELL", thr
            ))
        if today_open <= buy_level:
            signals.append(_make_signal(
                ticker, analysis_type, ref_price, ref_datetime,
                today_open, "BUY", thr
            ))
    return signals


def analyze_ticker(ticker: str, df: pd.DataFrame) -> list:
    """Executa todas as análises para um ticker e retorna lista de sinais."""
    df = df.copy()
    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["Datetime"]).sort_values("Datetime")

    today      = pd.Timestamp.now(tz=None).normalize()
    yesterday  = today - timedelta(days=1)

    # Busca o dia de hoje e o dia anterior com dados
    today_df  = df[df["Datetime"].dt.normalize() == today]
    prev_df   = df[df["Datetime"].dt.normalize() < today]

    if prev_df.empty:
        print(f"[ANALYZE] {ticker}: sem dados de dias anteriores.")
        return []

    # Dia de negociação anterior (último dia com dados)
    last_trade_day = prev_df["Datetime"].dt.normalize().max()
    prev_day_df    = prev_df[prev_df["Datetime"].dt.normalize() == last_trade_day]

    if today_df.empty:
        print(f"[ANALYZE] {ticker}: sem dados de hoje ({today.date()}).")
        return []

    today_open     = today_df.iloc[0]["Open"]
    today_open_dt  = today_df.iloc[0]["Datetime"]

    if pd.isna(today_open):
        return []

    signals = []

    # ── 2.1  Abertura de hoje vs. abertura do dia anterior ───────────────────
    prev_open    = prev_day_df.iloc[0]["Open"]
    prev_open_dt = prev_day_df.iloc[0]["Datetime"]
    if not pd.isna(prev_open):
        signals += _check_signals(
            ticker, "open_vs_prev_open",
            prev_open, prev_open_dt, today_open
        )

    # ── 2.2  Abertura de hoje vs. fechamento do dia anterior ─────────────────
    prev_close    = prev_day_df.iloc[-1]["Close"]
    prev_close_dt = prev_day_df.iloc[-1]["Datetime"]
    if not pd.isna(prev_close):
        signals += _check_signals(
            ticker, "open_vs_prev_close",
            prev_close, prev_close_dt, today_open
        )

    # ── 2.3  Abertura de hoje vs. hora de maior alta do dia anterior ─────────
    max_high_idx = prev_day_df["High"].idxmax()
    max_high_row = prev_day_df.loc[max_high_idx]
    if not pd.isna(max_high_row["High"]):
        signals += _check_signals(
            ticker, "open_vs_prev_max_high",
            max_high_row["High"], max_high_row["Datetime"], today_open
        )

    # ── 2.8  Abertura de hoje vs. hora de menor baixa do dia anterior ──────────
    min_low_idx = prev_day_df["Low"].idxmin()
    min_low_row = prev_day_df.loc[min_low_idx]
    if not pd.isna(min_low_row["Low"]):
        signals += _check_signals(
            ticker, "open_vs_prev_min_low",
            min_low_row["Low"], min_low_row["Datetime"], today_open
        )

    # ── 2.7  Abertura de hoje vs. Close da hora de maior volume do dia ant. ──
    max_vol_idx = prev_day_df["Volume"].idxmax()
    max_vol_row = prev_day_df.loc[max_vol_idx]
    if not pd.isna(max_vol_row["Close"]):
        signals += _check_signals(
            ticker, "open_vs_prev_max_vol_close",
            max_vol_row["Close"], max_vol_row["Datetime"], today_open
        )

    return signals


def run_analysis(data_cache_dir=DATA_CACHE_DIR, signals_dir=SIGNALS_DIR):
    os.makedirs(signals_dir, exist_ok=True)

    all_signals = []

    for fname in os.listdir(data_cache_dir):
        if not (fname.startswith("price_") and fname.endswith(".csv")):
            continue
        ticker = fname.replace("price_", "").replace(".csv", "").upper()
        path   = os.path.join(data_cache_dir, fname)
        try:
            df = pd.read_csv(path, parse_dates=["Datetime"])
            ticker_signals = analyze_ticker(ticker, df)
            if ticker_signals:
                all_signals.extend(ticker_signals)
                print(f"[ANALYZE] {ticker}: {len(ticker_signals)} sinal(is) encontrado(s).")
            else:
                print(f"[ANALYZE] {ticker}: nenhum sinal.")
        except Exception as e:
            print(f"[ANALYZE][WARN] Falha ao analisar {ticker}: {e}")

    if all_signals:
        today_str  = pd.Timestamp.now().strftime("%Y-%m-%d")
        out_path   = os.path.join(signals_dir, f"signals_{today_str}.csv")
        result_df  = pd.DataFrame(all_signals)
        result_df.to_csv(out_path, index=False)
        print(f"\n[ANALYZE] {len(all_signals)} sinal(is) salvos em: {out_path}")
    else:
        print("\n[ANALYZE] Nenhum sinal gerado hoje.")

    return all_signals


if __name__ == "__main__":
    run_analysis()
