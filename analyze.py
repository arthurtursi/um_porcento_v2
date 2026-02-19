import os
import pandas as pd
from datetime import timedelta, datetime
from utils_date import is_dia_util, ajustar_para_dia_util

# ── Configurações ────────────────────────────────────────────────────────────
DATA_CACHE_DIR  = "data_cache"
SIGNALS_DIR     = "signals"
BACKTEST_DIR    = "backtest"

THRESHOLDS     = [0.01, 0.02]               # 1% e 2%

# Stops finos: aplicados sobre o preço de entrada
FINE_SL        = [0.0020, 0.0050, 0.0075, 0.0100]  # 0.20%, 0.50%, 0.75%, 1.00%
FINE_SG        = [0.0020, 0.0050, 0.0075, 0.0100]

# Todas as combinações (SL, SG) — 4×4 = 16 pares
STOP_PAIRS     = [(sl, sg) for sl in FINE_SL for sg in FINE_SG]

# Chaveamentos / feature flags
#   USE_TREND_FILTER: lista de valores a testar simultaneamente.
#     [False]        → sem filtro (comportamento original)
#     [True]         → só com filtro MM20
#     [False, True]  → gera ambas as variantes no mesmo backtest;
#                      Analysis_Type recebe sufixo _trend_off / _trend_on
USE_TREND_FILTER  = [False, True]
MM20_WINDOW       = 20     # janela (dias) da média móvel de tendência
#   USE_ENTRY_WINDOW: lista de valores a testar simultaneamente.
#     [False]        → aceita entradas até 16h (comportamento original)
#     [True]         → só até ENTRY_HOUR_END
#     [False, True]  → gera ambas as variantes no mesmo backtest;
#                      Analysis_Type recebe sufixo _ew_off / _ew_on
USE_ENTRY_WINDOW  = [False, True]
ENTRY_HOUR_START  = 9
ENTRY_HOUR_END    = 10

# ─────────────────────────────────────────────────────────────────────────────


def _stop_levels(entry: float, direction: str, sl_pct: float, sg_pct: float) -> dict:
    """Calcula níveis de stop loss e stop gain para um par (sl_pct, sg_pct) específico."""
    sign_sl = +1 if direction == "SELL" else -1  # SL vai contra a posição
    sign_sg = -1 if direction == "SELL" else +1  # SG vai a favor
    return {
        "SL_pct":   sl_pct,
        "SG_pct":   sg_pct,
        "SL_price": round(entry * (1 + sign_sl * sl_pct), 2),
        "SG_price": round(entry * (1 + sign_sg * sg_pct), 2),
    }


def _make_signal(ticker, analysis_type, ref_price, ref_datetime,
                 entry_price, entry_dt, direction, threshold_pct,
                 sl_pct, sg_pct,
                 signal_date=None, natural_sg=None) -> dict:
    """Monta o dict de um sinal para um par de stops (sl_pct, sg_pct) específico."""
    row = {
        "Signal_Date":     pd.Timestamp(signal_date).strftime("%Y-%m-%d") if signal_date is not None else None,
        "Ticker":          ticker,
        "Analysis_Type":   analysis_type,
        "Reference_Price": round(ref_price, 2),
        "Reference_DT":    ref_datetime,
        "Signal":          direction,
        "Threshold_pct":   f"{int(threshold_pct*100)}%",
        "Entry_Price":     round(entry_price, 2),
        "Entry_DT":        entry_dt,
        # SG natural = ref_price (alvo de reversão à média)
        "SG_Natural":      round(natural_sg, 2) if natural_sg is not None else None,
    }
    row.update(_stop_levels(entry_price, direction, sl_pct, sg_pct))
    return row


