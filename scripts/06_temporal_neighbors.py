"""Estatísticas descritivas de vizinhança temporal: alertas "aparecem" ao lado de alertas recentes?

Somente dados até o fim do desenvolvimento (2025-06-30). Trimestres de 2016-T3 a 2025-T2.

Para cada transição de trimestre q → q+1 e cada célula da região de estudo, classifica a célula em q:
    ativa                   teve alerta em q
    vizinha_ativa_com_hist  sem alerta em q, algum vizinho imediato com alerta em q, já teve alerta antes
    vizinha_ativa_sem_hist  sem alerta em q, algum vizinho com alerta em q, NUNCA teve alerta
    isolada_com_hist        sem alerta em q, nenhum vizinho com alerta em q, já teve alerta antes
    isolada_sem_hist        sem alerta em q, nenhum vizinho com alerta em q, nunca teve alerta
e mede a probabilidade de a célula ter alerta em q+1 (agregando todas as transições).

Também mede, entre as células que recebem o PRIMEIRO alerta da sua história em q+1, a fração que
tinha vizinho ativo em q, comparada com a fração de células nunca alertadas que tinham vizinho ativo
(exposição de base). A razão entre as duas é o "enriquecimento" de vizinhança das novas detecções.

Cuidado: isto descreve padrões de DETECÇÃO. Não demonstra deslocamento físico da mineração,
causalidade ou vínculo entre atividades. A região de estudo usa o histórico até 2025-03 (descritivo).

Saídas (results/hexagonal/):
    vizinhanca_temporal.csv, novas_ativacoes.csv, fig_vizinhanca_temporal.png

Uso:
    python scripts/06_temporal_neighbors.py   (requer scripts/04_hexagonal_grid.py)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.avaliacao import disponiveis, origens_dev, universo_quadrados  # noqa: E402
from geodetect.dados import DEV, carregar_preparado  # noqa: E402
from geodetect.grades import GradeH3, GradeQuadrada  # noqa: E402

CATEGORIAS = ["ativa", "vizinha_ativa_com_hist", "vizinha_ativa_sem_hist", "isolada_com_hist", "isolada_sem_hist"]


def matriz_vizinhos(grade, celulas: np.ndarray) -> np.ndarray:
    pos = {c: i for i, c in enumerate(celulas)}
    viz = grade.vizinhos(celulas)
    m = max(len(v) for v in viz.values())
    out = np.full((len(celulas), m), -1, dtype=np.int64)
    for i, c in enumerate(celulas):
        idx = [pos.get(v, -1) for v in viz[c]]
        out[i, : len(idx)] = idx
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/hexagonal", type=Path)
    ap.add_argument("--processados", default="data/processed", type=Path)
    args = ap.parse_args()

    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]][["chave", "view_date", "cel_i", "cel_j"]].copy()
    g["tri"] = g["view_date"].dt.to_period("Q")
    trimestres = pd.period_range(g["tri"].min(), pd.Period(DEV[1], "Q"), freq="Q")
    disp = disponiveis(g, origens_dev()[-1])
    regiao = universo_quadrados(disp["cel_i"].to_numpy(), disp["cel_j"].to_numpy())

    linhas, ativ = [], []
    for grade in (GradeQuadrada(), GradeQuadrada(2500), GradeH3(7), GradeQuadrada(1000), GradeH3(8)):
        cent = pd.read_csv(args.processados / f"centroide_{grade.nome}.csv.gz")
        ge = g.merge(cent, on="chave")
        celulas = grade.celulas_por_quadrado(regiao).index.to_numpy()
        pos = pd.Series(np.arange(len(celulas)), index=celulas)
        viz = matriz_vizinhos(grade, celulas)

        ativo = np.zeros((len(trimestres), len(celulas)), dtype=bool)
        ti = pd.Series(np.arange(len(trimestres)), index=trimestres)
        ge = ge[ge["celula"].isin(pos.index)]
        ativo[ti[ge["tri"]].to_numpy(), pos[ge["celula"]].to_numpy()] = True
        hist = np.cumsum(ativo, axis=0) > 0  # já teve alerta até o fim do trimestre q

        cont = {c: [0, 0] for c in CATEGORIAS}  # [n_células·transições, n com alerta em q+1]
        novas = {"novas_total": 0, "novas_com_vizinho_ativo": 0, "nunca_total": 0, "nunca_com_vizinho_ativo": 0}
        pad = np.zeros((len(trimestres), 1), dtype=bool)
        ativo_p = np.concatenate([ativo, pad], axis=1)  # índice -1 → coluna falsa
        for q in range(len(trimestres) - 1):
            a, prox = ativo[q], ativo[q + 1]
            nb = ativo_p[q][viz].any(axis=1)
            h = hist[q]
            cat = np.select(
                [a, ~a & nb & h, ~a & nb & ~h, ~a & ~nb & h],
                CATEGORIAS[:4], default=CATEGORIAS[4])
            for c in CATEGORIAS:
                m = cat == c
                cont[c][0] += int(m.sum()); cont[c][1] += int(prox[m].sum())
            nunca = ~h
            nova = nunca & prox
            novas["novas_total"] += int(nova.sum()); novas["novas_com_vizinho_ativo"] += int((nova & nb).sum())
            novas["nunca_total"] += int(nunca.sum()); novas["nunca_com_vizinho_ativo"] += int((nunca & nb).sum())

        base = sum(v[1] for v in cont.values()) / sum(v[0] for v in cont.values())
        for c, (n, k) in cont.items():
            p = k / n if n else np.nan
            linhas.append({"grade": grade.nome, "categoria": c, "celula_trimestres": n, "com_alerta_no_seguinte": k,
                           "prob_alerta_seguinte": p, "lift_vs_base": p / base if base else np.nan,
                           "taxa_base": base})
        f_nova = novas["novas_com_vizinho_ativo"] / novas["novas_total"]
        f_base = novas["nunca_com_vizinho_ativo"] / novas["nunca_total"]
        ativ.append({"grade": grade.nome, **novas,
                     "frac_novas_com_vizinho_ativo": f_nova, "frac_exposicao_base": f_base,
                     "enriquecimento": f_nova / f_base})
        print(f"{grade.nome}: taxa base {base:.4f}; novas com vizinho ativo {f_nova:.3f} vs base {f_base:.4f}")

    viz_t = pd.DataFrame(linhas)
    viz_t.to_csv(args.saida / "vizinhanca_temporal.csv", index=False, float_format="%.5f")
    nov = pd.DataFrame(ativ)
    nov.to_csv(args.saida / "novas_ativacoes.csv", index=False, float_format="%.5f")

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(10, 4.2))
    piv = viz_t.pivot(index="categoria", columns="grade", values="prob_alerta_seguinte").loc[CATEGORIAS]
    piv = piv[["quadrado_5km", "quadrado_2.5km", "h3_r7", "quadrado_1km", "h3_r8"]]
    piv.plot.bar(ax=ax, logy=True, width=0.8,
                 color=["#333333", "#f2b880", "#e07a1f", "#b5d99c", "#6a994e"])
    ax.set_ylabel("P(alerta no trimestre seguinte) — log")
    ax.set_xlabel("")
    ax.set_xticklabels(["ativa em q", "vizinho ativo,\njá teve alerta", "vizinho ativo,\nnunca teve",
                        "sem vizinho ativo,\njá teve", "sem vizinho ativo,\nnunca teve"], rotation=0, fontsize=8)
    ax.set_title("Detecções no trimestre seguinte por situação da célula e dos vizinhos (2016-T3 → 2025-T2)")
    ax.legend(frameon=False, fontsize=8, ncol=5)
    fig.tight_layout(); fig.savefig(args.saida / "fig_vizinhanca_temporal.png", dpi=160); plt.close(fig)

    pd.set_option("display.width", 200)
    print(viz_t.pivot(index="categoria", columns="grade", values="lift_vs_base").loc[CATEGORIAS].round(2))
    print(nov.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
