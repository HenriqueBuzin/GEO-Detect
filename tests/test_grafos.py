"""Grafo espaçotemporal: arestas, componentes, pesos e vazamento (dados SINTÉTICOS)."""

import numpy as np
import pandas as pd
import pytest

from conftest import RAIZ, carregar_script
from geodetect.avaliacao import corte, disponiveis
from geodetect.grafos import arestas, componentes, janela_historica, pesos, pontuacao_celulas
from geodetect.modelos import pontuacoes


def alertas(xs, ys, datas, celulas):
    """Alertas SINTÉTICOS com centroide (cx, cy) em metros."""
    return pd.DataFrame({"chave": range(len(xs)), "cx": np.asarray(xs, float), "cy": np.asarray(ys, float),
                         "view_date": pd.to_datetime(datas), "celula": celulas})


def test_arestas_respeitam_distancia_e_intervalo():
    d = alertas([0, 900, 1500, 0], [0, 0, 0, 500],
                ["2024-01-01", "2024-01-20", "2024-01-25", "2024-06-01"], list("abcd"))
    e = {tuple(p) for p in arestas(d["cx"].to_numpy(), d["cy"].to_numpy(), d["view_date"], 1000, 30)}
    assert e == {(0, 1), (1, 2)}          # 0–2: 1,5 km; 0–3: 152 dias
    # com 365 dias entra 0–3 (500 m); 1–3 fica de fora (1.029 m > 1 km)
    assert {tuple(p) for p in arestas(d["cx"].to_numpy(), d["cy"].to_numpy(), d["view_date"], 1000, 365)} == {(0, 1), (1, 2), (0, 3)}


def test_componentes_e_tamanhos():
    rot, tam = componentes(5, np.array([[0, 1], [1, 2]]))
    assert len(set(rot[:3])) == 1 and rot[3] != rot[4]
    assert list(tam) == [3, 3, 3, 1, 1]
    rot0, tam0 = componentes(3, np.empty((0, 2), dtype=int))
    assert list(tam0) == [1, 1, 1]


def test_janela_historica_recusa_futuro_e_corta_24_meses():
    t = pd.Timestamp("2025-04-01")
    d = alertas([0, 0, 0], [0, 0, 0], ["2023-02-27", "2023-03-02", "2025-02-28"], list("abc"))
    h = janela_historica(d, t)
    assert list(h["celula"]) == ["b", "c"]           # corte = 2025-03-01; janela começa em 2023-03-01
    with pytest.raises(ValueError, match="vazamento"):
        janela_historica(alertas([0], [0], ["2025-03-01"], ["x"]), t)


def test_pesos_casos_limite():
    t = pd.Timestamp("2025-04-01")
    d = alertas([0, 100, 50_000], [0, 0, 0], ["2025-01-01", "2025-01-10", "2025-02-01"], list("aab"))
    assert np.allclose(pesos(d, t, "A"), 1)
    np.testing.assert_allclose(pesos(d, t, "G", d_s_m=1000, d_t_dias=30), [1 + np.log(2), 1 + np.log(2), 1])
    idade = (corte(t) - d["view_date"]).dt.days.to_numpy()
    np.testing.assert_allclose(pesos(d, t, "T", tau=180), np.exp(-idade / 180))
    np.testing.assert_allclose(pesos(d, t, "GT", tau=180, d_s_m=1000, d_t_dias=30),
                               pesos(d, t, "G", d_s_m=1000, d_t_dias=30) * np.exp(-idade / 180))


def test_peso_unitario_reproduz_modelo_C_congelado():
    t = pd.Timestamp("2025-01-01")
    d = alertas([0, 10, 20, 30], [0, 0, 0, 0], ["2023-05-01", "2024-03-01", "2024-06-01", "2024-11-20"], list("aabc"))
    cel = np.array(["a", "b", "c", "z"])
    viz = np.array([["b", "c"], ["a", "z"], ["a", "z"], ["b", "c"]], dtype=object)
    h = janela_historica(disponiveis(d, t), t)
    s_grafo = pontuacao_celulas(cel, viz, h, pesos(h, t, "A"), w=0.5)
    s_c = pontuacoes(cel, viz, disponiveis(d, t), t, {"C": 0.5})["C"]
    np.testing.assert_allclose(s_grafo, s_c)


def test_alertas_futuros_nao_alteram_pesos_nem_pontuacao():
    t = pd.Timestamp("2024-10-01")
    base = alertas([0, 500, 4000], [0, 0, 0], ["2024-05-01", "2024-05-15", "2024-08-20"], list("aab"))
    fut = alertas([200, 300], [0, 0], ["2024-09-10", "2024-10-05"], ["a", "c"])
    fut["chave"] += 10
    cel = np.array(["a", "b", "c"])
    viz = np.array([["b", "c"], ["a", "c"], ["a", "b"]], dtype=object)
    res = []
    for d in (base, pd.concat([base, fut])):
        h = janela_historica(disponiveis(d, t), t)
        res.append(pontuacao_celulas(cel, viz, h, pesos(h, t, "GT", tau=365, d_s_m=1000, d_t_dias=60)))
    np.testing.assert_array_equal(res[0], res[1])


def test_script10_le_so_desenvolvimento():
    fonte = (RAIZ / "scripts" / "10_temporal_graphs.py").read_text(encoding="utf-8")
    assert 'g = g[g["view_date"] <= DEV[1]]' in fonte
    mod = carregar_script("10_temporal_graphs")
    assert len(mod.configuracoes()) == 2 + 2 + 4 + 9 + 36
