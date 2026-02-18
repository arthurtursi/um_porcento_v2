import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

def update_data_cache(data_cache_dir="data_cache", ignore_tickers=None):
    """Atualiza todos os arquivos de preço no cache local até a data de hoje, ignorando tickers descomissionados."""
    if ignore_tickers is None:
        ignore_tickers = set()
    today = pd.Timestamp.now(tz=None).normalize()-timedelta(days=1)
    for fname in os.listdir(data_cache_dir):
        if fname.startswith("price_") and fname.endswith(".csv"):
            ticker = fname.replace("price_", "").replace(".csv", "").upper()
            if ticker in ignore_tickers:
                continue
            path = os.path.join(data_cache_dir, fname)
            try:
                df = pd.read_csv(path, parse_dates=["Datetime"])
                if df.empty:
                    continue
                    # Remove timezone das datas (torna tz-naive)
                    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce").dt.tz_localize(None)
                last_date = df["Datetime"].max()
                if last_date >= today:
                    continue
                yf_ticker = yf.Ticker(f"{ticker}")
                # Busca dados de hora em hora
                new_data = yf_ticker.history(start=last_date + timedelta(hours=1), end=today + timedelta(days=1), interval="60m")
                if not new_data.empty:
                    new_data = new_data.reset_index()
                    new_data = new_data.rename(columns={"Datetime": "Datetime", "Date": "Datetime"})
                        # Remove timezone das datas (torna tz-naive)
                    new_data["Datetime"] = pd.to_datetime(new_data["Datetime"], errors="coerce").dt.tz_localize(None)
                    # Padroniza colunas para evitar problemas de concatenação
                    for col in ["Open", "High", "Low", "Close", "Volume"]:
                        if col not in new_data.columns:
                            new_data[col] = None
                        else:
                            # Arredonda para 2 casas decimais se for numérico
                            new_data[col] = pd.to_numeric(new_data[col], errors="coerce").round(2)
                    df = pd.concat([df, new_data], ignore_index=True)
                    df = df.drop_duplicates(subset=["Datetime"])
                    df = df.sort_values("Datetime")
                    df.to_csv(path, index=False)
                    print(f"[CACHE] Atualizado {ticker}: {last_date} -> {today}")
            except Exception as e:
                print(f"[CACHE][WARN] Falha ao atualizar {ticker}: {e}")