def _check_signals(ticker, analysis_type, ref_price, ref_datetime,
                   today_candles: pd.DataFrame,
                   signal_date=None, only_signal=None, natural_sg=None) -> list:
    """
    Varre todos os candles do dia e gera um sinal para cada threshold cruzado,
    usando o PRIMEIRO candle em que High (SELL) ou Low (BUY) atinge o nível.

    only_signal : 'BUY' ou 'SELL' para restringir direção.
    natural_sg  : preço-alvo de reversão (ex: ref_price para min_low/max_high).
    """
    signals = []
    for thr in THRESHOLDS:
        sell_level = round(ref_price * (1 + thr), 2)
        buy_level  = round(ref_price * (1 - thr), 2)

        if only_signal != "BUY":
            # Primeiro candle cujo High >= sell_level
            hit = today_candles[today_candles["High"] >= sell_level]
            if not hit.empty:
                candle = hit.iloc[0]
                for sl_pct, sg_pct in STOP_PAIRS:
                    signals.append(_make_signal(
                        ticker, analysis_type, ref_price, ref_datetime,
                        sell_level, candle["Datetime"],
                        "SELL", thr, sl_pct, sg_pct,
                        signal_date=signal_date, natural_sg=natural_sg
                    ))

        if only_signal != "SELL":
            # Primeiro candle cujo Low <= buy_level
            hit = today_candles[today_candles["Low"] <= buy_level]
            if not hit.empty:
                candle = hit.iloc[0]
                for sl_pct, sg_pct in STOP_PAIRS:
                    signals.append(_make_signal(
                        ticker, analysis_type, ref_price, ref_datetime,
                        buy_level, candle["Datetime"],
                        "BUY", thr, sl_pct, sg_pct,
                        signal_date=signal_date, natural_sg=natural_sg
                    ))
    return signals


