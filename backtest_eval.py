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
import re
import argparse
import pandas as pd

from analyze import run_analysis

DATA_CACHE_DIR  = "data_cache"
BACKTEST_DIR    = "backtest"
EOD_HOUR          = 16    # encerramento forçado às 16h
POINT_VALUE_BRL   = 0.20  # R$ por ponto (WIN mini-índice)

# Trailing stop
USE_TRAILING_STOP = False  # True → substitui SG fixo por stop móvel
TRAIL_PCT         = 0.003  # distância do trailing stop (0.30%)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_analysis_type(at: str):
    """
    Extrai (base_strategy, trend_filter, entry_window) de um Analysis_Type.

    Exemplos:
      'open_vs_prev_close_trend_on_ew_off'  → ('open_vs_prev_close', True,  False)
      'open_vs_prev_close_trend_off_ew_on'  → ('open_vs_prev_close', False, True)
      'open_vs_prev_close'                  → ('open_vs_prev_close', None,  None)
    """
    base  = at
    trend = None
    ew    = None

    m = re.search(r'_(trend_on|trend_off)', base)
    if m:
        trend = (m.group(1) == "trend_on")
        base  = base[:m.start()] + base[m.end():]

    m = re.search(r'_(ew_on|ew_off)', base)
    if m:
        ew   = (m.group(1) == "ew_on")
        base = base[:m.start()] + base[m.end():]

    return base, trend, ew


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
    Com USE_TRAILING_STOP=True, o SG fixo é substituído por um stop móvel
    que rastreia o melhor preço atingido (TRAIL_PCT de distância).
    """
    best_price = entry  # referência para cálculo do trailing stop

    for _, row in candles.iterrows():
        dt    = row["Datetime"]
        high  = row["High"]
        low   = row["Low"]
        close = row["Close"]

        if USE_TRAILING_STOP:
            if direction == "BUY":
                if pd.notna(high):
                    best_price = max(best_price, high)
                eff_sg = best_price * (1 - TRAIL_PCT)
                sl_hit = pd.notna(low)  and low  <= sl_price
                sg_hit = pd.notna(low)  and low  <= eff_sg
            else:  # SELL
                if pd.notna(low):
                    best_price = min(best_price, low)
                eff_sg = best_price * (1 + TRAIL_PCT)
                sl_hit = pd.notna(high) and high >= sl_price
                sg_hit = pd.notna(high) and high >= eff_sg
        else:
            eff_sg = sg_price
            if direction == "BUY":
                sl_hit = pd.notna(low)  and low  <= sl_price
                sg_hit = pd.notna(high) and high >= eff_sg
            else:  # SELL
                sl_hit = pd.notna(high) and high >= sl_price
                sg_hit = pd.notna(low)  and low  <= eff_sg

        if sl_hit:
            exit_price  = sl_price
            exit_reason = "SL"
            exit_dt     = dt
            break
        if sg_hit:
            exit_price  = round(eff_sg, 2)
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

    # Valida que as colunas do novo paradigma existem
    required = {"SL_pct", "SG_pct", "SL_price", "SG_price"}
    if not required.issubset(signals_df.columns):
        print(f"[EVAL] Colunas esperadas não encontradas: {required - set(signals_df.columns)}")
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

        sl_pct   = sig.get("SL_pct")
        sg_pct   = sig.get("SG_pct")
        sl_price = sig.get("SL_price")
        sg_price = sig.get("SG_price")

        if pd.isna(sl_price) or pd.isna(sg_price):
            continue

        # ── Diagnóstico: amplitude do dia para validar se SL era alcançável ────
        day_low_min  = day_df["Low"].min()
        day_high_max = day_df["High"].max()
        # SL_reachable: o preço cruzou o nível de SL em algum momento do dia?
        # BUY  → SL é atingido quando o LOW cai abaixo do sl_price
        # SELL → SL é atingido quando o HIGH sobe acima do sl_price
        if direction == "BUY":
            sl_reachable = bool(day_low_min  <= sl_price)
        else:
            sl_reachable = bool(day_high_max >= sl_price)

        res = _evaluate_candles(day_df, direction, entry, sl_price, sg_price)

        results.append({
            "Signal_Date":    sig_date.strftime("%Y-%m-%d"),
            "Ticker":         ticker,
            "Analysis_Type":  sig["Analysis_Type"],
            "Signal":         direction,
            "Threshold_pct":  sig["Threshold_pct"],
            "Entry_Price":    entry,
            "SL_pct":         sl_pct,
            "SL_Price":       sl_price,
            "SG_pct":         sg_pct,
            "SG_Price":       sg_price,
            "Day_Low_min":    round(day_low_min,  2),
            "Day_High_max":   round(day_high_max, 2),
            "SL_reachable":   sl_reachable,
            **res,
        })

        # ── SG_Natural: avalia o mesmo SL contra o alvo de reversão (ref_price) ──
        sg_natural = sig.get("SG_Natural")
        if pd.notna(sg_natural):
            if not pd.isna(sl_price):
                res = _evaluate_candles(day_df, direction, entry, sl_price, sg_natural)
                results.append({
                    "Signal_Date":    sig_date.strftime("%Y-%m-%d"),
                    "Ticker":         ticker,
                    "Analysis_Type":  sig["Analysis_Type"],
                    "Signal":         direction,
                    "Threshold_pct":  sig["Threshold_pct"],
                    "Entry_Price":    entry,
                    "SL_pct":         sl_pct,
                    "SL_Price":       sl_price,
                    "SG_pct":         "Natural",
                    "SG_Price":       sg_natural,
                    "Day_Low_min":    round(day_low_min,  2),
                    "Day_High_max":   round(day_high_max, 2),
                    "SL_reachable":   sl_reachable,
                    **res,
                })

    if not results:
        print("[EVAL] Nenhum resultado calculado.")
        return

    result_df = pd.DataFrame(results)

    # ── Extrai Strategy / Trend_Filter / Entry_Window de Analysis_Type ───────
    _parsed = result_df["Analysis_Type"].map(_parse_analysis_type)
    result_df.insert(result_df.columns.get_loc("Analysis_Type") + 1, "Strategy",      _parsed.map(lambda x: x[0]))
    result_df.insert(result_df.columns.get_loc("Strategy")      + 1, "Trend_Filter",  _parsed.map(lambda x: x[1]))
    result_df.insert(result_df.columns.get_loc("Trend_Filter")  + 1, "Entry_Window",  _parsed.map(lambda x: x[2]))

    # ── Diagnóstico de consistência do SL ────────────────────────────────────
    # Caso A: Exit_Reason=SL mas SL_reachable=False → possível bug
    sl_false_hit = result_df[(result_df["Exit_Reason"] == "SL") & (~result_df["SL_reachable"])]
    if not sl_false_hit.empty:
        print(f"[EVAL][WARN] {len(sl_false_hit)} caso(s) com SL registrado mas SL_reachable=False (checar bug!):")
        print(sl_false_hit[["Signal_Date","Ticker","Signal","SL_Price","Day_Low_min","Day_High_max","Exit_Reason"]].to_string())
    else:
        print("[EVAL] Diagnóstico SL: OK — todos os SL registrados tinham SL_reachable=True.")

    # Caso B: SL_reachable=True mas Exit_Reason != SL → SL era atingível mas saiu por SG ou EOD antes (normal)
    sl_reachable_no_hit = result_df[(result_df["SL_reachable"]) & (result_df["Exit_Reason"] != "SL")]
    pct_reachable_escaped = round(100 * len(sl_reachable_no_hit) / len(result_df), 1) if len(result_df) else 0
    print(f"[EVAL] SL era atingível no dia mas saiu antes (SG/EOD): {len(sl_reachable_no_hit)} ({pct_reachable_escaped}% do total) — normal quando SG é atingido primeiro.")

    agg_spec = {
        "Operacoes":      ("PL_BRL", "count"),
        "PL_pts_total":   ("PL_abs", "sum"),
        "PL_pts_medio":   ("PL_abs", "mean"),
        "PL_BRL_total":   ("PL_BRL", "sum"),
        "PL_BRL_medio":   ("PL_BRL", "mean"),
        "PL_BRL_max":     ("PL_BRL", "max"),
        "PL_BRL_min":     ("PL_BRL", "min"),
        "PL_pct_medio":   ("PL_pct", "mean"),
        "SG_hits":        ("Exit_Reason", lambda x: (x == "SG").sum()),
        "SL_hits":        ("Exit_Reason", lambda x: (x == "SL").sum()),
        "EOD_hits":       ("Exit_Reason", lambda x: (x == "EOD").sum()),
        "WinRate_pct":    ("Exit_Reason", lambda x: round(100 * (x == "SG").sum() / len(x), 2)),
        "LossRate_pct":   ("Exit_Reason", lambda x: round(100 * (x != "SG").sum() / len(x), 2)),
    }

    def _add_flag(df: pd.DataFrame) -> pd.DataFrame:
        """Adiciona coluna Recomendada: True se WinRate >= 60% E PL_BRL_total > 0."""
        df = df.copy()
        df["Recomendada"] = (df["WinRate_pct"] >= 60) & (df["PL_BRL_total"] > 0)
        return df

    # ── Métrica de dedup: informa sinais únicos processados ──────────────────
    total_sinais = len(signals_df)
    print(f"[EVAL] Sinais únicos a avaliar (pós-dedup por estratégia): {total_sinais}")

    # ── Resumo 1: por Stop (SL_pct / SG_pct) ─────────────────────────────
    summary_stop = _add_flag(result_df.groupby(["SL_pct", "SG_pct"]).agg(**agg_spec).round(4))

    # ── Resumo 2: por Estratégia (Strategy + filtros + Threshold + Stop) ──
    summary_strategy = _add_flag(
        result_df
        .groupby(["Strategy", "Trend_Filter", "Entry_Window", "Threshold_pct", "Signal", "SL_pct", "SG_pct"])
        .agg(**agg_spec)
        .round(4)
    )

    # ── Resumo 3: consolidado por Estratégia (sem detalhe de stop) ────────
    summary_consolidated = _add_flag(
        result_df
        .groupby(["Strategy", "Trend_Filter", "Entry_Window", "Threshold_pct", "Signal"])
        .agg(**agg_spec)
        .round(4)
    )

    # ── Resumo 4: mensal ─────────────────────────────────────────────────────
    result_df["Mes"] = pd.to_datetime(result_df["Signal_Date"]).dt.to_period("M").astype(str)
    agg_spec_monthly = {
        "Trades":         ("PL_BRL", "count"),
        "PL_BRL_total":   ("PL_BRL", "sum"),
        "PL_BRL_medio":   ("PL_BRL", "mean"),
        "PL_BRL_max":     ("PL_BRL", "max"),
        "PL_BRL_min":     ("PL_BRL", "min"),
        "PL_pts_total":   ("PL_abs", "sum"),
        "PL_pts_medio":   ("PL_abs", "mean"),
        "WinRate_pct":    ("Exit_Reason", lambda x: round(100 * (x == "SG").sum() / len(x), 2)),
        "SG_hits":        ("Exit_Reason", lambda x: (x == "SG").sum()),
        "SL_hits":        ("Exit_Reason", lambda x: (x == "SL").sum()),
        "EOD_hits":       ("Exit_Reason", lambda x: (x == "EOD").sum()),
    }
    summary_monthly = result_df.groupby("Mes").agg(**agg_spec_monthly).round(4)

    base_name   = os.path.splitext(os.path.basename(signals_path))[0]
    out_path    = os.path.join(out_dir, f"eval_{base_name}.csv")
    stop_path   = os.path.join(out_dir, f"eval_{base_name}_by_stop.csv")
    strat_path  = os.path.join(out_dir, f"eval_{base_name}_by_strategy.csv")
    consol_path = os.path.join(out_dir, f"eval_{base_name}_consolidated.csv")
    monthly_path = os.path.join(out_dir, f"eval_{base_name}_monthly.csv")

    result_df.to_csv(out_path, index=False)
    summary_stop.to_csv(stop_path)
    summary_strategy.to_csv(strat_path)
    summary_consolidated.to_csv(consol_path)
    summary_monthly.to_csv(monthly_path)

    # ── Salva também em xlsx ──────────────────────────────────────────────────
    xlsx_path = os.path.join(out_dir, f"eval_{base_name}.xlsx")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        result_df.to_excel(writer, sheet_name="Detalhado", index=False, merge_cells=False)
        summary_stop.to_excel(writer, sheet_name="Por_Stop", merge_cells=False)
        summary_strategy.to_excel(writer, sheet_name="Por_Estrategia", merge_cells=False)
        summary_consolidated.to_excel(writer, sheet_name="Consolidado", merge_cells=False)
        summary_monthly.to_excel(writer, sheet_name="Mensal", merge_cells=False)
    print(f"[EVAL] Arquivo xlsx salvo em:  {xlsx_path}")

    print(f"[EVAL] {len(result_df)} operação(ões) detalhadas em: {out_path}")
    print(f"[EVAL] Resumo por stop:       {stop_path}")
    print(f"[EVAL] Resumo por estratégia: {strat_path}")
    print(f"[EVAL] Consolidado:           {consol_path}")
    print(f"[EVAL] Mensal:                {monthly_path}")

    print("\n── Consolidado por Estratégia ───────────────────────────────────────")
    print(summary_consolidated.to_string())
    recomendadas = summary_consolidated[summary_consolidated["Recomendada"] == True]
    if not recomendadas.empty:
        print("\n★  Estratégias RECOMENDADAS (WinRate ≥ 60% e lucro positivo):")
        print(recomendadas[["Operacoes", "WinRate_pct", "PL_BRL_total", "PL_BRL_medio", "PL_BRL_max", "PL_BRL_min"]].to_string())
    else:
        print("\n★  Nenhuma estratégia atingiu os critérios (WinRate ≥ 60% e lucro positivo).")
    print("\n── Resumo por Stop (SL_pct x SG_pct) ──────────────────────────────")
    print(summary_stop.to_string())
    print("\n── Resumo Mensal ────────────────────────────────────────────────────")
    print(summary_monthly.to_string())

    return result_df


# ── CLI ──────────────────────────────────────────────────────────────────────

# if __name__ == "__main__":


def backtest():
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
