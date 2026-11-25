"""Benchmark exploratório de ranking global, sem vagas reservadas ou seleção fixa."""
from __future__ import annotations
import hashlib
import json
import runpy
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingRegressor
from sklearn.naive_bayes import GaussianNB
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

RAIZ = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(RAIZ / 'scripts/16_aprendizado_maquina.py'))


def avaliar(frame, tgt, score, modelo, origem):
    k = M['k_orcamento'](.05, 6.25 * len(frame), 6.25)
    p = pd.Series(M['prob_selecao'](score, k), index=frame.index)
    assert np.isclose(p.sum(), k)
    capturas = p.reindex(tgt.celula, fill_value=0).to_numpy()
    novas = tgt.sem_registro.to_numpy()
    return dict(origem=str(origem.date()), modelo=modelo, k=k, celulas_elegiveis=len(frame), alvos=len(tgt),
                capturados=float(capturas.sum()), alvos_sem_registro=int(novas.sum()),
                capturados_sem_registro=float(capturas[novas].sum()))


def main():
    proto = json.loads((RAIZ / 'protocolo/protocolo_avaliacao_final.json').read_text())
    entrada = RAIZ / proto['dados']['arquivo']
    with entrada.open('rb') as arquivo:
        sha = hashlib.file_digest(arquivo, 'sha256').hexdigest()
    assert sha == proto['dados']['sha256']
    dados = M['carregar_preparado'](entrada)
    dados = dados[dados.view_date <= M['DEV'][1]].copy()
    dados['celula'] = M['GradeQuadrada'](2500).celula_dos_centroides(dados).to_numpy()
    origens = pd.date_range('2021-01-01', '2025-04-01', freq='QS')
    frames, alvos = {}, {}
    for t in origens:
        frames[t] = M['atributos_historicos'](dados, t)
        tgt = M['alvo'](dados, t).copy()
        tgt['sem_registro'] = ~tgt.celula.isin(M['disponiveis'](dados, t).celula.unique())
        alvos[t] = tgt
    linhas, treinos = [], []
    for t in M['origens_dev']():
        anteriores = [o for o in origens if o + M['HORIZONTE'] <= M['corte'](t)]
        assert anteriores and max(o + M['HORIZONTE'] for o in anteriores) <= M['corte'](t)
        treino = pd.concat([frames[o][M['ATRIBUTOS']] for o in anteriores])
        rotulos = np.concatenate([frames[o].index.isin(alvos[o].celula.unique()) for o in anteriores])
        disp = M['disponiveis'](dados, t)
        recente = disp[disp.view_date >= M['corte'](t) - pd.DateOffset(months=24)]
        scores = {
            'proximidade': -np.round(frames[t].distancia_recente.to_numpy(), 0),
            'recorrencia': recente.groupby('celula').size().reindex(frames[t].index, fill_value=0).to_numpy(),
        }
        modelos = {
            'random_forest': M['RandomForestClassifier'](**M['PARAMETROS_RF']),
            'gradient_boosting': M['HistGradientBoostingClassifier'](**M['PARAMETROS']),
            'extra_trees': ExtraTreesClassifier(n_estimators=100, max_depth=8, min_samples_leaf=30, max_features='sqrt', class_weight='balanced', random_state=2027, n_jobs=2),
            'naive_bayes': make_pipeline(SimpleImputer(strategy='median', add_indicator=True), GaussianNB(priors=[0.5, 0.5], var_smoothing=1e-9)),
            'poisson_boosting': HistGradientBoostingRegressor(loss='poisson', learning_rate=.08, max_iter=100, max_leaf_nodes=7, min_samples_leaf=30, l2_regularization=1, max_bins=63, early_stopping=False, random_state=2027),
            'regressao_logistica': make_pipeline(SimpleImputer(strategy='median', add_indicator=True),
                StandardScaler(), LogisticRegression(C=1, class_weight='balanced', max_iter=500, random_state=2027)),
        }
        for nome, modelo in modelos.items():
            with M['threadpool_limits'](limits=2), warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                if nome == 'poisson_boosting':
                    contagens = np.concatenate([alvos[o].groupby('celula').size().reindex(frames[o].index, fill_value=0).to_numpy() for o in anteriores])
                    modelo.fit(treino, contagens)
                    scores[nome] = modelo.predict(frames[t][M['ATRIBUTOS']])
                else:
                    modelo.fit(treino, rotulos)
                    scores[nome] = modelo.predict_proba(frames[t][M['ATRIBUTOS']])[:, 1]
        for nome, score in scores.items():
            linhas.append(avaliar(frames[t], alvos[t], score, nome, t))
        treinos.append(dict(origem=str(t.date()), linhas=len(treino), positivos=int(rotulos.sum()),
                           corte=str(M['corte'](t).date()), fim_ultimo_alvo=str((max(anteriores) + M['HORIZONTE']).date())))
        print(t.date(), len(treino), int(rotulos.sum()), flush=True)
    resultado = pd.DataFrame(linhas)
    saida = RAIZ / 'results/previsao'
    if (saida / 'por_origem.csv').exists():
        anterior = pd.read_csv(saida / 'por_origem.csv')
        chave = ['origem', 'modelo']
        comum = resultado.set_index(chave).sort_index().loc[anterior.set_index(chave).sort_index().index]
        np.testing.assert_allclose(comum[['k', 'alvos', 'capturados', 'capturados_sem_registro']], anterior.set_index(chave).sort_index()[['k', 'alvos', 'capturados', 'capturados_sem_registro']], atol=1e-7, rtol=0)
    soma = resultado.groupby('modelo').sum(numeric_only=True)
    soma['recall_total'] = soma.capturados / soma.alvos
    soma['recall_sem_registro'] = soma.capturados_sem_registro / soma.alvos_sem_registro
    saida = RAIZ / 'results/previsao'
    resultado.to_csv(saida / 'por_origem.csv', index=False, float_format='%.8f')
    soma.to_csv(saida / 'agregado.csv', float_format='%.8f')
    pd.DataFrame(treinos).to_csv(saida / 'treinos.csv', index=False)
    (saida / 'execucao.json').write_text(json.dumps(dict(tipo='exploratorio', dados_sha256=sha,
        sklearn=M['sklearn'].__version__, atributos=M['ATRIBUTOS'], orcamento=.05, reserva=False,
        selecao_fixa=False, limite_dados=M['DEV'][1], hgb=M['PARAMETROS'], rf=M['PARAMETROS_RF'],
        extra_trees=dict(n_estimators=100, max_depth=8, min_samples_leaf=30, max_features='sqrt', class_weight='balanced', random_state=2027, n_jobs=2),
        naive_bayes=dict(var_smoothing=1e-9, priors=[0.5, 0.5], imputacao='median + missing indicator'),
        poisson_boosting=dict(loss='poisson', learning_rate=.08, max_iter=100, max_leaf_nodes=7, min_samples_leaf=30, l2_regularization=1, max_bins=63, early_stopping=False, random_state=2027),
        logistica=dict(C=1, max_iter=500, class_weight='balanced', random_state=2027,
                       imputacao='median + missing indicator', escala='StandardScaler')),
        indent=2, ensure_ascii=False))
    ordem = ['regressao_logistica', 'naive_bayes', 'poisson_boosting', 'gradient_boosting', 'random_forest', 'extra_trees']
    melhor = max(soma.loc[ordem, 'capturados'])
    vencedor = next(n for n in ordem if abs(soma.loc[n, 'capturados'] - melhor) <= 1e-7)
    (saida / 'selecao.json').write_text(json.dumps(dict(modelo=vencedor, criterio='maior cobertura agregada no desenvolvimento a 5% da area', capturados=float(melhor), recall=float(soma.loc[vencedor, 'recall_total']), controles={n:float(soma.loc[n, 'capturados']) for n in ['proximidade','recorrencia']}, alcance='selecionado no desenvolvimento; sem confirmacao independente', regra_desempate=ordem), ensure_ascii=False, indent=2))
    config = json.loads((saida / 'execucao.json').read_text())
    chaves = {'regressao_logistica': 'logistica', 'naive_bayes': 'naive_bayes', 'poisson_boosting': 'poisson_boosting', 'gradient_boosting': 'hgb', 'random_forest': 'rf', 'extra_trees': 'extra_trees'}
    (saida / 'modelo_selecionado.json').write_text(json.dumps(dict(modelo=vencedor, parametros=config[chaves[vencedor]], atributos=M['ATRIBUTOS'], dados_sha256=sha, unidade='quadrado de 2,5 km', horizonte_meses=3, gap_meses=1, orcamento=.05, reserva=False, criterio='maior cobertura agregada no desenvolvimento', alcance='configuração selecionada no desenvolvimento; sem teste independente; não contém pesos para implantação'), ensure_ascii=False, indent=2))
    print(soma[['capturados', 'recall_total', 'capturados_sem_registro', 'recall_sem_registro']].to_string())


if __name__ == '__main__':
    main()
