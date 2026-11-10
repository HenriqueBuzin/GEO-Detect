"""Protocolo temporal e métricas compartilhados (sem vazamento)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from geodetect.dados import DEV

GAP = pd.DateOffset(months=1)  # o DETER público não informa a data de publicação
HORIZONTE = pd.DateOffset(months=3)
RAIO_UNIVERSO_CEL = 2  # 2 quadrados de 5 km = 10 km


def origens_dev() -> list[pd.Timestamp]:
    """Origens trimestrais cujo alvo [t, t+3m) termina dentro do desenvolvimento."""
    ini, fim = pd.Timestamp(DEV[0]), pd.Timestamp(DEV[1])
    out, t = [], ini
    while t + HORIZONTE - pd.Timedelta(days=1) <= fim:
        out.append(t)
        t = t + HORIZONTE
    return out


def corte(t: pd.Timestamp) -> pd.Timestamp:
    return t - GAP


def disponiveis(g: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """Alertas que poderiam ser conhecidos na origem t."""
    return g[g["view_date"] < corte(t)]


def alvo(g: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    return g[(g["view_date"] >= t) & (g["view_date"] < t + HORIZONTE)]


def universo_quadrados(cel_i: np.ndarray, cel_j: np.ndarray, raio: int = RAIO_UNIVERSO_CEL) -> list[str]:
    """Quadrados a até `raio` células (Chebyshev) de algum quadrado com alerta disponível."""
    base = np.unique(np.column_stack([cel_i, cel_j]), axis=0)
    r = np.arange(-raio, raio + 1)
    di, dj = np.meshgrid(r, r)
    viz = (base[:, None, :] + np.stack([di.ravel(), dj.ravel()], 1)[None, :, :]).reshape(-1, 2)
    u = np.unique(viz, axis=0)
    return [f"{i}_{j}" for i, j in u]


def ganho_esperado(score: np.ndarray, valor: np.ndarray, k: int) -> float:
    """Soma esperada de `valor` nas k células de maior `score`, com desempate aleatório."""
    k = min(k, len(score))
    if k <= 0:
        return 0.0
    s_ord = np.sort(score)[::-1]
    limiar = s_ord[k - 1]
    acima = score > limiar
    empate = score == limiar
    vagas = k - int(acima.sum())
    return float(valor[acima].sum() + vagas * valor[empate].mean())


def selecao_deterministica(score: np.ndarray, k: int, semente: int = 0) -> np.ndarray:
    """Índices das k maiores pontuações com desempate aleatório reprodutível (para estabilidade)."""
    rng = np.random.default_rng(semente)
    ordem = np.lexsort((rng.random(len(score)), -score))
    return ordem[: min(k, len(score))]


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a or b) else np.nan
