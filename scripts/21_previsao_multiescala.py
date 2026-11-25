"""Compara escalas e modelos para prever alertas DETER com histórico disponível."""
from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingRegressor
from sklearn.metrics import average_precision_score

RAIZ = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(RAIZ / 'scripts/16_aprendizado_maquina.py'))
ESCALAS = (1250, 2500, 5000)
REFERENCIA = 'extra_trees_original_2500'
EXTRA = dict(n_estimators=100, max_depth=8, min_samples_leaf=30, max_features='sqrt',
             class_weight='balanced', random_state=2027, n_jobs=2)
POISSON = dict(loss='poisson', learning_rate=.08, max_iter=100, max_leaf_nodes=7,
               min_samples_leaf=30, l2_regularization=1, max_bins=63,
               early_stopping=False, random_state=2027)


def preparar_origem(dados, origem, lado):
    grade = M['GradeQuadrada'](lado)
    corte = M['corte'](origem)
    disp = M['disponiveis'](dados, origem)
    quadrados = M['universo_quadrados'](disp.cel_i.to_numpy(), disp.cel_j.to_numpy())
    indice = grade.celulas_por_quadrado(quadrados).index
    xy = (grade._ij(indice) + .5) * lado
    idade = (corte - disp.view_date).dt.days.to_numpy()
    recente = (disp.view_date >= corte - pd.DateOffset(months=24)).to_numpy()
    sazonal = (disp.view_date.dt.quarter == origem.quarter).to_numpy()
    area = np.log1p(disp.area_km2.to_numpy())
    eventos = disp[['cx', 'cy']].to_numpy()
    arvore = cKDTree(eventos)
    arvore_recente = cKDTree(eventos[recente])
    distancias = arvore_recente.query(xy, k=[1, 5])[0]
    frame = pd.DataFrame(index=indice)
    frame['distancia_recente'] = distancias[:, 0]
    frame['distancia_quinto'] = distancias[:, 1]
    frame['distancia_historico'] = arvore.query(xy)[0]
    for raio in (1000, 3000, 10000):
        frame[f'alertas_{raio}m'] = arvore_recente.query_ball_point(
            xy, raio, return_length=True
        )

    # Kernels gaussianos truncados a 4 desvios. Uma consulta cobre todos os raios.
    pares = cKDTree(xy).sparse_distance_matrix(arvore, 24000, output_type='coo_matrix')
    linha, evento = pares.row, pares.col
    distancia = pares.data
    for raio in (1500, 3000, 6000):
        base = np.exp(-.5 * (distancia / raio) ** 2) * (distancia <= 4 * raio)
        for meia_vida in (90, 180, 540):
            peso = base * np.exp2(-idade[evento] / meia_vida)
            frame[f'densidade_{raio}m_{meia_vida}d'] = np.bincount(
                linha, weights=peso, minlength=len(frame)
            )
        frame[f'sazonal_{raio}m'] = np.bincount(
            linha, weights=base * sazonal[evento], minlength=len(frame)
        )
        frame[f'area_{raio}m'] = np.bincount(
            linha, weights=base * area[evento] * np.exp2(-idade[evento] / 540),
            minlength=len(frame),
        )

    proprio = disp.groupby('celula').view_date
    frame['historico_total'] = proprio.size().reindex(indice, fill_value=0)
    frame['dias_ultimo_proprio'] = (corte - proprio.max().reindex(indice)).dt.days
    for meses in (3, 12, 24):
        janela = disp.view_date >= corte - pd.DateOffset(months=meses)
        frame[f'proprio_{meses}m'] = disp.loc[janela, 'celula'].value_counts().reindex(
            indice, fill_value=0
        )

    alvo = M['alvo'](dados, origem).copy()
    alvo['sem_registro'] = ~alvo.celula.isin(disp.celula)
    contagens = alvo.celula.value_counts().reindex(indice, fill_value=0).to_numpy()
    return frame.astype('float32'), alvo, contagens


