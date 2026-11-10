"""Protocolo temporal, prevenção de vazamento e métricas (dados SINTÉTICOS, salvo indicação)."""

import itertools

import numpy as np
import pandas as pd
import pytest

from conftest import RAIZ, carregar_script
from geodetect.avaliacao import (
    GAP, HORIZONTE, alvo, corte, disponiveis, ganho_esperado, jaccard, origens_dev, selecao_deterministica,
    universo_quadrados,
)
from geodetect.dados import DEV, TESTE


def alertas_tabela(datas, celulas, ij):
    """Tabela SINTÉTICA de alertas já atribuídos a células."""
    return pd.DataFrame({
        "chave": np.arange(len(datas)), "view_date": pd.to_datetime(datas), "celula": celulas,
        "cel_i": [a for a, _ in ij], "cel_j": [b for _, b in ij], "area_km2": 0.08,
    })


def test_origens_ficam_dentro_do_desenvolvimento():
    os_ = origens_dev()
    assert len(os_) == 6
    assert os_[0] == pd.Timestamp(DEV[0])
    assert all(t + HORIZONTE - pd.Timedelta(days=1) <= pd.Timestamp(DEV[1]) for t in os_)
    assert pd.Timestamp(DEV[1]) < pd.Timestamp(TESTE[0])


def test_disponiveis_respeita_gap_e_alvo_e_futuro():
    t = pd.Timestamp("2024-04-01")
    df = alertas_tabela(["2024-02-29", "2024-03-01", "2024-03-15", "2024-04-01", "2024-06-30", "2024-07-01"],
                        list("abcdef"), [(0, 0)] * 6)
    assert corte(t) == t - GAP == pd.Timestamp("2024-03-01")
    assert list(disponiveis(df, t)["celula"]) == ["a"]           # março é o mês "cego"
    assert list(alvo(df, t)["celula"]) == ["d", "e"]              # [abr, jul)
    assert disponiveis(df, t)["view_date"].max() < alvo(df, t)["view_date"].min()


def test_variaveis_e_universo_nao_mudam_com_alertas_futuros():
    mod5 = carregar_script("05_compare_grids")
    t = pd.Timestamp("2024-07-01")
    base = alertas_tabela(["2022-08-01", "2023-09-01", "2024-01-10", "2024-05-20"],
                          ["0_0", "0_0", "1_0", "5_5"], [(0, 0), (0, 0), (1, 0), (5, 5)])
    futuro = alertas_tabela(["2024-06-01", "2024-08-01", "2025-01-01"],
                            ["0_1", "1_1", "9_9"], [(0, 1), (1, 1), (9, 9)])
    futuro["chave"] += 100
    junto = pd.concat([base, futuro])

    def estado(df):
        d = disponiveis(df, t)
        u = universo_quadrados(d["cel_i"].to_numpy(), d["cel_j"].to_numpy())
        a24 = mod5.soma_janela(d, "celula", corte(t) - pd.DateOffset(months=24))
        viz = np.array([["0_1", "1_0", "1_1"]], dtype=object)
        return u, a24.to_dict(), mod5.media_vizinhos(a24, viz).tolist()

    assert estado(base) == estado(junto)


def test_variaveis_script03_nao_mudam_com_alertas_futuros():
    mod3 = carregar_script("03_baselines_dev")
    t = pd.Timestamp("2025-01-01")
    c = corte(t)
    base = alertas_tabela(["2023-01-01", "2024-06-01", "2024-11-30"], ["0_0", "0_0", "2_2"],
                          [(0, 0), (0, 0), (2, 2)])
    extra = alertas_tabela(["2024-12-05", "2025-02-01"], ["0_0", "3_3"], [(0, 0), (3, 3)])
    extra["chave"] += 50
    resultados = []
    for df in (base, pd.concat([base, extra])):
        d = df[df["view_date"] < c]
        u = mod3.universo(d)
        resultados.append(mod3.variaveis(u, d, c))
    pd.testing.assert_frame_equal(resultados[0], resultados[1])  # NaN == NaN aqui


def test_ganho_esperado_igual_media_das_permutacoes():
    rng = np.random.default_rng(1)
    score = np.array([3, 2, 2, 2, 1, 1, 0, 0], dtype=float)
    valor = rng.integers(0, 3, len(score)).astype(float)
    for k in range(len(score) + 2):
        # força bruta: média sobre todas as ordens de desempate
        ganhos = []
        for perm in itertools.permutations(range(len(score))):
            ordem = sorted(range(len(score)), key=lambda i: (-score[i], perm[i]))
            ganhos.append(valor[ordem[:k]].sum())
        assert ganho_esperado(score, valor, k) == pytest.approx(np.mean(ganhos))


def test_selecao_deterministica_e_jaccard():
    s = np.array([5, 1, 1, 1, 0.0])
    a, b = selecao_deterministica(s, 2, semente=3), selecao_deterministica(s, 2, semente=3)
    assert list(a) == list(b) and 0 in a
    assert jaccard([1, 2], [2, 3]) == pytest.approx(1 / 3)


def test_script05_descarta_teste_ao_carregar():
    fonte = (RAIZ / "scripts" / "05_compare_grids.py").read_text(encoding="utf-8")
    assert 'g = g[g["view_date"] <= DEV[1]]' in fonte
    for nome in ("03_baselines_dev", "04_hexagonal_grid", "06_temporal_neighbors"):
        assert "DEV[1]" in (RAIZ / "scripts" / f"{nome}.py").read_text(encoding="utf-8")


DADOS = RAIZ / "data" / "raw" / "deter_amz_mineracao_pa.geojson"


@pytest.mark.skipif(not DADOS.exists(), reason="dados reais não baixados (rode scripts/01_download_deter.py)")
def test_datas_dos_dados_reais():
    from geodetect.dados import carregar
    g = carregar(DADOS)
    assert len(g) == 6770
    assert g["view_date"].notna().all()
    assert (g["publish_month"].dt.to_period("M") == g["view_date"].dt.to_period("M")).all()
    rec = g[(g["view_date"] >= "2024-01-01") & (g["view_date"] <= "2025-12-31")]
    assert len(rec) == 820
