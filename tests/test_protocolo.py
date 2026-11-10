"""Protocolo congelado: coerência, período reservado e ausência de vazamento (dados SINTÉTICOS, salvo indicação)."""

import json

import numpy as np
import pandas as pd
import pytest

from conftest import RAIZ, carregar_script
from geodetect.avaliacao import HORIZONTE, corte, disponiveis, ganho_esperado, origens_dev
from geodetect.dados import DEV
from geodetect.modelos import k_orcamento, media_vizinhos, pontuacoes, prob_selecao, soma_janela

PROTO = json.loads((RAIZ / "protocolo" / "protocolo_avaliacao_final.json").read_text(encoding="utf-8"))
ULTIMO_ALERTA_DISPONIVEL = pd.Timestamp("2026-10-28")  # view_date máximo do download congelado


def origens(grupo):
    return [pd.Timestamp(x) for x in PROTO["origens"][grupo]]


def test_parametros_congelados_coincidem_com_a_selecao_no_desenvolvimento():
    sel = json.loads((RAIZ / "results" / "hexagonal" / "selecao_parametros.json").read_text(encoding="utf-8"))["escolhas"]
    m = PROTO["modelos"]
    assert sel["h3_r7|C"] == f"C_{m['h3_r7_C']['w']}"
    assert sel["quadrado_2.5km|C"] == f"C_{m['quadrado_2.5km_C']['w']}"
    assert m["h3_r7_A"]["w"] is None and m["quadrado_5km_A"]["w"] is None
    assert PROTO["orcamento_primario"] == 0.02 and 0.02 in PROTO["orcamentos"]
    assert sum(c["primaria"] for c in PROTO["comparacoes"]) == 1


def test_periodo_reservado_nao_se_sobrepoe_ao_desenvolvimento():
    fim_dev = pd.Timestamp(DEV[1])
    for t in origens_dev():
        assert t + HORIZONTE - pd.Timedelta(days=1) <= fim_dev
    for grupo in ("teste_independente", "teste_semi_independente"):
        for t in origens(grupo):
            assert t > fim_dev                                         # alvo começa depois do desenvolvimento
            assert t + HORIZONTE - pd.Timedelta(days=1) <= ULTIMO_ALERTA_DISPONIVEL


def test_independente_so_usa_alvos_nao_vistos_espacialmente():
    """Alvos independentes devem começar em 2026 (a auditoria só viu o total anual de 2026)."""
    ind, semi = origens("teste_independente"), origens("teste_semi_independente")
    assert min(ind) >= pd.Timestamp("2026-01-01")
    assert all(pd.Timestamp("2025-07-01") <= t and t + HORIZONTE <= pd.Timestamp("2026-01-01") for t in semi)
    janelas = sorted((t, t + HORIZONTE) for t in ind + semi)
    assert all(a[1] <= b[0] for a, b in zip(janelas, janelas[1:]))   # janelas de alvo não se sobrepõem


def test_pontuacao_recusa_informacao_futura():
    t = pd.Timestamp("2026-04-01")
    disp = pd.DataFrame({"view_date": pd.to_datetime(["2026-03-05"]), "celula": ["x"], "chave": [0]})
    with pytest.raises(ValueError, match="vazamento"):
        pontuacoes(np.array(["x"]), np.array([["y"]], dtype=object), disp, t, {"A": None})


