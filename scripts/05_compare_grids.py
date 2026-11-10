"""Compara grades quadradas (5; 2,5; 1 km) e H3 (res. 6, 7, 8) sob o MESMO orçamento territorial em km².

Os quadrados de 2,5 km e 1 km são CONTROLES de resolução: têm área próxima à do H3 r7 e r8.
Sem eles, uma vantagem do H3 sobre o quadrado de 5 km poderia ser só efeito de célula menor.

Somente período de desenvolvimento (6 origens trimestrais, 2024-01 → 2025-04). O teste não é lido.
Requer as atribuições produzidas por scripts/04_hexagonal_grid.py.

Comparabilidade entre grades
----------------------------
- Região comum: o universo de cada origem é definido pelos quadrados de 5 km a até 10 km de
  algum alerta disponível (mesma regra do script 03). Para o H3, entram as células cujo CENTRO
  cai nesses quadrados. Assim, todas as grades cobrem praticamente a mesma área.
- Orçamento: fração f da ÁREA do universo (1%, 2%, 5%). Em cada grade, k = round(f·área / área
  média das células do universo). Com células de tamanhos diferentes, o número de células
  selecionadas muda, mas a área selecionada é a mesma.
- Métricas comparáveis entre grades (mesmo denominador para todas):
    recall_alertas  fração de TODOS os alertas-alvo cujo centroide cai nas células selecionadas
    recall_area     fração da área de todos os alertas-alvo que intersecta as células selecionadas
- Métricas que NÃO são comparáveis entre grades (dependem do tamanho da célula), reportadas
  só para referência: recall_celulas e precision_celulas.

Métodos (iguais para todas as grades, sem nenhum ajuste por grade)
---------------------------------------------------------------
    A      contagem de alertas na célula, 24 meses (janela congelada no script 03)
    B      área de alertas na célula (interseção), 12 meses (janela congelada no script 03)
    C_w    A + w · média de A nos vizinhos imediatos (6 no H3, 8 no quadrado)
    D_w_v  C_w + v · média, nos vizinhos, da contagem dos últimos 6 meses (atividade recente ao redor)

Seleção honesta de w e v: escolhidos nas origens 1–3 (2024-01, 04, 07), pelo maior recall_alertas
médio com orçamento de 2%, e reportados nas origens 4–6 (2024-10, 2025-01, 2025-04), que não
participaram da escolha. As médias nas 6 origens também são mostradas, para transparência.

Saídas (results/hexagonal/):
    comparacao_por_origem.csv, comparacao_resumo.csv, selecao_parametros.json,
    diferencas_pareadas.csv, estabilidade.csv, custo_computacional.csv,
    fig_recall_por_orcamento.png, fig_recall_por_origem.png

Uso:
    python scripts/05_compare_grids.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.avaliacao import (  # noqa: E402
    alvo, corte, disponiveis, ganho_esperado, jaccard, origens_dev, selecao_deterministica, universo_quadrados,
)
from geodetect.dados import DEV, carregar_preparado  # noqa: E402
from geodetect.grades import grades_padrao  # noqa: E402

FRACOES = (0.01, 0.02, 0.05)
CURVA = np.array([0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.075, 0.10])
JANELA_A, JANELA_B, JANELA_REC = 24, 12, 6
W = (0.25, 0.5, 1.0, 2.0)
V = (0.5, 1.0, 2.0, 4.0)
ORIG_AJUSTE, ORIG_AVAL = slice(0, 3), slice(3, 6)
ORC_SELECAO = "2%"


def soma_janela(df: pd.DataFrame, col_cel: str, ini: pd.Timestamp, valor: str | None = None) -> pd.Series:
    sub = df[df["view_date"] >= ini]
    return sub.groupby(col_cel).size() if valor is None else sub.groupby(col_cel)[valor].sum()


def media_vizinhos(valores: pd.Series, viz: np.ndarray) -> np.ndarray:
    """viz: matriz (n, m) de ids de vizinhos; valores ausentes contam como zero."""
    v = valores.reindex(viz.ravel()).fillna(0).to_numpy().reshape(viz.shape)
    return v.mean(1)


def metodos(cnt_a, area_b, nb_a, nb_rec) -> dict[str, np.ndarray]:
    m = {"A": cnt_a, "B": area_b}
    for w in W:
        m[f"C_{w}"] = cnt_a + w * nb_a
        for v in V:
            m[f"D_{w}_{v}"] = cnt_a + w * nb_a + v * nb_rec
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/hexagonal", type=Path)
    ap.add_argument("--processados", default="data/processed", type=Path)
    args = ap.parse_args()

    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]][["chave", "view_date", "cel_i", "cel_j", "area_km2"]].copy()
    origens = origens_dev()
    nomes_orig = [t.date().isoformat() for t in origens]

    # universo máximo (cresce com o tempo): usado só para pré-computar o mapeamento célula→quadrado
    disp_ult = disponiveis(g, origens[-1])
    quad_max = universo_quadrados(disp_ult["cel_i"].to_numpy(), disp_ult["cel_j"].to_numpy())

    linhas, estab, custo = [], [], []
    for grade in grades_padrao():
        tracemalloc.start()
        t0 = time.perf_counter()
        cent = pd.read_csv(args.processados / f"centroide_{grade.nome}.csv.gz")
        inter = pd.read_csv(args.processados / f"atribuicao_{grade.nome}.csv.gz")
        ge = g.merge(cent, on="chave")
        gi = g[["chave", "view_date"]].merge(inter, on="chave")

        mapa = grade.celulas_por_quadrado(quad_max)  # índice: célula, valor: quadrado
        cel_all = mapa.index.to_numpy()
        area_all = grade.area_km2(cel_all).to_numpy()
        viz = grade.vizinhos(cel_all)
        viz_mat = np.array([viz[c] for c in cel_all], dtype=object)
        t_prep = time.perf_counter() - t0

        selecoes_prev: dict[str, np.ndarray] = {}
        for t, nome_t in zip(origens, nomes_orig):
            c = corte(t)
            disp_e = disponiveis(ge, t)
            disp_i = disponiveis(gi, t)
            tgt_e, tgt_i = alvo(ge, t), alvo(gi, t)

            u_quad = set(universo_quadrados(disponiveis(g, t)["cel_i"].to_numpy(), disponiveis(g, t)["cel_j"].to_numpy()))
            no_u = mapa.isin(u_quad).to_numpy()
            cel, area, vz = cel_all[no_u], area_all[no_u], viz_mat[no_u]
            area_universo = 25.0 * len(u_quad)

            a24 = soma_janela(disp_e, "celula", c - pd.DateOffset(months=JANELA_A))
            b12 = soma_janela(disp_i, "celula", c - pd.DateOffset(months=JANELA_B), "area_km2")
            r6 = soma_janela(disp_e, "celula", c - pd.DateOffset(months=JANELA_REC))
            cnt_a = a24.reindex(cel).fillna(0).to_numpy(float)
            area_b = b12.reindex(cel).fillna(0).to_numpy(float)
            nb_a = media_vizinhos(a24, vz)
            nb_rec = media_vizinhos(r6, vz)

            y_alert = tgt_e.groupby("celula").size().reindex(cel).fillna(0).to_numpy(float)
            y_area = tgt_i.groupby("celula")["area_km2"].sum().reindex(cel).fillna(0).to_numpy(float)
            y_cel = (y_alert > 0).astype(float)
            tot_alert, tot_area = float(len(tgt_e)), float(tgt_i["area_km2"].sum())

            ms = metodos(cnt_a, area_b, nb_a, nb_rec)
            a_media = float(area.mean())
            for f in sorted(set(FRACOES) | set(CURVA)):
                k = max(1, int(round(f * area_universo / a_media)))
                for nome_m, s in ms.items():
                    if f not in FRACOES and nome_m not in ("A", "B") and not nome_m.startswith("C_"):
                        continue
                    h_cel = ganho_esperado(s, y_cel, k)
                    linhas.append({
                        "grade": grade.nome, "origem": nome_t, "metodo": nome_m,
                        "orcamento": f"{f*100:g}%", "fracao": f, "k": k,
                        "area_selecionada_km2": k * a_media, "area_universo_km2": area_universo,
                        "recall_alertas": ganho_esperado(s, y_alert, k) / tot_alert if tot_alert else np.nan,
                        "recall_area": ganho_esperado(s, y_area, k) / tot_area if tot_area else np.nan,
                        "recall_celulas": h_cel / y_cel.sum() if y_cel.sum() else np.nan,
                        "precision_celulas": h_cel / k,
                        "alertas_alvo": tot_alert, "celulas_universo": len(cel),
                    })
                    if f == 0.02 and (nome_m in ("A", "B") or nome_m.startswith("C_")):
                        sel = cel[selecao_deterministica(s, k)]
                        chave_e = (nome_m,)
                        if chave_e in selecoes_prev:
                            estab.append({"grade": grade.nome, "metodo": nome_m, "origem": nome_t,
                                          "jaccard_com_origem_anterior": jaccard(sel, selecoes_prev[chave_e])})
                        selecoes_prev[chave_e] = sel
        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        custo.append({"grade": grade.nome, "celulas_regiao_max": len(cel_all),
                      "tempo_preparo_s": round(t_prep, 2), "tempo_total_s": round(time.perf_counter() - t0, 2),
                      "pico_memoria_mb": round(pico / 2**20, 1)})
        print(f"{grade.nome}: {len(cel_all)} células na região, {custo[-1]['tempo_total_s']} s")

    met = pd.DataFrame(linhas)
    met.to_csv(args.saida / "comparacao_por_origem.csv", index=False, float_format="%.5f")
    pd.DataFrame(custo).to_csv(args.saida / "custo_computacional.csv", index=False)

    # ---- escolha de w e v nas origens de ajuste ---------------------------------
    def media(d, origs):
        return d[d["origem"].isin(origs)]["recall_alertas"].mean()

    aj, av = nomes_orig[ORIG_AJUSTE], nomes_orig[ORIG_AVAL]
    sel = {}
    m2 = met[met["orcamento"] == ORC_SELECAO]
    for grade, d in m2.groupby("grade"):
        for fam in ("C", "D"):
            cand = d[d["metodo"].str.startswith(fam + "_")]
            r = cand.groupby("metodo").apply(lambda x: media(x, aj), include_groups=False).sort_values(ascending=False)
            sel[(grade, fam)] = r.index[0]
    selecao = {f"{gr}|{fam}": m for (gr, fam), m in sel.items()}
    (args.saida / "selecao_parametros.json").write_text(json.dumps({
        "criterio": f"maior recall_alertas médio, orçamento {ORC_SELECAO}, origens de ajuste {aj}",
        "origens_avaliacao": av, "escolhas": selecao}, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- resumo ----------------------------------------------------------------
    def rotulo(row):
        if row["metodo"] in ("A", "B"):
            return row["metodo"]
        fam = row["metodo"][0]
        return f"{fam}*" if sel.get((row["grade"], fam)) == row["metodo"] else None

    met["modelo"] = met.apply(rotulo, axis=1)
    princ = met[met["modelo"].notna() & met["fracao"].isin(FRACOES)]
    resumo = []
    for (grade, modelo, orc), d in princ.groupby(["grade", "modelo", "orcamento"]):
        resumo.append({
            "grade": grade, "modelo": modelo, "metodo": d["metodo"].iloc[0], "orcamento": orc,
            "k_medio": round(d["k"].mean(), 1),
            "recall_alertas_6orig": d["recall_alertas"].mean(),
            "recall_alertas_ajuste": media(d, aj), "recall_alertas_avaliacao": media(d, av),
            "recall_area_6orig": d["recall_area"].mean(),
            "recall_celulas_6orig": d["recall_celulas"].mean(),
            "precision_celulas_6orig": d["precision_celulas"].mean(),
        })
    resumo = pd.DataFrame(resumo).sort_values(["orcamento", "modelo", "grade"])
    resumo.to_csv(args.saida / "comparacao_resumo.csv", index=False, float_format="%.4f")

    # diferenças pareadas por origem em relação ao quadrado, mesmo modelo, orçamento 2%
    p = princ[princ["orcamento"] == ORC_SELECAO].pivot_table(
        index=["modelo", "origem"], columns="grade", values="recall_alertas")
    pares = {"h3_r6-quadrado_5km": ("h3_r6", "quadrado_5km"), "h3_r7-quadrado_5km": ("h3_r7", "quadrado_5km"),
             "h3_r7-quadrado_2.5km": ("h3_r7", "quadrado_2.5km"), "h3_r8-quadrado_1km": ("h3_r8", "quadrado_1km"),
             "quadrado_2.5km-quadrado_5km": ("quadrado_2.5km", "quadrado_5km")}
    dif = pd.DataFrame({n: p[a] - p[b] for n, (a, b) in pares.items()}).reset_index()
    dif.to_csv(args.saida / "diferencas_pareadas.csv", index=False, float_format="%.4f")

    est = pd.DataFrame(estab)
    est.to_csv(args.saida / "estabilidade.csv", index=False, float_format="%.4f")

    # ---- figuras ---------------------------------------------------------------
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    cores = {"quadrado_5km": "#333333", "h3_r6": "#2a6f97", "h3_r7": "#e07a1f", "quadrado_2.5km": "#f2b880",
             "h3_r8": "#6a994e", "quadrado_1km": "#b5d99c"}
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, fam in zip(axs, ("A", "C")):
        for grade, cor in cores.items():
            mname = "A" if fam == "A" else sel[(grade, "C")]
            d = met[(met["grade"] == grade) & (met["metodo"] == mname)].groupby("fracao")["recall_alertas"].mean()
            ax.plot(100 * d.index, d.values, marker="o", ms=3, color=cor, label=f"{grade} ({mname})")
        ax.set_xlabel("orçamento (% da área do universo)")
        ax.set_title("A — contagem própria (24 meses)" if fam == "A" else "C* — própria + vizinhos (w escolhido nas origens 1–3)")
        ax.legend(frameon=False, fontsize=8)
    axs[0].set_ylabel("recall de alertas futuros (média de 6 origens)")
    fig.suptitle("Mesmo orçamento em km²: fração dos alertas do trimestre seguinte capturada", fontsize=11)
    fig.tight_layout(); fig.savefig(args.saida / "fig_recall_por_orcamento.png", dpi=160); plt.close(fig)

    fig, axs = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True, sharey=True)
    for ax, modelo in zip(axs, ("A", "C*")):
        d = princ[(princ["orcamento"] == ORC_SELECAO) & (princ["modelo"] == modelo)]
        piv = d.pivot_table(index="origem", columns="grade", values="recall_alertas")[list(cores)]
        piv.plot.bar(ax=ax, width=0.85, color=list(cores.values()), legend=False)
        ax.axvline(2.5, color="#999", lw=0.8, ls="--")
        ax.text(1, 0.93, "ajuste de w", ha="center", transform=ax.get_xaxis_transform(), fontsize=8)
        ax.text(4, 0.93, "avaliação", ha="center", transform=ax.get_xaxis_transform(), fontsize=8)
        ax.set_ylabel(f"recall @ {ORC_SELECAO}")
        ax.set_title("A — contagem própria" if modelo == "A" else "C* — própria + vizinhos", fontsize=10)
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=8, ncol=6, loc="lower center")
    axs[1].set_xlabel("origem")
    plt.setp(axs[1].get_xticklabels(), rotation=0)
    fig.suptitle(f"Recall de alertas futuros por origem — orçamento de {ORC_SELECAO} da área", fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(args.saida / "fig_recall_por_origem.png", dpi=160); plt.close(fig)

    pd.set_option("display.width", 200)
    print(resumo.round(3).to_string(index=False))
    print(json.dumps(selecao, indent=1))
    print(dif.round(3).to_string(index=False))
    print(est.groupby(["grade", "metodo"])["jaccard_com_origem_anterior"].mean().unstack().round(3).iloc[:, :4])
    print(pd.DataFrame(custo).to_string(index=False))


if __name__ == "__main__":
    main()
