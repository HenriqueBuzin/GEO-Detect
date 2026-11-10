"""Grafo espaçotemporal de alertas e pontuações interpretáveis por célula (GEO-Detect).

Grafo G = (V, E):
    V  alertas com view_date em [corte − 24 meses, corte)  (só informação disponível na origem)
    E  (i, j) se distância entre centroides ≤ d_s  E  |data_i − data_j| ≤ d_t
Componentes conexos = "episódios" espaçotemporais: cadeias de alertas próximos no espaço e no tempo.

Peso de cada alerta i (idade_i = dias entre a data do alerta e o corte; n_i = tamanho do episódio de i):
    A    1                                       (frequência histórica)
    T    exp(−idade_i / τ)                       (só decaimento temporal)
    G    1 + ln(n_i)                             (só estrutura do grafo: alerta isolado vale 1)
    GT   (1 + ln(n_i)) · exp(−idade_i / τ)       (grafo + decaimento)
Pontuação da célula = V(c) + w · média de V nos vizinhos imediatos, com V(c) = soma dos pesos dos
alertas cujo centroide está em c, e w = 0,5 (o mesmo do modelo C congelado). Assim, a única
diferença entre os modelos é a informação temporal/estrutural contida nos pesos.

As arestas são relações matemáticas definidas por limiares; não indicam deslocamento físico da
mineração nem vínculo entre atividades.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from geodetect.avaliacao import corte
from geodetect.modelos import media_vizinhos

JANELA_MESES = 24
W_VIZINHOS = 0.5


def janela_historica(disp: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """Alertas na janela [corte − 24 meses, corte). Falha se houver informação futura."""
    c = corte(t)
    if len(disp) and disp["view_date"].max() >= c:
        raise ValueError("vazamento: alerta com view_date >= corte da origem")
    return disp[disp["view_date"] >= c - pd.DateOffset(months=JANELA_MESES)]


def arestas(x: np.ndarray, y: np.ndarray, datas: pd.Series, d_s_m: float, d_t_dias: float) -> np.ndarray:
    """Pares (i, j), i < j, com distância ≤ d_s e |Δt| ≤ d_t."""
    if len(x) < 2:
        return np.empty((0, 2), dtype=int)
    pares = cKDTree(np.column_stack([x, y])).query_pairs(d_s_m, output_type="ndarray")
    if len(pares) == 0:
        return pares.reshape(0, 2)
    d = datas.to_numpy().astype("datetime64[D]").astype(np.int64)
    ok = np.abs(d[pares[:, 0]] - d[pares[:, 1]]) <= d_t_dias
    return pares[ok]


def componentes(n: int, e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rótulo do componente de cada nó e tamanho do componente de cada nó."""
    if n == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    m = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)) if len(e) else coo_matrix((n, n))
    _, rot = connected_components(m, directed=False)
    tam = np.bincount(rot)[rot]
    return rot, tam


def pesos(hist: pd.DataFrame, t: pd.Timestamp, modelo: str, tau: float | None = None,
          d_s_m: float | None = None, d_t_dias: float | None = None) -> np.ndarray:
    """Peso de cada alerta da janela histórica segundo o modelo (A, T, G, GT)."""
    n = len(hist)
    idade = (corte(t) - hist["view_date"]).dt.days.to_numpy(float)
    if modelo == "A":
        return np.ones(n)
    if modelo == "T":
        return np.exp(-idade / tau)
    _, tam = componentes(n, arestas(hist["cx"].to_numpy(), hist["cy"].to_numpy(), hist["view_date"], d_s_m, d_t_dias))
    g = 1.0 + np.log(np.maximum(tam, 1))
    if modelo == "G":
        return g
    if modelo == "GT":
        return g * np.exp(-idade / tau)
    raise ValueError(modelo)


def pontuacao_celulas(celulas: np.ndarray, viz: np.ndarray, hist: pd.DataFrame, peso: np.ndarray,
                      w: float = W_VIZINHOS) -> np.ndarray:
    """V(c) + w · média de V nos vizinhos, com V = soma dos pesos dos alertas na célula."""
    v = pd.Series(peso, index=hist["celula"].to_numpy()).groupby(level=0).sum()
    own = v.reindex(celulas).fillna(0).to_numpy(float)
    return own + w * media_vizinhos(v, viz)