def test_pontuacao_identica_ao_script05_e_sem_vazamento():
    mod5 = carregar_script("05_compare_grids")
    t = pd.Timestamp("2026-01-01")
    ev = pd.DataFrame({  # SINTÉTICO
        "chave": range(7), "celula": ["a", "a", "b", "c", "a", "b", "d"],
        "view_date": pd.to_datetime(["2023-06-01", "2025-03-01", "2025-08-01", "2025-11-30",
                                     "2025-12-01", "2026-02-01", "2026-05-01"]),
    })
    cel = np.array(["a", "b", "c", "d"])
    viz = np.array([["b", "c"], ["a", "d"], ["a", "d"], ["b", "c"]], dtype=object)
    disp = disponiveis(ev, t)
    assert disp["view_date"].max() < corte(t)
    s = pontuacoes(cel, viz, disp, t, {"A": None, "C": 0.5})
    a24 = mod5.soma_janela(disp, "celula", corte(t) - pd.DateOffset(months=24))
    np.testing.assert_array_equal(s["A"], a24.reindex(cel).fillna(0).to_numpy(float))
    np.testing.assert_allclose(s["C"], s["A"] + 0.5 * mod5.media_vizinhos(a24, viz))
    # alertas no mês cego ou no alvo não mudam nada
    ev2 = pd.concat([ev, pd.DataFrame({"chave": [90, 91], "celula": ["d", "d"],
                                       "view_date": pd.to_datetime(["2025-12-15", "2026-01-10"])})])
    s2 = pontuacoes(cel, viz, disponiveis(ev2, t), t, {"A": None, "C": 0.5})
    for m in s:
        np.testing.assert_array_equal(s[m], s2[m])
    np.testing.assert_array_equal(soma_janela(disp, "celula", corte(t) - pd.DateOffset(months=24)), a24)
    np.testing.assert_array_equal(media_vizinhos(a24, viz), mod5.media_vizinhos(a24, viz))


@pytest.mark.parametrize("k", range(0, 9))
def test_prob_selecao_consistente_com_ganho_esperado(k):
    score = np.array([3, 2, 2, 2, 1, 1, 0, 0], dtype=float)
    valor = np.array([1, 0, 2, 1, 0, 1, 1, 0], dtype=float)
    p = prob_selecao(score, k)
    assert p.sum() == pytest.approx(min(k, len(score)))
    assert (p * valor).sum() == pytest.approx(ganho_esperado(score, valor, k))


def test_k_orcamento_iguala_area():
    assert k_orcamento(0.02, 25 * 6000, 25.0) == 120
    assert k_orcamento(0.02, 25 * 6000, 5.673) == round(0.02 * 150000 / 5.673)
    assert k_orcamento(0.0001, 25.0, 25.0) == 1


def test_script_final_tem_travas_de_execucao_unica():
    fonte = (RAIZ / "scripts" / "07_final_evaluation.py").read_text(encoding="utf-8")
    assert "já existe. A avaliação final só pode ser executada uma vez" in fonte
    assert 'execucao["git"] = verificar_git()' in fonte
    assert "SHA-256 dos dados difere do protocolo" in fonte
    assert 'fim_dados = DEV[1] if args.modo == "dev"' in fonte


VALIDACAO = RAIZ / "results" / "avaliacao_final" / "dev" / "por_origem.csv"


@pytest.mark.skipif(not VALIDACAO.exists(), reason="rode scripts/07_final_evaluation.py --modo dev")
def test_modo_dev_reproduz_script05():
    """Dados REAIS: o pipeline final reproduz exatamente o exploratório nas origens de desenvolvimento."""
    a = pd.read_csv(VALIDACAO)
    b = pd.read_csv(RAIZ / "results" / "hexagonal" / "comparacao_por_origem.csv")
    mapa = {m: (v["grade"], "A" if v["w"] is None else f"C_{v['w']}") for m, v in PROTO["modelos"].items()}
    a["grade05"] = a["modelo"].map(lambda m: mapa[m][0])
    a["metodo05"] = a["modelo"].map(lambda m: mapa[m][1])
    m = a.merge(b, left_on=["grade05", "metodo05", "origem", "orcamento"],
                right_on=["grade", "metodo", "origem", "fracao"], suffixes=("", "_05"))
    assert len(m) == len(a)
    for c in ("recall_alertas", "recall_area", "recall_celulas", "k"):
        np.testing.assert_allclose(m[c], m[f"{c}_05"], atol=1e-4)