def analyze_ticker(ticker: str, df: pd.DataFrame, ref_date: pd.Timestamp = None) -> list:
    """Executa todas as análises para um ticker em uma data de referência.

    ref_date: o dia simulado como 'hoje'. Default = hoje real.
    """
    df = df.copy()
    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["Datetime"]).sort_values("Datetime")

    if ref_date is None:
        ref_date = pd.Timestamp.now(tz=None).normalize()
    today = pd.Timestamp(ref_date).normalize()

    # Busca o dia de referência e os dias anteriores
    today_df  = df[df["Datetime"].dt.normalize() == today]
    prev_df   = df[df["Datetime"].dt.normalize() < today]

    if prev_df.empty:
        return [], 0

    # Dia de negociação anterior (último dia com dados)
    last_trade_day = prev_df["Datetime"].dt.normalize().max()
    prev_day_df    = prev_df[prev_df["Datetime"].dt.normalize() == last_trade_day]

    if today_df.empty:
        return [], 0

    today_open     = today_df.iloc[0]["Open"]
    today_open_dt  = today_df.iloc[0]["Datetime"]

    if pd.isna(today_open):
        return [], 0

    signals = []

    _ew_variants    = USE_ENTRY_WINDOW if isinstance(USE_ENTRY_WINDOW, list) else [USE_ENTRY_WINDOW]
    _multi_ew       = isinstance(USE_ENTRY_WINDOW, list) and len(_ew_variants) > 1
    _trend_variants = USE_TREND_FILTER if isinstance(USE_TREND_FILTER, list) else [USE_TREND_FILTER]
    _multi_trend    = isinstance(USE_TREND_FILTER, list) and len(_trend_variants) > 1

    for _use_ew in _ew_variants:
        ew_tag         = ("_ew_on" if _use_ew else "_ew_off") if _multi_ew else ""
        entry_hour_end = ENTRY_HOUR_END if _use_ew else 16
        today_candles  = today_df[
            (today_df["Datetime"].dt.hour >= ENTRY_HOUR_START) &
            (today_df["Datetime"].dt.hour <= entry_hour_end)
        ].copy()

        # ── 2.3  Abertura de hoje vs. hora de maior alta do dia anterior ─────────
        # (direção fixa SELL — não afetada pelo filtro de tendência)
        max_high_idx = prev_day_df["High"].idxmax()
        max_high_row = prev_day_df.loc[max_high_idx]
        if not pd.isna(max_high_row["High"]):
            signals += _check_signals(
                ticker, "open_vs_prev_max_high" + ew_tag,
                max_high_row["High"], max_high_row["Datetime"], today_candles,
                signal_date=today, only_signal="SELL",
                natural_sg=max_high_row["High"]
            )

        # ── 2.8  Abertura de hoje vs. hora de menor baixa do dia anterior ─────────
        # (direção fixa BUY — não afetada pelo filtro de tendência)
        min_low_idx = prev_day_df["Low"].idxmin()
        min_low_row = prev_day_df.loc[min_low_idx]
        if not pd.isna(min_low_row["Low"]):
            signals += _check_signals(
                ticker, "open_vs_prev_min_low" + ew_tag,
                min_low_row["Low"], min_low_row["Datetime"], today_candles,
                signal_date=today, only_signal="BUY",
                natural_sg=min_low_row["Low"]
            )

        # ── Estratégias afetadas pelo filtro de tendência ─────────────────────────
        for _use_trend in _trend_variants:
            trend_tag  = ("_trend_on" if _use_trend else "_trend_off") if _multi_trend else ""
            full_tag   = trend_tag + ew_tag
            trend_bias = None

            if _use_trend:
                daily_closes = (
                    prev_df.groupby(prev_df["Datetime"].dt.normalize())["Close"]
                    .last()
                    .sort_index()
                )
                if len(daily_closes) >= MM20_WINDOW:
                    mm20 = daily_closes.iloc[-MM20_WINDOW:].mean()
                    trend_bias = "BUY" if today_open > mm20 else "SELL"

            # 2.1  Abertura de hoje vs. abertura do dia anterior
            prev_open    = prev_day_df.iloc[0]["Open"]
            prev_open_dt = prev_day_df.iloc[0]["Datetime"]
            if not pd.isna(prev_open):
                signals += _check_signals(
                    ticker, "open_vs_prev_open" + full_tag,
                    prev_open, prev_open_dt, today_candles, signal_date=today,
                    only_signal=trend_bias
                )

            # 2.2  Abertura de hoje vs. fechamento do dia anterior
            prev_close    = prev_day_df.iloc[-1]["Close"]
            prev_close_dt = prev_day_df.iloc[-1]["Datetime"]
            if not pd.isna(prev_close):
                signals += _check_signals(
                    ticker, "open_vs_prev_close" + full_tag,
                    prev_close, prev_close_dt, today_candles, signal_date=today,
                    only_signal=trend_bias
                )

            # 2.7  Abertura de hoje vs. Close da hora de maior volume do dia ant.
            max_vol_idx = prev_day_df["Volume"].idxmax()
            max_vol_row = prev_day_df.loc[max_vol_idx]
            if not pd.isna(max_vol_row["Close"]):
                signals += _check_signals(
                    ticker, "open_vs_prev_max_vol_close" + full_tag,
                    max_vol_row["Close"], max_vol_row["Datetime"], today_candles, signal_date=today,
                    only_signal=trend_bias
                )

            # 2.6  Abertura de hoje vs. VWAP do dia anterior
            vol_sum = prev_day_df["Volume"].sum()
            if vol_sum > 0:
                typical     = (prev_day_df["High"] + prev_day_df["Low"] + prev_day_df["Close"]) / 3
                vwap        = (typical * prev_day_df["Volume"]).sum() / vol_sum
                vwap_ref_dt = prev_day_df.iloc[-1]["Datetime"]
                if not pd.isna(vwap):
                    signals += _check_signals(
                        ticker, "open_vs_prev_vwap" + full_tag,
                        vwap, vwap_ref_dt, today_candles, signal_date=today,
                        only_signal=trend_bias
                    )

    # ── Dedup: por (analysis_type, direction, threshold_pct) só o primeiro candle ativado vence
    # Ordena pelo Entry_DT para garantir que o mais cedo leva
    signals.sort(key=lambda s: pd.Timestamp(s["Entry_DT"]) if pd.notna(s.get("Entry_DT")) else pd.Timestamp.max)
    seen = set()
    deduped = []
    dropped = 0
    for s in signals:
        key = (s["Analysis_Type"], s["Signal"], s["Threshold_pct"], s["SL_pct"], s["SG_pct"])
        if key not in seen:
            seen.add(key)
            s["Deduped"] = False
            deduped.append(s)
        else:
            dropped += 1  # descartado, não incluído no resultado

    if dropped:
        pass  # contabilizado no run_analysis

    return deduped, dropped


