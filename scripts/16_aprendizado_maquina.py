"""Gradient boosting para priorização de alertas, somente no desenvolvimento.

Treino expansivo com alvos inteiramente anteriores ao corte de cada origem.
Configuração fixa; nenhuma seleção de hiperparâmetros nos alvos avaliados.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('OMP_NUM_THREADS', '2')

import numpy as np
import pandas as pd
import sklearn
from scipy.spatial import cKDTree
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from threadpoolctl import threadpool_limits

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from geodetect.avaliacao import HORIZONTE, alvo, corte, disponiveis, origens_dev, universo_quadrados
from geodetect.dados import DEV, carregar_preparado
from geodetect.grades import GradeQuadrada
from geodetect.modelos import k_orcamento, media_vizinhos, prob_selecao

ATRIBUTOS = [
    'distancia_recente', 'distancia_quinto', 'distancia_historico',
    'alertas_1km', 'alertas_3km', 'alertas_10km',
    'vizinhos_3m', 'vizinhos_12m', 'vizinhos_24m', 'fracao_vizinhos_ativos',
    'historico_total', 'dias_ultimo_proprio',
]
PARAMETROS = dict(
    learning_rate=0.08, max_iter=100, max_leaf_nodes=7, min_samples_leaf=30,
    l2_regularization=1.0, max_bins=63, early_stopping=False,
    class_weight='balanced', random_state=2027,
)
PARAMETROS_RF = dict(
    n_estimators=100, max_depth=8, min_samples_leaf=30, max_features='sqrt',
    class_weight='balanced_subsample', random_state=2027, n_jobs=2,
)


def atributos_historicos(dados: pd.DataFrame, origem: pd.Timestamp) -> pd.DataFrame:
    """Os atributos e a população elegível usam apenas informações anteriores ao corte."""
    grade = GradeQuadrada(2500)
    disp = disponiveis(dados, origem)
    recente = disp[disp.view_date >= corte(origem) - pd.DateOffset(months=24)]
    universo = universo_quadrados(disp.cel_i.to_numpy(), disp.cel_j.to_numpy())
    celulas = grade.celulas_por_quadrado(universo).index.to_numpy()
    centros = grade.poligonos(celulas).centroid
    xy = np.column_stack((centros.x, centros.y))
    arvore = cKDTree(recente[['cx', 'cy']])
    distancia = arvore.query(xy, k=min(5, len(recente)))[0]
    if distancia.ndim == 1:
        distancia = distancia[:, None]
    frame = pd.DataFrame(index=pd.Index(celulas, name='celula'))
    frame['distancia_recente'] = distancia[:, 0]
    frame['distancia_quinto'] = distancia[:, -1]
    frame['distancia_historico'] = cKDTree(disp[['cx', 'cy']]).query(xy)[0]
    for raio in (1, 3, 10):
        frame[f'alertas_{raio}km'] = arvore.query_ball_point(xy, raio * 1000, return_length=True)
    vizinhos = grade.vizinhos(celulas)
    viz = np.array([vizinhos[c] for c in celulas], dtype=object)
    for meses in (3, 12, 24):
        eventos = disp[disp.view_date >= corte(origem) - pd.DateOffset(months=meses)]
        contagem = eventos.groupby('celula').size()
        frame[f'vizinhos_{meses}m'] = media_vizinhos(contagem, viz)
    frame['fracao_vizinhos_ativos'] = media_vizinhos(contagem.gt(0).astype(float), viz)
    frame['historico_total'] = disp.groupby('celula').size().reindex(celulas, fill_value=0)
    ultima = disp.groupby('celula').view_date.max().reindex(celulas)
    frame['dias_ultimo_proprio'] = (corte(origem) - ultima).dt.days
    frame['proprio_recente'] = frame.index.isin(recente.celula.unique())
    frame['sem_registro'] = frame.historico_total == 0
    return frame


def avaliar(frame, tgt, score, regra, modelo, origem):
    k = k_orcamento(.05, 6.25 * len(frame), 6.25)
    proprio = frame.proprio_recente.to_numpy()
    novas = frame.sem_registro.to_numpy()
    antigas = ~novas & ~proprio
    vagas = k - proprio.sum()
    assert 0 < vagas <= min(novas.sum(), antigas.sum())
    p = proprio.astype(float)
    if regra == 'sem_reserva':
        p[~proprio] = prob_selecao(score[~proprio], vagas)
    else:
        fracao = regra / 100
        vagas_novas = int(round(fracao * vagas))
        p[novas] = prob_selecao(score[novas], vagas_novas)
        p[antigas] = prob_selecao(score[antigas], vagas - vagas_novas)
    assert np.isclose(p.sum(), k)
    capturas = pd.Series(p, index=frame.index).reindex(tgt.celula, fill_value=0).to_numpy()
    # A classificação dos alvos inclui os que ficaram fora do universo elegível.
    grupo_novo = tgt.sem_registro.to_numpy()
    return {
        'origem': str(origem.date()), 'modelo': modelo, 'regra': str(regra),
        'k': k, 'vagas_sem_registro': p[novas].sum(),
        'alvos': len(tgt), 'alvos_sem_registro': grupo_novo.sum(),
        'alvos_com_registro': (~grupo_novo).sum(),
        'capturados_sem_registro': capturas[grupo_novo].sum(),
        'capturados_com_registro': capturas[~grupo_novo].sum(),
    }


def main() -> None:
    proto = json.loads((RAIZ / 'protocolo/protocolo_avaliacao_final.json').read_text())
    entrada = RAIZ / proto['dados']['arquivo']
    with entrada.open('rb') as f:
        sha = hashlib.file_digest(f, 'sha256').hexdigest()
    if sha != proto['dados']['sha256']:
        raise ValueError('SHA-256 diverge dos dados congelados')
    dados = carregar_preparado(entrada)
    dados = dados[dados.view_date <= DEV[1]].copy()
    dados['celula'] = GradeQuadrada(2500).celula_dos_centroides(dados).to_numpy()
    origens = pd.date_range('2021-01-01', '2025-04-01', freq='QS')
    frames, alvos = {}, {}
    for t in origens:
        frames[t] = atributos_historicos(dados, t)
        tgt = alvo(dados, t).copy()
        tgt['sem_registro'] = ~tgt.celula.isin(disponiveis(dados, t).celula.unique())
        alvos[t] = tgt
    linhas, treinos = [], []
    for t in origens_dev():
        anteriores = [o for o in origens if o + HORIZONTE <= corte(t)]
        assert anteriores and max(o + HORIZONTE for o in anteriores) <= corte(t)
        treino = pd.concat([frames[o].loc[~frames[o].proprio_recente, ATRIBUTOS] for o in anteriores])
        rotulos = np.concatenate([
            frames[o].index[~frames[o].proprio_recente].isin(alvos[o].celula.unique())
            for o in anteriores
        ])
        if np.unique(rotulos).size != 2:
            raise ValueError('Treino sem as duas classes')
        scores = {'distancia': -np.round(frames[t].distancia_recente.to_numpy(), 0)}
        modelos = {
            'gradient_boosting': HistGradientBoostingClassifier(**PARAMETROS),
            'random_forest': RandomForestClassifier(**PARAMETROS_RF),
        }
        for nome, modelo in modelos.items():
            with threadpool_limits(limits=2):
                modelo.fit(treino, rotulos)
                scores[nome] = modelo.predict_proba(frames[t][ATRIBUTOS])[:, 1]
        # As pontuações servem para ranking, sem calibração operacional de probabilidades.
        for nome, score in scores.items():
            for regra in ('sem_reserva', 0, 25, 50, 75, 100):
                linhas.append(avaliar(frames[t], alvos[t], score, regra, nome, t))
        treinos.append({
            'origem': str(t.date()), 'origens_treino': len(anteriores), 'linhas': len(treino),
            'celulas_positivas': int(rotulos.sum()),
            'fim_ultimo_alvo_treino': str((max(anteriores) + HORIZONTE).date()),
            'corte': str(corte(t).date()),
        })
        print(t.date(), len(treino), int(rotulos.sum()), flush=True)
    resultado = pd.DataFrame(linhas)
    soma = resultado.groupby(['modelo', 'regra']).sum(numeric_only=True)
    for grupo in ('sem_registro', 'com_registro'):
        soma[f'recall_{grupo}'] = soma[f'capturados_{grupo}'] / soma[f'alvos_{grupo}']
    soma['recall_total'] = (soma.capturados_sem_registro + soma.capturados_com_registro) / soma.alvos
    # O controle deve reproduzir todas as políticas já registradas no script 15.
    referencia = pd.read_csv(RAIZ / 'results/custo_descoberta/por_origem.csv')
    referencia['regra'] = referencia.regra.replace({'distancia_sem_reserva': 'sem_reserva'}).str.replace('reserva_', '').str.replace('%', '')
    chaves = ['origem', 'regra']
    controle = resultado[resultado.modelo == 'distancia'].set_index(chaves).sort_index()
    referencia = referencia.set_index(chaves).sort_index()
    for coluna in ('capturados_sem_registro', 'capturados_com_registro', 'alvos'):
        np.testing.assert_allclose(controle[coluna], referencia[coluna], atol=1e-7, rtol=0)
    saida = RAIZ / 'results/aprendizado_maquina'
    saida.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(saida / 'por_origem.csv', index=False, float_format='%.8f')
    soma.to_csv(saida / 'agregado.csv', float_format='%.8f')
    pd.DataFrame(treinos).to_csv(saida / 'treinos.csv', index=False)
    (saida / 'execucao.json').write_text(json.dumps({
        'tipo': 'exploratorio', 'dados_sha256': sha, 'sklearn': sklearn.__version__,
        'modelos': {
            'HistGradientBoostingClassifier': PARAMETROS,
            'RandomForestClassifier': PARAMETROS_RF,
        }, 'atributos': ATRIBUTOS,
        'inicio_treino': '2021-01-01', 'limite_dados': DEV[1],
        'politica_treino': 'somente trimestres-alvo encerrados antes do corte da origem',
    }, indent=2, ensure_ascii=False))
    print(soma[['recall_sem_registro', 'recall_com_registro', 'recall_total']].mul(100).round(2))


if __name__ == '__main__':
    main()
