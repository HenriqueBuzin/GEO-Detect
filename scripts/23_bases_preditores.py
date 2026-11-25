"""Incorpora hidrografia e localidades históricas à comparação com a literatura."""
from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

RAIZ = Path(__file__).resolve().parents[1]
V = runpy.run_path(str(RAIZ / 'scripts/21_previsao_multiescala.py'))
M = V['M']
SAIDA = RAIZ / 'results/multiescala'
HIDRO = Path('data/raw/hydrorivers_v10_sa.zip')
IBGE = Path('data/raw/ibge_localidades_2010/BR_Localidades_2010_v1.shp')
URL_HIDRO = 'https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_sa_shp.zip'
URL_IBGE = ('https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/'
            'localidades/cadastro_de_localidades_selecionadas_2010/Shapefile_SHP/')


def distancia_linhas(pontos, linhas):
    indices, distancias = shapely.STRtree(linhas).query_nearest(
        pontos, all_matches=False, return_distance=True
    )
    resposta = np.full(len(pontos), np.nan)
    resposta[indices[0]] = distancias
    if not np.isfinite(resposta).all():
        raise ValueError('Distância à hidrografia indisponível para alguma célula')
    return resposta


def atributos_espaciais(celulas, lado, crs):
    grade = M['GradeQuadrada'](lado)
    xy = (grade._ij(celulas) + .5) * lado
    pontos = shapely.points(xy)
    rios = gpd.read_file(
        f'zip://{RAIZ / HIDRO}!HydroRIVERS_v10_sa_shp/HydroRIVERS_v10_sa.shp',
        bbox=(-76, -19, -40, 8), columns=['ORD_STRA'],
    ).to_crs(crs)
    localidades = gpd.read_file(RAIZ / IBGE, columns=[]).to_crs(crs)
    centros = np.column_stack((localidades.geometry.x, localidades.geometry.y))
    distancias = {
        'distancia_rio': distancia_linhas(pontos, rios.geometry.to_numpy()),
        'distancia_rio_ordem5': distancia_linhas(pontos, rios.loc[rios.ORD_STRA >= 5, 'geometry'].to_numpy()),
        'distancia_localidade': cKDTree(centros).query(xy)[0],
    }
    return pd.DataFrame(distancias, index=celulas, dtype='float32')


def sha256(arquivo):
    with (RAIZ / arquivo).open('rb') as entrada:
        return hashlib.file_digest(entrada, 'sha256').hexdigest()


def main():
    protocolo = json.loads((RAIZ / 'protocolo/protocolo_avaliacao_final.json').read_text())
    entrada = Path(protocolo['dados']['arquivo'])
    sha = sha256(entrada)
    if sha != protocolo['dados']['sha256']:
        raise ValueError('SHA-256 diverge da base congelada DETER')
    arquivos = [HIDRO, *(IBGE.with_suffix(ext) for ext in ('.shp', '.shx', '.prj', '.dbf'))]
    metadados = {str(arquivo): sha256(arquivo) for arquivo in arquivos}

    dados = M['carregar_preparado'](RAIZ / entrada)
    dados = dados[dados.view_date <= M['DEV'][1]].copy()
    lado = V['ESCALAS'][0]
    dados['celula'] = M['GradeQuadrada'](lado).celula_dos_centroides(dados).to_numpy()
    dados['celula_fina'] = dados['celula']
    origens = pd.date_range('2021-01-01', '2025-04-01', freq='QS')
    periodos = {t: V['preparar_origem'](dados, t, lado) for t in origens}
    celulas = pd.Index(pd.concat([f.index.to_series() for f, _, _ in periodos.values()])
                       .drop_duplicates().to_numpy())
    espaciais = atributos_espaciais(celulas, lado, dados.crs)
    frames = {t: frame.join(espaciais, how='left', validate='one_to_one')
              for t, (frame, _, _) in periodos.items()}
    print(f'{len(celulas):,} células com atributos espaciais', flush=True)

    linhas = []
    for t in M['origens_dev']():
        anteriores = [o for o in origens if o + M['HORIZONTE'] <= M['corte'](t)]
        x = pd.concat([frames[o] for o in anteriores], ignore_index=True)
        y = np.concatenate([periodos[o][2] for o in anteriores]) > 0
        modelos = {
            'geo_detect': V['ExtraTreesClassifier'](**V['EXTRA']),
            'random_forest_adaptada': M['RandomForestClassifier'](**M['PARAMETROS_RF']),
        }
        with M['threadpool_limits'](limits=2):
            for nome, modelo in modelos.items():
                score = modelo.fit(x, y).predict_proba(frames[t])[:, 1]
                linhas.append(V['avaliar'](frames[t], periodos[t][1], score, t, nome, lado))
                print(t.date(), nome, f'{linhas[-1]["precisao_media"]:.6f}', flush=True)

    resultado = pd.DataFrame(linhas)
    original = pd.read_csv(SAIDA / 'por_origem.csv').query(
        "modelo == 'extra_trees_1250' and etapa == 'comparacao'"
    )
    colunas = ['alertas', 'celulas_positivas', 'celulas_positivas_avaliadas', 'celulas_avaliadas']
    esperado = original.set_index('origem')[colunas].sort_index()
    for _, grupo in resultado.groupby('modelo'):
        pd.testing.assert_frame_equal(grupo.set_index('origem')[colunas].sort_index(), esperado)
    total = resultado.groupby('modelo', as_index=False).agg(
        precisao_media=('precisao_media', 'mean'), alertas=('alertas', 'sum'),
        celulas_positivas=('celulas_positivas', 'sum'),
    )
    resultado.to_csv(SAIDA / 'bases_por_origem.csv', index=False, float_format='%.8f')
    total.to_csv(SAIDA / 'bases_agregado.csv', index=False, float_format='%.8f')
    (SAIDA / 'dados_auxiliares.json').write_text(json.dumps(dict(
        deter_sha256=sha, arquivos_sha256=metadados, hydro_url=URL_HIDRO, ibge_url=URL_IBGE,
        extra_trees=V['EXTRA'], random_forest=M['PARAMETROS_RF'],
        sklearn=M['sklearn'].__version__,
    ), ensure_ascii=False, indent=2) + '\n')
    print(total.to_string(index=False))


if __name__ == '__main__':
    main()