def _load_cache(data_cache_dir: str) -> dict:
    """Carrega todos os CSVs do cache em memória. Retorna {ticker: df}."""
    cache = {}
    for fname in os.listdir(data_cache_dir):
        if not (fname.startswith("price_") and fname.endswith(".csv")):
            continue
        ticker = fname.replace("price_", "").replace(".csv", "").upper()
        path   = os.path.join(data_cache_dir, fname)
        try:
            df = pd.read_csv(path)
            df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce").dt.tz_localize(None)
            df = df.dropna(subset=["Datetime"]).sort_values("Datetime")
            cache[ticker] = df
        except Exception as e:
            print(f"[LOAD][WARN] Falha ao carregar {ticker}: {e}")
    return cache


def run_analysis(
    data_cache_dir=DATA_CACHE_DIR,
    signals_dir=SIGNALS_DIR,
    backtest_dir=BACKTEST_DIR,
    start: str = None,
    to: str = None,
):
    """
    Executa a análise dia a dia entre `start` e `to` (inclusive).

    - start : data inicial  (str 'YYYY-MM-DD'). Default = ontem.
    - to    : data final    (str 'YYYY-MM-DD'). Default = hoje.

    Se start == to (modo diário normal) os sinais são salvos em signals/.
    Se start < to (modo backtest)       os sinais são salvos em backtest/.
    """
    today_real = pd.Timestamp.now(tz=None).normalize()

    start_dt = pd.Timestamp(start).normalize() if start else today_real - timedelta(days=1)
    to_dt    = pd.Timestamp(to).normalize()    if to    else today_real

    is_backtest = start_dt < to_dt
    out_dir     = backtest_dir if is_backtest else signals_dir
    os.makedirs(out_dir, exist_ok=True)

    # Carrega todos os dados uma única vez
    cache = _load_cache(data_cache_dir)
    if not cache:
        print("[ANALYZE] Nenhum dado encontrado no cache.")
        return []

    # Itera cada dia de negociação no intervalo [start_dt, to_dt]
    all_signals  = []
    total_dropped = 0
    current = start_dt
    while current <= to_dt:
        # Pula fins de semana e feriados
        if not is_dia_util(current):
            current += timedelta(days=1)
            continue
        day_signals = []
        for ticker, df in cache.items():
            try:
                sigs, dropped = analyze_ticker(ticker, df, ref_date=current)
                total_dropped += dropped
                if sigs:
                    day_signals.extend(sigs)
            except Exception as e:
                print(f"[ANALYZE][WARN] {ticker} em {current.date()}: {e}")

        if day_signals:
            all_signals.extend(day_signals)
            if is_backtest:
                print(f"[BACKTEST] {current.date()}: {len(day_signals)} sinal(is)")
            else:
                for ticker in {s['Ticker'] for s in day_signals}:
                    n = sum(1 for s in day_signals if s['Ticker'] == ticker)
                    print(f"[ANALYZE] {ticker}: {n} sinal(is) encontrado(s).")

        current += timedelta(days=1)

    if all_signals:
        start_str = start_dt.strftime("%Y-%m-%d")
        to_str    = to_dt.strftime("%Y-%m-%d")
        fname     = (
            f"backtest_{start_str}_{to_str}.csv"
            if is_backtest
            else f"signals_{to_str}.csv"
        )
        out_path  = os.path.join(out_dir, fname)
        result_df = pd.DataFrame(all_signals)
        result_df.to_csv(out_path, index=False)
        print(f"\n[{'BACKTEST' if is_backtest else 'ANALYZE'}] {len(all_signals)} sinal(is) salvos em: {out_path}")
        print(f"[{'BACKTEST' if is_backtest else 'ANALYZE'}] {total_dropped} sinal(is) duplicado(s) descartados no período.")
    else:
        print("\n[ANALYZE] Nenhum sinal gerado no período.")

    return all_signals


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Análise de sinais de mercado")
    parser.add_argument("--start", default=None, help="Data inicial YYYY-MM-DD (default: ontem)")
    parser.add_argument("--to",    default=None, help="Data final   YYYY-MM-DD (default: hoje)")
    args = parser.parse_args()

    run_analysis(start=args.start, to=args.to)
