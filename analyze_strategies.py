"""
analyze_strategies.py
─────────────────────
Lê todos os arquivos *_by_strategy.csv dos diretórios backtest/anual/ e
backtest/semestral/ e aplica filtros duplos:

  • WinRate_pct  > FILTER_WINRATE  (padrão: 60%)
  • PL_BRL_medio > FILTER_MED_BRL  (padrão: R$50 por trade)
  • Operacoes   >= MIN_TRADES      (padrão: 10 — mínimo estatístico)

Exibe o ranking das melhores configurações e lista os defeitos por estratégia.
"""

import os
import glob
import argparse
import pandas as pd

# ── Parâmetros de filtro ─────────────────────────────────────────────────────
FILTER_WINRATE = 60.0   # WinRate_pct mínimo (%)
FILTER_MED_BRL = 50.0   # PL_BRL_medio mínimo por trade (R$)
MIN_TRADES     = 10     # Operações mínimas por período para ser válido
BACKTEST_DIR   = "backtest"
TOP_N          = 10     # quantas configs exibir no ranking final

KEY_COLS = ["Analysis_Type", "Threshold_pct", "Signal", "SL_pct", "SG_pct"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_all(backtest_dir: str) -> pd.DataFrame:
    """Carrega todos os _by_strategy.csv e adiciona metadados de período."""
    pattern = os.path.join(backtest_dir, "**", "*_by_strategy.csv")
    files   = glob.glob(pattern, recursive=True)

    if not files:
        raise FileNotFoundError(
            f"Nenhum arquivo *_by_strategy.csv encontrado em '{backtest_dir}'"
        )

    dfs = []
    for f in files:
        df = pd.read_csv(f)
        folder = os.path.basename(os.path.dirname(f))
        tipo   = "anual" if "anual" in f else "semestral"
        df["periodo"]      = folder
        df["tipo_periodo"] = tipo
        dfs.append(df)

    all_df = pd.concat(dfs, ignore_index=True)
    print(f"[INFO] {len(files)} arquivos carregados — {len(all_df)} linhas no total\n")
    return all_df


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica filtros de qualidade."""
    mask = (
        (df["WinRate_pct"]  > FILTER_WINRATE)  &
        (df["PL_BRL_medio"] > FILTER_MED_BRL)  &
        (df["Operacoes"]   >= MIN_TRADES)
    )
    passed = df[mask].copy()
    pct = len(passed) / len(df) * 100
    print(f"[FILTRO] WinRate>{FILTER_WINRATE}%  |  Med/trade>R${FILTER_MED_BRL}"
          f"  |  Trades>={MIN_TRADES}")
    print(f"[FILTRO] {len(passed)}/{len(df)} linhas passaram ({pct:.1f}%)\n")
    return passed


def build_ranking(passed: pd.DataFrame) -> pd.DataFrame:
    """Agrupa por configuração e ranqueia por consistência + rentabilidade."""
    ranking = (
        passed
        .groupby(KEY_COLS)
        .agg(
            periodos_aprovados = ("periodo",        "count"),
            winrate_medio      = ("WinRate_pct",    "mean"),
            winrate_min        = ("WinRate_pct",    "min"),
            medio_brl          = ("PL_BRL_medio",   "mean"),
            total_brl          = ("PL_BRL_total",   "sum"),
            operacoes_total    = ("Operacoes",       "sum"),
            periodos_lista     = ("periodo",         lambda s: ", ".join(sorted(s))),
        )
        .reset_index()
        .sort_values(
            ["periodos_aprovados", "winrate_medio", "medio_brl"],
            ascending=[False, False, False]
        )
        .reset_index(drop=True)
    )
    ranking.index += 1  # ranking começa em 1
    return ranking


def print_ranking(ranking: pd.DataFrame, top_n: int) -> None:
    top = ranking.head(top_n)
    print("=" * 90)
    print(f"  TOP {top_n} CONFIGURAÇÕES — WinRate>{FILTER_WINRATE}%"
          f" & Med>R${FILTER_MED_BRL} & Trades>={MIN_TRADES}")
    print("=" * 90)

    cols_display = [
        "Analysis_Type", "Threshold_pct", "Signal", "SL_pct", "SG_pct",
        "periodos_aprovados", "winrate_medio", "winrate_min",
        "medio_brl", "total_brl", "operacoes_total",
    ]
    col_rename = {
        "Analysis_Type":      "Estrategia",
        "Threshold_pct":      "Thresh",
        "Signal":             "Dir",
        "SL_pct":             "SL",
        "SG_pct":             "SG",
        "periodos_aprovados": "Periodos✓",
        "winrate_medio":      "WR_med%",
        "winrate_min":        "WR_min%",
        "medio_brl":          "Med R$/trade",
        "total_brl":          "PL_Total R$",
        "operacoes_total":    "Trades",
    }

    display = top[cols_display].rename(columns=col_rename)
    display["WR_med%"]     = display["WR_med%"].map("{:.1f}%".format)
    display["WR_min%"]     = display["WR_min%"].map("{:.1f}%".format)
    display["Med R$/trade"]= display["Med R$/trade"].map("R$ {:,.2f}".format)
    display["PL_Total R$"] = display["PL_Total R$"].map("R$ {:,.2f}".format)
    display["SL"]          = display["SL"].map("{:.1%}".format)
    display["SG"]          = display["SG"].apply(
        lambda x: "Natural" if str(x).lower() == "natural" else f"{float(x):.1%}"
    )

    print(display.to_string())
    print()

    # Detalhe: períodos onde cada top-config passou
    print("-" * 90)
    print("  Períodos aprovados por configuração:")
    print("-" * 90)
    for i, row in top.iterrows():
        label = (f"#{i} {row['Analysis_Type']} | {row['Threshold_pct']} | "
                 f"{row['Signal']} | SL={float(row['SL_pct']):.1%} | SG={row['SG_pct']}")
        print(f"  {label}")
        print(f"      → {row['periodos_lista']}\n")


def print_defects(df: pd.DataFrame) -> None:
    """Imprime resumo de defeitos por estratégia."""
    print("=" * 90)
    print("  ANÁLISE DE DEFEITOS POR ESTRATÉGIA")
    print("=" * 90)

    strategies = df["Analysis_Type"].unique()

    for strat in sorted(strategies):
        sub = df[df["Analysis_Type"] == strat]
        total = len(sub)
        passed_wr  = (sub["WinRate_pct"]  > FILTER_WINRATE).sum()
        passed_med = (sub["PL_BRL_medio"] > FILTER_MED_BRL).sum()
        passed_vol = (sub["Operacoes"]    >= MIN_TRADES).sum()
        passed_all = (
            (sub["WinRate_pct"]  > FILTER_WINRATE) &
            (sub["PL_BRL_medio"] > FILTER_MED_BRL) &
            (sub["Operacoes"]    >= MIN_TRADES)
        ).sum()

        negative = (sub["PL_BRL_total"] < 0).sum()
        wr_below50 = (sub["WinRate_pct"] < 50).sum()

        print(f"\n  [{strat}]")
        print(f"    Total configs/períodos : {total}")
        print(f"    Passam WinRate>60%     : {passed_wr} ({passed_wr/total*100:.0f}%)")
        print(f"    Passam Med>R$50/trade  : {passed_med} ({passed_med/total*100:.0f}%)")
        print(f"    Passam Trades>={MIN_TRADES:<2}      : {passed_vol} ({passed_vol/total*100:.0f}%)")
        print(f"    Passam TODOS critérios : {passed_all} ({passed_all/total*100:.0f}%)")
        print(f"    P&L total NEGATIVO     : {negative} ({negative/total*100:.0f}%)")
        print(f"    WinRate < 50%          : {wr_below50} ({wr_below50/total*100:.0f}%)")

        # Pior config por P&L total
        worst = sub.nsmallest(1, "PL_BRL_total").iloc[0]
        print(f"    Pior PL_BRL_total      : R${worst['PL_BRL_total']:,.2f} "
              f"({worst['Signal']} SL={worst['SL_pct']:.1%} SG={worst['SG_pct']} "
              f"Thresh={worst['Threshold_pct']} período={worst['periodo']})")

        # Best config
        best_rows = sub[
            (sub["WinRate_pct"]  > FILTER_WINRATE) &
            (sub["PL_BRL_medio"] > FILTER_MED_BRL) &
            (sub["Operacoes"]    >= MIN_TRADES)
        ]
        if len(best_rows):
            best = best_rows.nlargest(1, "PL_BRL_medio").iloc[0]
            print(f"    Melhor Med R$/trade    : R${best['PL_BRL_medio']:,.2f} "
                  f"(WR={best['WinRate_pct']:.1f}% {best['Signal']} "
                  f"SL={best['SL_pct']:.1%} SG={best['SG_pct']} "
                  f"Thresh={best['Threshold_pct']} período={best['periodo']})")
        else:
            print(f"    Melhor Med R$/trade    : nenhuma config passou todos os critérios")

    print()


def export_results(ranking: pd.DataFrame, passed: pd.DataFrame, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    ranking_path = os.path.join(out_dir, "ranking_strategies.csv")
    ranking.to_csv(ranking_path, index=True)
    print(f"[EXPORT] Ranking salvo em: {ranking_path}")

    passed_path = os.path.join(out_dir, "passed_strategies.csv")
    passed.to_csv(passed_path, index=False)
    print(f"[EXPORT] Configs aprovadas salvas em: {passed_path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analisa e ranqueia estratégias de backtest"
    )
    parser.add_argument("--backtest-dir", default=BACKTEST_DIR,
                        help="Diretório raiz do backtest (default: backtest/)")
    parser.add_argument("--top",          type=int, default=TOP_N,
                        help=f"Quantidade de tops a exibir (default: {TOP_N})")
    parser.add_argument("--winrate",      type=float, default=FILTER_WINRATE,
                        help=f"WinRate mínimo %% (default: {FILTER_WINRATE})")
    parser.add_argument("--med-brl",      type=float, default=FILTER_MED_BRL,
                        help=f"PL_BRL_medio mínimo R$ (default: {FILTER_MED_BRL})")
    parser.add_argument("--min-trades",   type=int, default=MIN_TRADES,
                        help=f"Trades mínimos por período (default: {MIN_TRADES})")
    parser.add_argument("--export",       action="store_true",
                        help="Salva resultados em backtest/analysis/", default=True)
    parser.add_argument("--defects",      action="store_true", default=True,
                        help="Exibe análise de defeitos por estratégia (padrão: True)")
    parser.add_argument("--no-defects",   dest="defects", action="store_false")
    args = parser.parse_args()

    # # Sobrescreve globais com args
    # FILTER_WINRATE = args.winrate
    # FILTER_MED_BRL = args.med_brl
    # MIN_TRADES     = args.min_trades

    df      = load_all(args.backtest_dir)
    passed  = apply_filters(df)
    ranking = build_ranking(passed)

    if args.defects:
        print_defects(df)

    print_ranking(ranking, args.top)

    if args.export:
        export_results(ranking, passed, os.path.join(args.backtest_dir, "analysis"))


if __name__ == "__main__":
    main()
