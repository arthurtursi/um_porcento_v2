import pandas as pd
from datetime import timedelta


def parse_date(date_str):
    """
    Tenta converter string de data para datetime suportando múltiplos formatos.
    """
    try:
        return pd.to_datetime(date_str, format='%d/%m/%Y')
    except Exception:
        try:
            return pd.to_datetime(date_str, format='%m/%d/%Y')
        except Exception:
            try:
                return pd.to_datetime(date_str, format='%Y-%m-%d')
            except Exception:
                return pd.to_datetime(date_str, format='mixed')


def get_feriados_nacionais(ano):
    """Retorna uma lista com as datas dos principais feriados nacionais do ano."""
    feriados = [
        f"{ano}-01-01",  # Ano Novo
        f"{ano}-04-21",  # Tiradentes
        f"{ano}-05-01",  # Dia do Trabalho
        f"{ano}-09-07",  # Independência
        f"{ano}-10-12",  # Nossa Senhora Aparecida
        f"{ano}-11-02",  # Finados
        f"{ano}-11-15",  # Proclamação da República
        f"{ano}-12-25",  # Natal
        f"{ano}-12-30",  # Véspera de Ano Novo
        f"{ano}-12-31",  # Ano Novo
    ]
    return [pd.to_datetime(data).date() for data in feriados]


def ajustar_para_dia_util(data, mover_para_frente=True):
    """Ajusta uma data para o próximo (ou anterior) dia útil se cair em fim de semana ou feriado."""
    ano = data.year
    feriados = get_feriados_nacionais(ano)
    if mover_para_frente:
        feriados.extend(get_feriados_nacionais(ano + 1))
    else:
        feriados.extend(get_feriados_nacionais(ano - 1))

    while data.weekday() >= 5 or data.date() in feriados:
        data += timedelta(days=1 if mover_para_frente else -1)

    return data


def is_dia_util(data) -> bool:
    """Retorna True se a data for um dia útil (não feriado e não fim de semana)."""
    if hasattr(data, 'date'):
        d = data.date()
    else:
        d = data
    ano = d.year
    feriados = get_feriados_nacionais(ano)
    return d.weekday() < 5 and d not in feriados


def ajustar_periodos(start, end, days_before, days_after):
    """
    Ajusta as datas de início e fim considerando dias úteis e feriados.

    Returns:
        Tupla (start_day, start_next, end_day, end_next) no formato 'YYYY-MM-DD'
    """
    start_dt = pd.to_datetime(start)
    end_dt   = pd.to_datetime(end)

    start_day = start_dt.strftime('%Y-%m-%d')
    end_day   = end_dt.strftime('%Y-%m-%d')

    start_next = ajustar_para_dia_util(start_dt - timedelta(days=days_before), mover_para_frente=False)
    end_next   = ajustar_para_dia_util(end_dt   + timedelta(days=days_after),  mover_para_frente=True)

    return start_day, start_next.strftime('%Y-%m-%d'), end_day, end_next.strftime('%Y-%m-%d')
