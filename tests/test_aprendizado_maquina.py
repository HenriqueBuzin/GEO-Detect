"""Regressões de vazamento e orçamento do experimento de ML, com dados sintéticos."""
import numpy as np
import pandas as pd

from conftest import carregar_script
from geodetect.grades import GradeQuadrada


def test_atributos_ml_ignoram_mes_de_gap_e_alertas_futuros(alertas_sinteticos):
    script = carregar_script('16_aprendizado_maquina')
    dados = alertas_sinteticos.copy()
    centro = dados.geometry.centroid
    dados['cx'], dados['cy'] = centro.x, centro.y
    dados['cel_i'] = np.floor(dados['cx'] / 5000).astype(int)
    dados['cel_j'] = np.floor(dados['cy'] / 5000).astype(int)
    dados['celula'] = GradeQuadrada(2500).celula_dos_centroides(dados).to_numpy()
    origem = pd.Timestamp('2024-04-01')
    passado = dados[dados.view_date < pd.Timestamp('2024-03-01')]
    esperado = script.atributos_historicos(passado, origem)
    observado = script.atributos_historicos(dados, origem)
    pd.testing.assert_frame_equal(esperado, observado)
    assert set(script.ATRIBUTOS).issubset(observado.columns)
    assert 'view_date' not in script.ATRIBUTOS


def test_ml_orcamento_e_alvos_fora_do_universo():
    script = carregar_script('16_aprendizado_maquina')
    frame = pd.DataFrame({
        'proprio_recente': [True] + [False] * 39,
        'sem_registro': [False] * 20 + [True] * 20,
    }, index=[str(i) for i in range(40)])
    tgt = pd.DataFrame({'celula': ['0', '20', 'fora'], 'sem_registro': [False, True, True]})
    score = np.arange(40, dtype=float)
    score[20] = 100
    resultado = script.avaliar(frame, tgt, score, 100, 'sintetico', pd.Timestamp('2024-01-01'))
    assert resultado['k'] == 2
    assert resultado['vagas_sem_registro'] == 1
    assert resultado['alvos_sem_registro'] == 2
    assert resultado['capturados_sem_registro'] == 1
    assert resultado['capturados_com_registro'] == 1


def test_previsao_global_nao_fixa_celulas_e_inclui_alvos_externos():
    script = carregar_script('18_previsao_espacial')
    frame = pd.DataFrame(index=[str(i) for i in range(40)])
    tgt = pd.DataFrame({'celula': ['0', '20', 'fora'], 'sem_registro': [False, True, True]})
    score = np.zeros(40)
    score[0], score[20], score[21] = -100, 100, 99
    resultado = script.avaliar(frame, tgt, score, 'sintetico', pd.Timestamp('2024-01-01'))
    assert resultado['k'] == 2
    assert resultado['alvos'] == 3
    assert resultado['capturados'] == 1
    assert resultado['alvos_sem_registro'] == 2
    assert resultado['capturados_sem_registro'] == 1