def avaliar(frame, alvo, score, origem, modelo, lado):
    """Projeta o ranking na mesma grade fina e penaliza alvos fora da região pontuada."""
    assert len(score) == len(frame) and np.isfinite(score).all()
    grade_fina = M['GradeQuadrada'](ESCALAS[0])
    subcelulas = grade_fina.celulas_por_quadrado(frame.index, lado_ref_m=lado)
    repeticoes = (lado // grade_fina.lado_m) ** 2
    score_fino = np.repeat(score, repeticoes)
    celulas_alvo = pd.Index(alvo.celula_fina.unique())
    rotulo = subcelulas.index.isin(celulas_alvo)
    positivos_elegiveis = int(rotulo.sum())
    positivos_total = len(celulas_alvo)
    limite_recall = positivos_elegiveis / positivos_total
    ap = average_precision_score(rotulo, score_fino) * limite_recall
    prevalencia = rotulo.mean()
    return dict(
        origem=str(origem.date()), modelo=modelo, lado_m=lado,
        celulas_avaliadas=len(rotulo), celulas_positivas=positivos_total,
        celulas_positivas_avaliadas=positivos_elegiveis, alertas=len(alvo),
        area_elegivel_km2=len(rotulo) * (grade_fina.lado_m / 1000) ** 2,
        precisao_media=ap, referencia_sem_ranking=prevalencia * limite_recall,
    )


def executar_escala(dados, origens, avaliadas, lado):
    dados['celula'] = M['GradeQuadrada'](lado).celula_dos_centroides(dados).to_numpy()
    periodos = {t: preparar_origem(dados, t, lado) for t in origens}
    originais = {t: M['atributos_historicos'](dados, t) for t in origens} if lado == 2500 else {}
    linhas = []
    for t in avaliadas:
        anteriores = [o for o in origens if o + M['HORIZONTE'] <= M['corte'](t)]
        frame, alvo, _ = periodos[t]
        treino = pd.concat([periodos[o][0] for o in anteriores], ignore_index=True)
        y = np.concatenate([periodos[o][2] for o in anteriores])
        scores = {
            f'proximidade_{lado}': -np.round(frame.distancia_recente.to_numpy()),
            f'densidade_{lado}': frame.densidade_3000m_180d.to_numpy(),
        }
        with M['threadpool_limits'](limits=2):
            extra = ExtraTreesClassifier(**EXTRA).fit(treino, y > 0)
            scores[f'extra_trees_{lado}'] = extra.predict_proba(frame)[:, 1]
            poisson = HistGradientBoostingRegressor(**POISSON).fit(treino, y)
            scores[f'poisson_{lado}'] = poisson.predict(frame)
            if originais:
                for o in (*anteriores, t):
                    pd.testing.assert_index_equal(originais[o].index, periodos[o][0].index,
                                                  check_names=False)
                colunas = M['ATRIBUTOS']
                base = pd.concat([originais[o][colunas] for o in anteriores], ignore_index=True)
                ref = ExtraTreesClassifier(**EXTRA).fit(base, y > 0)
                scores[REFERENCIA] = ref.predict_proba(originais[t][colunas])[:, 1]
        for nome, score in scores.items():
            linhas.append(avaliar(frame, alvo, score, t, nome, lado))
        print(f'{lado} m | {t.date()} | {len(treino):,} exemplos', flush=True)
    return linhas


def main():
    protocolo = json.loads((RAIZ / 'protocolo/protocolo_avaliacao_final.json').read_text())
    entrada = RAIZ / protocolo['dados']['arquivo']
    with entrada.open('rb') as arquivo:
        sha = hashlib.file_digest(arquivo, 'sha256').hexdigest()
    if sha != protocolo['dados']['sha256']:
        raise ValueError('SHA-256 diverge da base congelada')
    dados = M['carregar_preparado'](entrada)
    dados = dados[dados.view_date <= M['DEV'][1]].copy()
    dados['celula_fina'] = M['GradeQuadrada'](ESCALAS[0]).celula_dos_centroides(dados).to_numpy()
    origens = pd.date_range('2021-01-01', '2025-04-01', freq='QS')
    selecao = origens[origens.year == 2023].tolist()
    avaliadas = M['origens_dev']()
    linhas = []
    for lado in ESCALAS:
        linhas.extend(executar_escala(dados, origens, selecao + avaliadas, lado))
    por_origem = pd.DataFrame(linhas)
    por_origem['etapa'] = np.where(por_origem.origem.str.startswith('2023'), 'selecao', 'comparacao')
    comparabilidade = ['area_elegivel_km2', 'celulas_avaliadas', 'celulas_positivas',
                        'celulas_positivas_avaliadas', 'alertas']
    assert por_origem.groupby('origem')[comparabilidade].nunique().eq(1).all().all()
    chaves = ['etapa', 'modelo', 'lado_m']
    classificacao = (por_origem.groupby(chaves, as_index=False)
                     .agg(precisao_media=('precisao_media', 'mean'),
                          referencia_sem_ranking=('referencia_sem_ranking', 'mean'),
                          alertas=('alertas', 'sum'),
                          celulas_positivas=('celulas_positivas', 'sum'),
                          celulas_positivas_avaliadas=('celulas_positivas_avaliadas', 'sum')))
    ranking = (classificacao.query("etapa == 'selecao'")
               .sort_values(['precisao_media', 'modelo'], ascending=[False, True]))
    vencedor = ranking.iloc[0].modelo
    saida = RAIZ / 'results/multiescala'
    saida.mkdir(parents=True, exist_ok=True)
    por_origem.to_csv(saida / 'por_origem.csv', index=False, float_format='%.8f')
    classificacao.to_csv(saida / 'agregado.csv', index=False, float_format='%.8f')
    (saida / 'execucao.json').write_text(json.dumps(dict(
        selecionado=vencedor, referencia=REFERENCIA, dados_sha256=sha, sklearn=M['sklearn'].__version__,
        escalas_m=ESCALAS, extra_trees=EXTRA, poisson=POISSON,
        metrica='média por origem da precisão média na grade comum de 1250 m, com penalização por ausência territorial',
        alcance='desenvolvimento exploratório, sem validação independente no Pará',
    ), indent=2, ensure_ascii=False) + '\n')
    print(classificacao.pivot(index='modelo', columns='etapa', values='precisao_media')
          .mul(100).round(3).to_string())


if __name__ == '__main__':
    main()
