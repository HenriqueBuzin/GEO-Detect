"""Curva de resolução H3 (r6 → r10) — EXPLORATÓRIA, somente período de desenvolvimento.

O teste independente de 2026 já foi usado na avaliação final pré-registrada e NÃO é lido aqui.
Este script responde a uma pergunta descritiva: até onde vale a pena refinar a célula?

Mesmo protocolo do script 05 (origens, gap, universo, orçamento em km², empates pela
expectativa, w escolhido nas origens 1–3), com cálculo ESPARSO para caber em r9/r10:
    - só células com alerta disponível e seus vizinhos imediatos podem ter pontuação > 0;
    - as demais células do universo têm pontuação 0 e empatam entre si;
    - o tamanho do universo vem da contagem de células H3 com centro em cada quadrado de 5 km,
      e a área média, de contagem × área da célula central de cada quadrado.
A versão esparsa é validada contra o script 05 em r6–r8 (ver validacao_vs_script05.csv).

Saídas (results/resolucao/):
    curva_por_origem.csv, curva_resumo.csv, selecao_w.json, validacao_vs_script05.csv,
    diagnostico_esparsidade.csv, fig_curva_resolucao.png

Uso:
    python scripts/08_resolution_curve.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import h3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.avaliacao import alvo, corte, disponiveis, ganho_esperado, origens_dev, universo_quadrados  # noqa: E402
from geodetect.dados import CELULA_M, CRS_METRICO, DEV, carregar_preparado  # noqa: E402

RESOLUCOES = (6, 7, 8, 9, 10)
FRACOES = (0.01, 0.02, 0.05)
W = (0.25, 0.5, 1.0, 2.0)
JANELA_A = 24
ORC_SELECAO = 0.02
_LL = Transformer.from_crs(CRS_METRICO, "EPSG:4326", always_xy=True)
_M = Transformer.from_crs("EPSG:4326", CRS_METRICO, always_xy=True)


def contagem_por_quadrado(quadrados: list[str], res: int) -> pd.DataFrame:
    """Nº de células H3 com centro em cada quadrado de 5 km e área aproximada dessas células."""
    linhas = []
    for q in quadrados:
        i, j = map(int, q.split("_"))
        caixa = shapely.box(i * CELULA_M, j * CELULA_M, (i + 1) * CELULA_M, (j + 1) * CELULA_M)
        ll = shapely.transform(caixa, lambda xy: np.column_stack(_LL.transform(xy[:, 0], xy[:, 1])))
        n = len(h3.h3shape_to_cells(h3.geo_to_h3shape(ll.__geo_interface__), res))
        cx, cy = _LL.transform((i + 0.5) * CELULA_M, (j + 0.5) * CELULA_M)
        a = h3.cell_area(h3.latlng_to_cell(cy, cx, res), unit="km^2")
        linhas.append((q, n, n * a))
    return pd.DataFrame(linhas, columns=["quadrado", "n_celulas", "area_km2"]).set_index("quadrado")


def quadrado_do_centro(celulas: np.ndarray) -> np.ndarray:
    lat, lon = np.array([h3.cell_to_latlng(c) for c in celulas]).T if len(celulas) else (np.array([]), np.array([]))
    x, y = _M.transform(lon, lat)
    return np.char.add(np.char.add(np.floor(np.asarray(x) / CELULA_M).astype(int).astype(str), "_"),
                       np.floor(np.asarray(y) / CELULA_M).astype(int).astype(str))


def ganho_esparso(score_pos: np.ndarray, valor_pos: np.ndarray, soma_valor_zero: float, n_zero: int, k: int) -> float:
    """Ganho esperado com k seleções: células com score > 0 explícitas; n_zero células com score 0."""
    n_pos = len(score_pos)
    if k <= n_pos:
        return ganho_esperado(score_pos, valor_pos, k)
    vagas = min(k - n_pos, n_zero)
    return float(valor_pos.sum() + (vagas * soma_valor_zero / n_zero if n_zero else 0.0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/resolucao", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)

    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]].copy()  # o teste nunca entra na memória deste script
    origens = origens_dev()
    nomes = [t.date().isoformat() for t in origens]
    disp_ult = disponiveis(g, origens[-1])
    quad_max = universo_quadrados(disp_ult["cel_i"].to_numpy(), disp_ult["cel_j"].to_numpy())
    cx, cy = g.geometry.centroid.x.to_numpy(), g.geometry.centroid.y.to_numpy()
    lon, lat = _LL.transform(cx, cy)

    linhas, diag, tempos = [], [], {}
    for res in RESOLUCOES:
        t0 = time.perf_counter()
        cont = contagem_por_quadrado(quad_max, res)
        ev = pd.DataFrame({"chave": g["chave"].to_numpy(), "view_date": g["view_date"].to_numpy(),
                           "celula": [h3.latlng_to_cell(a, b, res) for a, b in zip(lat, lon)]})
        cel_quad = dict(zip(ev["celula"], quadrado_do_centro(ev["celula"].to_numpy())))
        for t, nome_t in zip(origens, nomes):
            c = corte(t)
            disp, tgt = disponiveis(ev, t), alvo(ev, t)
            d_g = disponiveis(g, t)
            u_quad = set(universo_quadrados(d_g["cel_i"].to_numpy(), d_g["cel_j"].to_numpy()))
            cu = cont.loc[cont.index.isin(u_quad)]
            n_u, area_u_cel = int(cu["n_celulas"].sum()), float(cu["area_km2"].sum())
            area_ref, a_media = 25.0 * len(u_quad), area_u_cel / n_u

            a24 = disp[disp["view_date"] >= c - pd.DateOffset(months=JANELA_A)].groupby("celula").size()
            suporte = set(a24.index)
            for cel in list(a24.index):
                suporte.update(h3.grid_ring(cel, 1))
            sup = np.array(sorted(suporte))
            quad_sup = quadrado_do_centro(sup)
            dentro = np.isin(quad_sup, list(u_quad))
            sup = sup[dentro]
            a_sup = a24.reindex(sup).fillna(0).to_numpy(float)
            nb = np.array([a24.reindex(h3.grid_ring(c_, 1)).fillna(0).mean() for c_ in sup])

            y = tgt.groupby("celula").size()
            y_no_u = y[[cel_quad.get(c_, quadrado_do_centro(np.array([c_]))[0]) in u_quad for c_ in y.index]]
            tot = float(len(tgt))
            y_sup = y_no_u.reindex(sup).fillna(0).to_numpy(float)
            fora_sup = float(y_no_u.sum() - y_sup.sum())  # alertas-alvo em células de score 0
            diag.append({"res": res, "origem": nome_t, "celulas_universo": n_u, "celulas_suporte": len(sup),
                         "celulas_com_historico_24m": int((a_sup > 0).sum()),
                         "alertas_alvo": int(tot),
                         "pct_alvos_em_celula_com_historico_24m": 100 * float(y_no_u.reindex(a24.index).fillna(0).sum()) / tot,
                         "pct_alvos_no_suporte_vizinhanca": 100 * float(y_sup.sum()) / tot,
                         "area_universo_sobre_referencia": area_u_cel / area_ref})

            modelos = {"A": a_sup} | {f"C_{w}": a_sup + w * nb for w in W}
            for f in FRACOES:
                k = max(1, int(round(f * area_ref / a_media)))
                for m, s in modelos.items():
                    pos = s > 0
                    n_zero = n_u - int(pos.sum())
                    soma_zero = fora_sup + float(y_sup[~pos].sum())
                    h = ganho_esparso(s[pos], y_sup[pos], soma_zero, n_zero, k)
                    linhas.append({"res": res, "origem": nome_t, "metodo": m, "fracao": f, "k": k,
                                   "area_celula_km2": a_media, "recall_alertas": h / tot if tot else np.nan})
        tempos[res] = round(time.perf_counter() - t0, 1)
        print(f"r{res}: {tempos[res]} s")

    cur = pd.DataFrame(linhas)
    cur.to_csv(args.saida / "curva_por_origem.csv", index=False, float_format="%.5f")
    dg = pd.DataFrame(diag)
    dg.to_csv(args.saida / "diagnostico_esparsidade.csv", index=False, float_format="%.4f")

    # escolha de w nas origens 1–3 (como no script 05)
    aj, av = nomes[:3], nomes[3:]
    sel = {}
    for res, d in cur[(cur["fracao"] == ORC_SELECAO) & cur["metodo"].str.startswith("C_")].groupby("res"):
        sel[int(res)] = d[d["origem"].isin(aj)].groupby("metodo")["recall_alertas"].mean().idxmax()
    (args.saida / "selecao_w.json").write_text(json.dumps({"criterio": "maior recall médio, 2%, origens 1–3",
                                                           "escolhas": {f"r{k}": v for k, v in sel.items()}}, indent=2),
                                               encoding="utf-8")
    cur["modelo"] = np.where(cur["metodo"] == "A", "A",
                             np.where(cur.apply(lambda r: sel[int(r["res"])] == r["metodo"], axis=1), "C*", None))
    p = cur[cur["modelo"].notna()]
    resumo = (p.groupby(["res", "modelo", "fracao"])
              .apply(lambda d: pd.Series({
                  "metodo": d["metodo"].iloc[0], "area_celula_km2": d["area_celula_km2"].mean(), "k_medio": d["k"].mean(),
                  "recall_6orig": d["recall_alertas"].mean(),
                  "recall_ajuste": d[d["origem"].isin(aj)]["recall_alertas"].mean(),
                  "recall_avaliacao": d[d["origem"].isin(av)]["recall_alertas"].mean(),
                  "origens_melhor_que_r7": np.nan}), include_groups=False)
              .reset_index())
    # quantas origens cada resolução supera o r7 (mesmo modelo e orçamento)
    piv = p.pivot_table(index=["modelo", "fracao", "origem"], columns="res", values="recall_alertas")
    for (modelo, f), d in piv.groupby(level=[0, 1]):
        for res in RESOLUCOES:
            m = (resumo["res"] == res) & (resumo["modelo"] == modelo) & (resumo["fracao"] == f)
            resumo.loc[m, "origens_melhor_que_r7"] = int((d[res] > d[7]).sum()) if res != 7 else np.nan
    resumo["tempo_s"] = resumo["res"].map(tempos)
    resumo.to_csv(args.saida / "curva_resumo.csv", index=False, float_format="%.4f")

    # validação contra o script 05 (r6–r8)
    ref = pd.read_csv("results/hexagonal/comparacao_por_origem.csv")
    ref = ref[ref["grade"].isin(["h3_r6", "h3_r7", "h3_r8"]) & ref["fracao"].isin(FRACOES)
              & ref["metodo"].isin(["A"] + [f"C_{w}" for w in W])].copy()
    ref["res"] = ref["grade"].str[-1].astype(int)
    val = cur.merge(ref[["res", "origem", "metodo", "fracao", "k", "recall_alertas"]],
                    on=["res", "origem", "metodo", "fracao"], suffixes=("", "_05"))
    val["dif_recall"] = val["recall_alertas"] - val["recall_alertas_05"]
    val["dif_k"] = val["k"] - val["k_05"]
    val.to_csv(args.saida / "validacao_vs_script05.csv", index=False, float_format="%.6f")

    # figura
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axs = plt.subplots(1, 3, figsize=(14, 4.2), sharey=True)
    for ax, f in zip(axs, FRACOES):
        for modelo, cor, rot in (("A", "#2a6f97", "A — só a própria célula"), ("C*", "#e07a1f", "C* — própria + 6 vizinhos")):
            d = resumo[(resumo["modelo"] == modelo) & (resumo["fracao"] == f)].sort_values("res")
            ax.plot(d["res"], d["recall_6orig"], marker="o", color=cor, label=rot)
            ax.fill_between(d["res"], d["recall_ajuste"], d["recall_avaliacao"], color=cor, alpha=0.12)
        ref5 = pd.read_csv("results/hexagonal/comparacao_resumo.csv")
        r5 = ref5[(ref5["grade"] == "quadrado_5km") & (ref5["modelo"] == "A") & (ref5["orcamento"] == f"{f*100:g}%")]
        if len(r5):
            ax.axhline(r5["recall_alertas_6orig"].iloc[0], color="#333", ls="--", lw=1, label="quadrado 5 km (A)")
        ax.set_xticks(RESOLUCOES)
        ax.set_xticklabels([f"r{r}\n{resumo[resumo['res'] == r]['area_celula_km2'].iloc[0]:.3g} km²" for r in RESOLUCOES], fontsize=8)
        ax.set_title(f"orçamento {f:.0%} da área")
    axs[0].set_ylabel("recall de alertas futuros (média de 6 origens)")
    axs[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Curva de resolução H3 — EXPLORATÓRIA, só desenvolvimento (faixa: média ajuste ↔ avaliação)", fontsize=11)
    fig.tight_layout(); fig.savefig(args.saida / "fig_curva_resolucao.png", dpi=160); plt.close(fig)

    pd.set_option("display.width", 220)
    print(resumo[resumo["fracao"] == ORC_SELECAO].round(3).to_string(index=False))
    print(json.dumps(sel))
    print("validação r6–r8: dif máx recall", float(val["dif_recall"].abs().max()), "| dif máx k", int(val["dif_k"].abs().max()), "| linhas", len(val))
    print(dg.groupby("res")[["celulas_universo", "celulas_com_historico_24m", "pct_alvos_em_celula_com_historico_24m",
                             "pct_alvos_no_suporte_vizinhanca", "area_universo_sobre_referencia"]].mean().round(3))


if __name__ == "__main__":
    main()
