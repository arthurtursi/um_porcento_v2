"""
backtest_eval.py
────────────────
Lê um CSV de sinais gerado por analyze.py (backtest ou diário) e, para cada
sinal, simula o resultado intraday:

  - Verifica hora a hora se o SL ou o SG foi atingido (nessa ordem de
    prioridade quando ambos ocorrem no mesmo candle).
  - Caso nenhum seja atingido até a 16h, encerra a posição no fechamento
    (Close) do último candle <= 16h.

Resultado salvo em backtest/backtest_eval_<arquivo>.csv
"""

import os
import argparse
import pandas as pd

from analyze import run_analysis

DATA_CACHE_DIR  = "data_cache"
BACKTEST_DIR    = "backtest"
EOD_HOUR        = 16    # encerramento forçado às 16h
POINT_VALUE_BRL = 0.20  # R$ por ponto (WIN mini-índice)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_cache(data_cache_dir: str) -> dict:
    """Carrega todos os CSVs de preço em memória. Retorna {ticker: df}."""
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
            print(f"[EVAL][WARN] Falha ao carregar {ticker}: {e}")
    return cache


def _sl_sg_pairs(columns: list) -> list[tuple[str, str]]:
    """
    Retorna pares (sl_col, sg_col) a avaliar.
    Emparelha por posição dentro de cada grupo (fine / broad).
    """
    sl_cols  = sorted([c for c in columns if c.startswith("SL_")])
    sg_cols  = sorted([c for c in columns if c.startswith("SG_")])
    # Separa fine (contém '_' no sufixo, ex: SL_0_20pct) de broad (ex: SL_10pct)
    fine_sl  = [c for c in sl_cols if c[3:4] == "0"]   # SL_0_*
    broad_sl = [c for c in sl_cols if c[3:4] != "0"]   # SL_10pct …
    fine_sg  = [c for c in sg_cols if c[3:4] == "0"]
    broad_sg = [c for c in sg_cols if c[3:4] != "0"]
    pairs = list(zip(fine_sl, fine_sg)) + list(zip(broad_sl, broad_sg))
    return pairs


def _evaluate_candles(
    candles: pd.DataFrame,
    direction: str,
    entry: float,
    sl_price: float,
    sg_price: float,
) -> dict:
    """
    Itera candles horários e retorna o resultado da operação.

    BUY : SL se Low  <= sl_price ; SG se High >= sg_price
    SELL: SL se High >= sl_price ; SG se Low  <= sg_price

    Se no mesmo candle SL e SG são tocados, assume-se SL (pior caso).
    """
    for _, row in candles.iterrows():
        dt    = row["Datetime"]
        high  = row["High"]
        low   = row["Low"]
        close = row["Close"]

        if direction == "BUY":
            sl_hit = pd.notna(low)  and low  <= sl_price
            sg_hit = pd.notna(high) and high >= sg_price
        else:  # SELL
            sl_hit = pd.notna(high) and high >= sl_price
            sg_hit = pd.notna(low)  and low  <= sg_price

        if sl_hit:
            exit_price  = sl_price
            exit_reason = "SL"
            exit_dt     = dt
            break
        if sg_hit:
            exit_price  = sg_price
            exit_reason = "SG"
            exit_dt     = dt
            break
    else:
        # Nenhum stop atingido → fecha no último candle disponível (EOD)
        last = candles.iloc[-1]
        exit_price  = last["Close"]
        exit_reason = "EOD"
        exit_dt     = last["Datetime"]

    if direction == "BUY":
        pl_abs = round(exit_price - entry, 2)
    else:
        pl_abs = round(entry - exit_price, 2)

    pl_pct = round(pl_abs / entry * 100, 4) if entry else None
    pl_brl = round(pl_abs * POINT_VALUE_BRL, 2)

    return {
        "Exit_DT":     exit_dt,
        "Exit_Price":  round(exit_price, 2),
        "Exit_Reason": exit_reason,
        "PL_abs":      pl_abs,
        "PL_pct":      pl_pct,
        "PL_BRL":      pl_brl,
    }


# ── Core ─────────────────────────────────────────────────────────────────────

