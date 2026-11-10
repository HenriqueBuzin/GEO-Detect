"""Pontuações congeladas e seleção sob orçamento (fonte única para a avaliação final).

As fórmulas são idênticas às do script 05 (verificado em teste):
    A(c)   = nº de alertas com centroide em c e view_date em [corte − 24 meses, corte)
    C_w(c) = A(c) + w · média de A nos vizinhos imediatos de c (6 no H3, 8 no quadrado)
Vizinhos sem alerta contam como zero. Empates no ponto de corte são tratados pela
expectativa sob desempate aleatório: cada célula empatada recebe probabilidade
vagas / n_empatadas de ser selecionada.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geodetect.avaliacao import corte

JANELA_A_MESES = 24


def soma_janela(eventos: pd.DataFrame, col_cel: str, ini: pd.Timestamp, valor: str | None = None) -> pd.Series:
    sub = eventos[eventos["view_date"] >= ini]
    return sub.groupby(col_cel).size() if valor is None else sub.groupby(col_cel)[valor].sum()


def media_vizinhos(valores: pd.Series, viz: np.ndarray) -> np.ndarray:
    """viz: matriz (n, m) de ids de vizinhos; valores ausentes contam como zero."""
    v = valores.reindex(viz.ravel()).fillna(0).to_numpy().reshape(viz.shape)
    return v.mean(1)


def pontuacoes(celulas: np.ndarray, viz: np.ndarray, disp: pd.DataFrame, t: pd.Timestamp,
               modelos: dict[str, float | None]) -> dict[str, np.ndarray]:
    """modelos: nome → w (None para A, sem vizinhança). `disp` já deve conter só alertas < corte(t)."""
    if len(disp) and disp["view_date"].max() >= corte(t):
        raise ValueError("vazamento: alerta com view_date >= corte da origem")
    a = soma_janela(disp, "celula", corte(t) - pd.DateOffset(months=JANELA_A_MESES))
    cnt = a.reindex(celulas).fillna(0).to_numpy(float)
    nb = media_vizinhos(a, viz)
    return {m: cnt if w is None else cnt + w * nb for m, w in modelos.items()}


def k_orcamento(fracao: float, area_universo_km2: float, area_media_celula_km2: float) -> int:
    return max(1, int(round(fracao * area_universo_km2 / area_media_celula_km2)))


def prob_selecao(score: np.ndarray, k: int) -> np.ndarray:
    """Probabilidade de cada célula estar entre as k selecionadas (desempate aleatório)."""
    n = len(score)
    k = min(k, n)
    p = np.zeros(n)
    if k <= 0:
        return p
    limiar = np.sort(score)[::-1][k - 1]
    acima, empate = score > limiar, score == limiar
    p[acima] = 1.0
    p[empate] = (k - acima.sum()) / empate.sum()
    return p
