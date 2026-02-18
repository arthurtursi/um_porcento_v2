# Estratégia `open_vs_prev_close` 1% — Como operar no dia a dia

## A lógica em uma frase

> **Se hoje a cotação se afastar 1% do fechamento de ontem, você entra na direção do movimento com SL de 0,75% e SG de 0,50%.**

---

## Configuração dos stops

| Signal | SL_pct | SG_pct |
|--------|--------|--------|
| BUY    | 0,75%  | 0,50%  |
| SELL   | 0,75%  | 0,50%  |

---

## Passo a passo antes da abertura (ex: às 8h30)

1. Veja o **fechamento de ontem** do WIN (ex: fechou em **130.000 pts**)
2. Calcule os dois níveis-gatilho:

| Direção | Gatilho | Cálculo           |
|---------|---------|-------------------|
| **SELL** | 131.300 | 130.000 × 1,01   |
| **BUY**  | 128.700 | 130.000 × 0,99   |

---

## Durante o pregão (a partir das 9h)

Monitore: **se o preço tocar um dos gatilhos, entra imediatamente.**

### Se tocar 131.300 → SELL em 131.300

| Nível        | Cálculo            | Valor       |
|--------------|--------------------|-------------|
| Entrada      | —                  | **131.300** |
| Stop Loss (SL 0,75%) | 131.300 × 1,0075 | **132.285** |
| Stop Gain (SG 0,50%) | 131.300 × 0,9950 | **130.643** |

### Se tocar 128.700 → BUY em 128.700

| Nível        | Cálculo            | Valor       |
|--------------|--------------------|-------------|
| Entrada      | —                  | **128.700** |
| Stop Loss (SL 0,75%) | 128.700 × 0,9925 | **127.735** |
| Stop Gain (SG 0,50%) | 128.700 × 1,0050 | **129.343** |

---

## Regras de saída (em ordem de prioridade)

1. **SG atingido** → encerra com lucro (+0,50% sobre a entrada)
2. **SL atingido** → encerra com prejuízo (−0,75% sobre a entrada)
3. **16h00** → encerra no fechamento do candle das 16h, independente do resultado

---

## Apenas um sinal por dia

Só o **primeiro** gatilho atingido (SELL ou BUY) é operado. Se subir 1% e depois cair 1% no mesmo dia, só o SELL — que aconteceu primeiro — conta.

---

## Resultados do backtest (2024-01-01 a 2026-03-01)

| Signal | Operações | SG hits | SL hits | WinRate | P&L BRL total |
|--------|-----------|---------|---------|---------|---------------|
| BUY    | 90        | 61      | 29      | 67,78%  | R$ 1.924,87   |
| SELL   | 122       | 93      | 29      | 76,23%  | R$ 6.684,58   |

> Apesar do SG ser menor que o SL, a alta taxa de acerto compensa a assimetria de risco.
