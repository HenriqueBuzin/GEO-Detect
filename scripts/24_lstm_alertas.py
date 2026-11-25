"""Adapta uma LSTM de duas camadas à previsão trimestral de alertas de mineração."""
from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.spatial import cKDTree
from torch import nn

RAIZ = Path(__file__).resolve().parents[1]
B = runpy.run_path(str(RAIZ / 'scripts/23_bases_preditores.py'))
V = B['V']
M = V['M']
SAIDA = B['SAIDA']
MESES = 24
SEMENTE = 2027
NEGATIVOS_POR_POSITIVO = 10
EPOCAS = 12
LOTE = 256


class LSTMAlertas(nn.Module):
    def __init__(self):
        super().__init__()
        self.recorrente = nn.LSTM(input_size=2, hidden_size=16, num_layers=2, batch_first=True)
        self.saida = nn.Sequential(nn.Linear(19, 16), nn.ReLU(), nn.Dropout(.25),
                                   nn.Linear(16, 8), nn.ReLU(), nn.Dropout(.25), nn.Linear(8, 1))

    def forward(self, series, espaciais):
        sequencia, _ = self.recorrente(series)
        representacao = torch.cat((sequencia[:, -1], espaciais), dim=1)
        return self.saida(representacao).squeeze(1)


def preparar_origem(dados, origem, grade):
    limite = M['corte'](origem)
    disp = M['disponiveis'](dados, origem)
    quadrados = M['universo_quadrados'](disp.cel_i.to_numpy(), disp.cel_j.to_numpy())
    indice = grade.celulas_por_quadrado(quadrados).index
    frame = pd.DataFrame(index=indice)
    xyz = (grade._ij(indice) + .5) * grade.lado_m
    recente = disp[disp.view_date >= limite - pd.DateOffset(months=MESES)]
    meses_eventos = (recente.view_date.dt.to_period('M').astype('int64')
                     - (limite.to_period('M').ordinal - MESES)).to_numpy()
    assert ((meses_eventos >= 0) & (meses_eventos < MESES)).all()
    celulas_eventos = indice.get_indexer(recente.celula)
    assert (celulas_eventos >= 0).all()
    proprio = np.bincount(celulas_eventos * MESES + meses_eventos,
                          minlength=len(indice) * MESES)
    pares = cKDTree(xyz).sparse_distance_matrix(
        cKDTree(recente[['cx', 'cy']].to_numpy()), 12000, output_type='coo_matrix'
    )
    pesos = np.exp(-.5 * (pares.data / 3000) ** 2)
    vizinhos = np.bincount(pares.row * MESES + meses_eventos[pares.col],
                           weights=pesos, minlength=len(indice) * MESES)
    series = np.log1p(np.stack((proprio, vizinhos), axis=1)).astype('float32')
    alvo = M['alvo'](dados, origem)
    rotulo = indice.isin(alvo.celula)
    return frame, series.reshape(len(indice), MESES, 2), alvo, rotulo


def amostra(rotulos, rng):
    positivos = np.flatnonzero(rotulos)
    negativos = np.flatnonzero(~rotulos)
    n = min(len(negativos), NEGATIVOS_POR_POSITIVO * len(positivos))
    return np.concatenate((positivos, rng.choice(negativos, n, replace=False)))


def ajustar(treino, arquitetura=LSTMAlertas):
    torch.manual_seed(SEMENTE)
    rng = np.random.default_rng(SEMENTE)
    blocos = []
    for series, espacial, rotulo in treino:
        selecao = amostra(rotulo, rng)
        blocos.append((series[selecao], espacial[selecao], rotulo[selecao]))
    series, espacial, rotulos = [torch.as_tensor(np.concatenate(coluna), dtype=torch.float32)
                                 for coluna in zip(*blocos)]
    modelo = arquitetura()
    otimizador = torch.optim.Adam(modelo.parameters(), lr=.002)
    perda = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(float(NEGATIVOS_POR_POSITIVO)))
    for _ in range(EPOCAS):
        for ids in torch.randperm(len(rotulos)).split(LOTE):
            otimizador.zero_grad()
            erro = perda(modelo(series[ids], espacial[ids]), rotulos[ids])
            erro.backward()
            otimizador.step()
    return modelo