def evaluate(signals_path: str, data_cache_dir=DATA_CACHE_DIR, out_dir=BACKTEST_DIR):
    """
    Avalia todos os sinais de `signals_path` contra os dados intraday.

    Para cada sinal, gera uma linha de resultado por par (SL, SG) avaliado.
    """
    os.makedirs(out_dir, exist_ok=True)

    signals_df = pd.read_csv(signals_path)

    cache = _load_cache(data_cache_dir)

    # Compatibilidade: infere Signal_Date a partir do Reference_DT quando ausente
    if "Signal_Date" not in signals_df.columns:
        print("[EVAL] Coluna 'Signal_Date' ausente — inferindo a partir de Reference_DT...")
        signals_df["Reference_DT"] = pd.to_datetime(signals_df["Reference_DT"], errors="coerce")

        def _infer_signal_date(row):
            ticker = row["Ticker"]
            ref_dt = pd.Timestamp(row["Reference_DT"]).normalize() if pd.notna(row["Reference_DT"]) else None
            if ref_dt is None or ticker not in cache:
                return pd.NaT
            available_days = cache[ticker]["Datetime"].dt.normalize().drop_duplicates().sort_values()
            next_days = available_days[available_days > ref_dt]
            return next_days.iloc[0] if not next_days.empty else pd.NaT

        signals_df["Signal_Date"] = signals_df.apply(_infer_signal_date, axis=1)
        missing = signals_df["Signal_Date"].isna().sum()
        if missing:
            print(f"[EVAL][WARN] {missing} sinal(is) sem Signal_Date válido — serão ignorados.")
        signals_df = signals_df.dropna(subset=["Signal_Date"])

    signals_df["Signal_Date"] = pd.to_datetime(signals_df["Signal_Date"], errors="coerce")

    pairs  = _sl_sg_pairs(signals_df.columns.tolist())

    if not pairs:
        print("[EVAL] Nenhum par SL/SG encontrado nas colunas do arquivo de sinais.")
        return

    results = []
    total = len(signals_df)

    for i, (_, sig) in enumerate(signals_df.iterrows(), start=1):
        if i % 25 == 0 or i == 1 or i == total:
            print(f"[EVAL] Processando {i}/{total} ({100*i//total}%) ...")
        ticker     = sig["Ticker"]
        sig_date   = pd.Timestamp(sig["Signal_Date"]).normalize()
        direction  = sig["Signal"]
        entry      = sig["Entry_Price"]

        # Entry_DT: candle onde o threshold foi cruzado (novo paradigma)
        # Se ausente (arquivo gerado pelo paradigma antigo), usa o 1º candle do dia
        entry_dt_raw = sig.get("Entry_DT")
        if pd.notna(entry_dt_raw):
            entry_dt = pd.Timestamp(entry_dt_raw)
        else:
            entry_dt = None

        if ticker not in cache:
            continue

        df = cache[ticker]

        # Candles a partir do candle de entrada até 16h (inclusive)
        # O candle de entrada é incluído pois a posição abre no threshold ainda dentro dele
        if entry_dt is not None:
            day_df = df[
                (df["Datetime"] >= entry_dt) &
                (df["Datetime"].dt.hour <= EOD_HOUR)
            ].copy()
        else:
            # Compatibilidade com arquivo antigo: descarta só o 1º candle (open)
            day_df = df[
                (df["Datetime"].dt.normalize() == sig_date) &
                (df["Datetime"].dt.hour <= EOD_HOUR)
            ].copy()
            day_df = day_df.iloc[1:] if len(day_df) > 1 else day_df

        if day_df.empty:
            continue

        for sl_col, sg_col in pairs:
            sl_price = sig.get(sl_col)
            sg_price = sig.get(sg_col)

            if pd.isna(sl_price) or pd.isna(sg_price):
                continue

            res = _evaluate_candles(day_df, direction, entry, sl_price, sg_price)

            results.append({
                "Signal_Date":    sig_date.strftime("%Y-%m-%d"),
                "Ticker":         ticker,
                "Analysis_Type":  sig["Analysis_Type"],
                "Signal":         direction,
                "Threshold_pct":  sig["Threshold_pct"],
                "Entry_Price":    entry,
                "SL_col":         sl_col,
                "SL_Price":       sl_price,
                "SG_col":         sg_col,
                "SG_Price":       sg_price,
                **res,
            })

        # ── SG_Natural: avalia cada SL contra o alvo de reversão (ref_price) ──
        sg_natural = sig.get("SG_Natural")
        if pd.notna(sg_natural):
            for sl_col, _ in pairs:
                sl_price = sig.get(sl_col)
                if pd.isna(sl_price):
                    continue
                res = _evaluate_candles(day_df, direction, entry, sl_price, sg_natural)
                results.append({
                    "Signal_Date":    sig_date.strftime("%Y-%m-%d"),
                    "Ticker":         ticker,
                    "Analysis_Type":  sig["Analysis_Type"],
                    "Signal":         direction,
                    "Threshold_pct":  sig["Threshold_pct"],
                    "Entry_Price":    entry,
                    "SL_col":         sl_col,
                    "SL_Price":       sl_price,
                    "SG_col":         "SG_Natural",
                    "SG_Price":       sg_natural,
                    **res,
                })

    if not results:
        print("[EVAL] Nenhum resultado calculado.")
        return

    result_df = pd.DataFrame(results)

    agg_spec = {
        "Operacoes":    ("PL_BRL", "count"),
        "PL_pts_total": ("PL_abs", "sum"),
        "PL_BRL_total": ("PL_BRL", "sum"),
        "PL_pct_medio": ("PL_pct", "mean"),
        "SL_hits":      ("Exit_Reason", lambda x: (x == "SL").sum()),
        "SG_hits":      ("Exit_Reason", lambda x: (x == "SG").sum()),
        "EOD_hits":     ("Exit_Reason", lambda x: (x == "EOD").sum()),
    }

    # ── Métrica de dedup: informa sinais únicos processados ──────────────────
    total_sinais = len(signals_df)
    print(f"[EVAL] Sinais únicos a avaliar (pós-dedup por estratégia): {total_sinais}")

    # ── Resumo 1: por Stop (SL_col / SG_col) ─────────────────────────────
    summary_stop = result_df.groupby(["SL_col", "SG_col"]).agg(**agg_spec).round(4)

    # ── Resumo 2: por Estratégia (Analysis_Type + Threshold + Stop) ───────
    summary_strategy = (
        result_df
        .groupby(["Analysis_Type", "Threshold_pct", "Signal", "SL_col", "SG_col"])
        .agg(**agg_spec)
        .round(4)
    )

    # ── Resumo 3: consolidado por Estratégia (sem detalhe de stop) ────────
    summary_consolidated = (
        result_df
        .groupby(["Analysis_Type", "Threshold_pct", "Signal"])
        .agg(**agg_spec)
        .round(4)
    )

    base_name   = os.path.splitext(os.path.basename(signals_path))[0]
    out_path    = os.path.join(out_dir, f"eval_{base_name}.csv")
    stop_path   = os.path.join(out_dir, f"eval_{base_name}_by_stop.csv")
    strat_path  = os.path.join(out_dir, f"eval_{base_name}_by_strategy.csv")
    consol_path = os.path.join(out_dir, f"eval_{base_name}_consolidated.csv")

    result_df.to_csv(out_path, index=False)
    summary_stop.to_csv(stop_path)
    summary_strategy.to_csv(strat_path)
    summary_consolidated.to_csv(consol_path)

    print(f"[EVAL] {len(result_df)} operação(ões) detalhadas em: {out_path}")
    print(f"[EVAL] Resumo por stop:       {stop_path}")
    print(f"[EVAL] Resumo por estratégia: {strat_path}")
    print(f"[EVAL] Consolidado:           {consol_path}")

    print("\n── Consolidado por Estratégia ───────────────────────────────────────")
    print(summary_consolidated.to_string())
    print("\n── Resumo por Stop (SL/SG) ─────────────────────────────────────────")
    print(summary_stop.to_string())

    return result_df


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_analysis(start="2024-01-01", to="2026-03-01")  # modo diário: start=ontem, to=hoje
    parser = argparse.ArgumentParser(description="Avalia resultados do backtest intraday")
    parser.add_argument(
        "signals_file",
        nargs="?",
        default=None,
        help="Caminho para o CSV de sinais. Se omitido, usa o mais recente em backtest/",
    )
    parser.add_argument("--data-cache", default=DATA_CACHE_DIR)
    parser.add_argument("--out-dir",   default=BACKTEST_DIR)
    args = parser.parse_args()

    if args.signals_file:
        signals_path = args.signals_file
    else:
        # Usa o arquivo backtest mais recente
        bt_files = sorted([
            f for f in os.listdir(args.out_dir)
            if f.startswith("backtest_") and f.endswith(".csv")
            and "eval" not in f
        ])
        if not bt_files:
            print("[EVAL] Nenhum arquivo de backtest encontrado em", args.out_dir)
            raise SystemExit(1)
        signals_path = os.path.join(args.out_dir, bt_files[-1])
        print(f"[EVAL] Usando: {signals_path}")

    evaluate(signals_path, data_cache_dir=args.data_cache, out_dir=args.out_dir)
