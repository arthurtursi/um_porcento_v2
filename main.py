from backtest_eval import backtest
from utils import update_data_cache
from analyze import run_analysis

if __name__ == "__main__":
    update_data_cache()
    # run_analysis(start="2026-01-01", to="2025-06-01")  # modo diário: start=ontem, to=hoje
    run_analysis(start="2025-06-01", to="2026-01-01")  # modo diário: start=ontem, to=hoje
    backtest()
