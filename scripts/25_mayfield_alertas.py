"""Adapta a rede densa de Mayfield et al. à previsão trimestral de alertas DETER."""
from __future__ import annotations

import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score
from torch import nn

RAIZ = Path(__file__).resolve().parents[1]
L = runpy.run_path(str(RAIZ / 'scripts/24_lstm_alertas.py'))
B, V, M = (L[chave] for chave in ('B', 'V', 'M'))
SAIDA = RAIZ / 'results/redes_temporais'


class RedeMayfield(nn.Module):
    """Usa uma camada oculta de 60 unidades, como no artigo de Mayfield."""
    def __init__(self):
        super().__init__()
        self.classificador = nn.Sequential(nn.Linear(2 * L['MESES'] + 3, 60),
                                           nn.Sigmoid(), nn.Linear(60, 1))

    def forward(self, series, espaciais):
        entradas = torch.cat((series.flatten(start_dim=1), espaciais), dim=1)
        return self.classificador(entradas).squeeze(1)


def por_historico(frame, alvo, scores, historico, origem, nome):
    positivos = pd.Index(alvo.celula.unique())
    rotulo = frame.index.isin(positivos)
    com_historico = frame.index.isin(historico)
    alvo_com_historico = positivos.isin(historico)
    linhas = []
    for grupo, seletor, alvos in (
        ('com_historico', com_historico, alvo_com_historico),
        ('sem_historico', ~com_historico, ~alvo_com_historico),
    ):
        total = int(alvos.sum())
        elegiveis = int(rotulo[seletor].sum())
        ap = (average_precision_score(rotulo[seletor], scores[seletor]) * elegiveis / total
              if elegiveis else 0)
        linhas.append(dict(origem=str(origem.date()), modelo=nome, grupo=grupo,
                           celulas_avaliadas=int(seletor.sum()), positivos=total,
                           positivos_avaliados=elegiveis, precisao_media=ap))
    return linhas


def main():
    torch.set_num_threads(2)
    cfg = json.loads((RAIZ / 'results/multiescala/lstm_execucao.json').read_text())
    protocolo = json.loads((RAIZ / 'protocolo/protocolo_avaliacao_final.json').read_text())
    entrada = Path(protocolo['dados']['arquivo'])
    if B['sha256'](entrada) != cfg['deter_sha256']:
        raise ValueError('A base DETER diverge da usada na LSTM')
    for arquivo, sha in cfg['arquivos_sha256'].items():
        if B['sha256'](Path(arquivo)) != sha:
            raise ValueError(f'Hash diferente para {arquivo}')
    dados = M['carregar_preparado'](RAIZ / entrada)
    dados = dados[dados.view_date <= M['DEV'][1]].copy()
    lado = V['ESCALAS'][0]
    grade = M['GradeQuadrada'](lado)
    dados['celula'] = grade.celula_dos_centroides(dados).to_numpy()
    dados['celula_fina'] = dados.celula
    origens = pd.date_range('2021-01-01', '2025-04-01', freq='QS')
    periodos = {t: L['preparar_origem'](dados, t, grade) for t in origens}
    todas = pd.Index(np.unique(np.concatenate([f.index.to_numpy() for f, *_ in periodos.values()])))
    estaticos = np.log1p(B['atributos_espaciais'](todas, lado, dados.crs) / 1000) / 5
    locais = {t: estaticos.loc[frame.index].to_numpy(copy=True) for t, (frame, *_) in periodos.items()}
    arquiteturas = {'lstm_kanoga': L['LSTMAlertas'], 'ann_mayfield': RedeMayfield}
    linhas, grupos = [], []
    for t in M['origens_dev']():
        anteriores = [o for o in origens if o + M['HORIZONTE'] <= M['corte'](t)]
        treino = [(periodos[o][1], locais[o], periodos[o][3]) for o in anteriores]
        frame, serie, alvo, _ = periodos[t]
        historico = M['disponiveis'](dados, t).celula.unique()
        for nome, arquitetura in arquiteturas.items():
            modelo = L['ajustar'](treino, arquitetura)
            score = L['pontuar'](modelo, serie, locais[t])
            linha = V['avaliar'](frame, alvo, score, t, nome, lado)
            linhas.append(linha)
            grupos.extend(por_historico(frame, alvo, score, historico, t, nome))
            print(t.date(), nome, f"{linha['precisao_media']:.6f}", flush=True)
    total = pd.DataFrame(linhas)
    anterior = pd.read_csv(RAIZ / 'results/multiescala/lstm_por_origem.csv').set_index('origem')
    repeticao = total.query("modelo == 'lstm_kanoga'").set_index('origem')
    pd.testing.assert_index_equal(anterior.index, repeticao.index)
    np.testing.assert_allclose(anterior.precisao_media, repeticao.precisao_media, atol=1e-7, rtol=0)
    agregado = total.groupby('modelo', as_index=False).precisao_media.mean()
    SAIDA.mkdir(parents=True, exist_ok=True)
    total.to_csv(SAIDA / 'por_origem.csv', index=False, float_format='%.8f')
    agregado.to_csv(SAIDA / 'agregado.csv', index=False, float_format='%.8f')
    pd.DataFrame(grupos).to_csv(SAIDA / 'por_historico.csv', index=False, float_format='%.8f')
    (SAIDA / 'execucao.json').write_text(json.dumps({
        'torch': torch.__version__, 'fontes_e_treino': cfg,
        'ann_mayfield': {'camada_oculta': 60, 'ativacao': 'sigmoid',
                         'doi': '10.1016/j.envsoft.2020.104741'},
        'lstm_kanoga': {'doi': '10.1109/IGARSS53475.2024.10642628'},
    }, indent=2) + '\n')
    print(agregado.to_string(index=False))


if __name__ == '__main__':
    main()