def pontuar(modelo, entrada_temporal, atributos_estaticos):
    modelo.eval()
    with torch.inference_mode():
        series = torch.from_numpy(entrada_temporal)
        espaciais = torch.from_numpy(atributos_estaticos)
        return np.concatenate([
            modelo(a, b).numpy() for a, b in zip(series.split(1024), espaciais.split(1024))
        ])



def main():
    torch.set_num_threads(2)
    protocolo = json.loads((RAIZ / 'protocolo/protocolo_avaliacao_final.json').read_text())
    entrada = Path(protocolo['dados']['arquivo'])
    with (RAIZ / entrada).open('rb') as arquivo:
        sha = hashlib.file_digest(arquivo, 'sha256').hexdigest()
    if sha != protocolo['dados']['sha256']:
        raise ValueError('SHA-256 diverge da base congelada DETER')
    lado = V['ESCALAS'][0]
    grade = M['GradeQuadrada'](lado)
    dados = M['carregar_preparado'](RAIZ / entrada)
    dados = dados[dados.view_date <= M['DEV'][1]].copy()
    dados['celula'] = grade.celula_dos_centroides(dados).to_numpy()
    dados['celula_fina'] = dados.celula
    origens = pd.date_range('2021-01-01', '2025-04-01', freq='QS')
    periodos = {t: preparar_origem(dados, t, grade) for t in origens}
    celulas = pd.Index(pd.concat([f.index.to_series() for f, *_ in periodos.values()])
                       .drop_duplicates().to_numpy())
    estaticos = np.log1p(B['atributos_espaciais'](celulas, lado, dados.crs) / 1000) / 5
    locais = {t: estaticos.loc[frame.index].to_numpy(copy=True) for t, (frame, *_) in periodos.items()}
    print(f'{len(celulas):,} células com séries e atributos espaciais', flush=True)

    linhas = []
    for t in M['origens_dev']():
        anteriores = [o for o in origens if o + M['HORIZONTE'] <= M['corte'](t)]
        modelo = ajustar([(periodos[o][1], locais[o], periodos[o][3]) for o in anteriores])
        frame, entrada_temporal, alvo, _ = periodos[t]
        scores = pontuar(modelo, entrada_temporal, locais[t])
        linhas.append(V['avaliar'](frame, alvo, scores, t, 'lstm_adaptada', lado))
        print(t.date(), f'{linhas[-1]["precisao_media"]:.6f}', flush=True)

    resultado = pd.DataFrame(linhas)
    anterior = pd.read_csv(SAIDA / 'por_origem.csv').query(
        "modelo == 'extra_trees_1250' and etapa == 'comparacao'"
    )
    colunas = ['alertas', 'celulas_positivas', 'celulas_positivas_avaliadas', 'celulas_avaliadas']
    pd.testing.assert_frame_equal(resultado.set_index('origem')[colunas],
                                  anterior.set_index('origem')[colunas])
    total = resultado.groupby('modelo', as_index=False).agg(
        precisao_media=('precisao_media', 'mean'), alertas=('alertas', 'sum'),
        celulas_positivas=('celulas_positivas', 'sum'),
    )
    resultado.to_csv(SAIDA / 'lstm_por_origem.csv', index=False, float_format='%.8f')
    total.to_csv(SAIDA / 'lstm_agregado.csv', index=False, float_format='%.8f')
    (SAIDA / 'lstm_execucao.json').write_text(json.dumps(dict(
        deter_sha256=sha, arquivos_sha256={str(p): B['sha256'](p) for p in (
            B['HIDRO'], *(B['IBGE'].with_suffix(ext) for ext in ('.shp', '.shx', '.prj', '.dbf'))
        )}, torch=torch.__version__, semente=SEMENTE, meses=MESES, epocas=EPOCAS,
        negativos_por_positivo=NEGATIVOS_POR_POSITIVO, lote=LOTE, lr=.002,
    ), indent=2) + '\n')
    print(total.to_string(index=False))


if __name__ == '__main__':
    main()
