"""Grafo espaçotemporal × frequência, vizinhança e raio fixo — EXPLORATÓRIO, H3 r7, só desenvolvimento.

Pergunta: a sequência temporal dos alertas (decaimento e episódios espaçotemporais) acrescenta
informação à priorização, além da frequência histórica e da vizinhança espacial?

Grade H3 r7; universo, orçamento em km², empates e Recall@B como no protocolo congelado
(protocolo/protocolo_avaliacao_final.json). Não há período independente novo: o teste de 2026 já
foi usado. Por isso a avaliação é EXPLORATÓRIA. Os parâmetros são escolhidos nas origens 1–3
(2024-01, 04, 07) e reportados nas origens 4–6 (2024-10, 2025-01, 2025-04).

Modelos (ver geodetect/grafos.py):
    A_propria   só a própria célula (frequência 24 meses, sem vizinhos)
    C           frequência + 0,5 · média dos vizinhos (configuração principal congelada)
    R1, R3      nº de alertas (24 meses) a até 1 / 3 km do centro da célula r7 (raio físico fixo)
    T_τ         C com peso exp(−idade/τ),            τ ∈ {90, 180, 365, 730} dias
    G_ds_dt     C com peso 1 + ln(tamanho do episódio), d_s ∈ {1, 2, 3} km, d_t ∈ {30, 60, 90} dias
    GT_τ_ds_dt  C com os dois pesos

Saídas (results/grafos/): por_origem.csv, resumo.csv, selecao.json, comparacoes.csv,
    estatisticas_grafo.csv, fig_recall_por_orcamento.png, fig_mapa_grafo.png

Uso:
    python scripts/10_temporal_graphs.py
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.avaliacao import alvo, corte, disponiveis, origens_dev, universo_quadrados  # noqa: E402
from geodetect.dados import CRS_METRICO, DEV, LIMITE_PADRAO, carregar_preparado  # noqa: E402
from geodetect.grades import GradeH3  # noqa: E402
from geodetect.grafos import arestas, componentes, janela_historica, pesos, pontuacao_celulas  # noqa: E402
from geodetect.modelos import k_orcamento, prob_selecao  # noqa: E402

FRACOES = (0.01, 0.02, 0.05)
CURVA = (0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.10)
TAUS = (90, 180, 365, 730)
DS_KM = (1, 2, 3)
DT_DIAS = (30, 60, 90)
RAIOS_KM = (1, 3)
ORC = 0.02
N_BOOT, SEMENTE = 2000, 2027


def configuracoes() -> dict[str, dict]:
    c = {"A_propria": {"modelo": "A", "w": 0.0}, "C": {"modelo": "A"}}
    for r in RAIOS_KM:
        c[f"R{r}"] = {"modelo": "R", "raio_m": r * 1000}
    for tau in TAUS:
        c[f"T_{tau}"] = {"modelo": "T", "tau": tau}
    for ds, dt in itertools.product(DS_KM, DT_DIAS):
        c[f"G_{ds}_{dt}"] = {"modelo": "G", "d_s_m": ds * 1000, "d_t_dias": dt}
    for tau, ds, dt in itertools.product(TAUS, DS_KM, DT_DIAS):
        c[f"GT_{tau}_{ds}_{dt}"] = {"modelo": "GT", "tau": tau, "d_s_m": ds * 1000, "d_t_dias": dt}
    return c


def familia(nome: str) -> str:
    return nome.split("_")[0] if nome.split("_")[0] in ("T", "G", "GT") else nome


def bootstrap(pa: pd.DataFrame, a: str, b: str, rng) -> tuple[float, float, float]:
    est = (pa[a].sum() - pa[b].sum()) / len(pa)
    grupos = []
    for _, d in pa.groupby("origem"):
        bl = d.groupby("bloco")[[a, b]].agg(["sum", "size"])
        grupos.append((bl[(a, "sum")].to_numpy(), bl[(b, "sum")].to_numpy(), bl[(a, "size")].to_numpy()))
    reps = np.empty(N_BOOT)
    for r in range(N_BOOT):
        sa = sb = n = 0.0
        for xa, xb, cnt in grupos:
            i = rng.integers(0, len(xa), len(xa))
            sa += xa[i].sum(); sb += xb[i].sum(); n += cnt[i].sum()
        reps[r] = (sa - sb) / n
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return est, lo, hi


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/grafos", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)

    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]].copy()  # o teste nunca entra na memória deste script
    grade = GradeH3(7)
    g["celula"] = grade.celula_dos_centroides(g).to_numpy()
    g["bloco"] = g["cel_i"].astype(str) + "_" + g["cel_j"].astype(str)
    ev = g[["chave", "view_date", "celula", "bloco", "cx", "cy", "cel_i", "cel_j"]]

    origens = origens_dev()
    nomes = [t.date().isoformat() for t in origens]
    disp_ult = disponiveis(g, origens[-1])
    quad_max = universo_quadrados(disp_ult["cel_i"].to_numpy(), disp_ult["cel_j"].to_numpy())
    mapa = grade.celulas_por_quadrado(quad_max)
    cel_all = mapa.index.to_numpy()
    area_all = grade.area_km2(cel_all).to_numpy()
    vz = grade.vizinhos(cel_all)
    viz_all = np.array([vz[c] for c in cel_all], dtype=object)
    cent = grade.poligonos(cel_all).centroid
    cxy_all = np.column_stack([cent.x.to_numpy(), cent.y.to_numpy()])

    confs = configuracoes()
    linhas, prob, estat = [], [], []
    for t, nome_t in zip(origens, nomes):
        d = disponiveis(ev, t)
        u_quad = set(universo_quadrados(d["cel_i"].to_numpy(), d["cel_j"].to_numpy()))
        no_u = mapa.isin(u_quad).to_numpy()
        cel, area, viz, cxy = cel_all[no_u], area_all[no_u], viz_all[no_u], cxy_all[no_u]
        area_ref = 25.0 * len(u_quad)
        hist = janela_historica(d, t)
        tgt = alvo(ev, t)
        pos = pd.Series(np.arange(len(cel)), index=cel)
        y = tgt.groupby("celula").size().reindex(cel).fillna(0).to_numpy(float)
        sem_hist = ~tgt["celula"].isin(set(hist["celula"])).to_numpy()
        idx_t = pos.reindex(tgt["celula"]).to_numpy()
        kd = cKDTree(hist[["cx", "cy"]].to_numpy())

        for ds, dt in itertools.product(DS_KM, DT_DIAS):
            rot, tam = componentes(len(hist), arestas(hist["cx"].to_numpy(), hist["cy"].to_numpy(),
                                                      hist["view_date"], ds * 1000, dt))
            estat.append({"origem": nome_t, "d_s_km": ds, "d_t_dias": dt, "alertas": len(hist),
                          "episodios": int(rot.max() + 1) if len(rot) else 0,
                          "pct_alertas_isolados": 100 * float((tam == 1).mean()) if len(tam) else np.nan,
                          "maior_episodio": int(tam.max()) if len(tam) else 0,
                          "tamanho_medio_por_alerta": float(tam.mean()) if len(tam) else np.nan})

        pa = {"origem": np.full(len(tgt), nome_t), "chave": tgt["chave"].to_numpy(), "bloco": tgt["bloco"].to_numpy(),
              "sem_hist": sem_hist}
        for nome, cf in confs.items():
            if cf["modelo"] == "R":
                s = kd.query_ball_point(cxy, cf["raio_m"], return_length=True).astype(float)
            else:
                p_al = pesos(hist, t, cf["modelo"], cf.get("tau"), cf.get("d_s_m"), cf.get("d_t_dias"))
                s = pontuacao_celulas(cel, viz, hist, p_al, w=cf.get("w", 0.5))
            for f in sorted(set(FRACOES) | set(CURVA)):
                k = k_orcamento(f, area_ref, float(area.mean()))
                p = prob_selecao(s, k)
                p_t = np.where(np.isnan(idx_t), 0.0, p[np.nan_to_num(idx_t, nan=0).astype(int)])
                linhas.append({"origem": nome_t, "config": nome, "familia": familia(nome), "fracao": f, "k": k,
                               "alertas_alvo": len(tgt), "recall_alertas": float(p_t.mean()),
                               "recall_sem_historico": float(p_t[sem_hist].mean()) if sem_hist.any() else np.nan,
                               "alvos_sem_historico": int(sem_hist.sum())})
                if f in FRACOES:
                    pa[f"{nome}|{f}"] = p_t
        prob.append(pd.DataFrame(pa))
        print(f"{nome_t}: {len(hist)} alertas na janela, {len(tgt)} alvos, {len(cel)} células")

    met = pd.DataFrame(linhas)
    met.to_csv(args.saida / "por_origem.csv", index=False, float_format="%.5f")
    est = pd.DataFrame(estat)
    est.to_csv(args.saida / "estatisticas_grafo.csv", index=False, float_format="%.3f")
    pa_all = pd.concat(prob, ignore_index=True)

    aj, av = nomes[:3], nomes[3:]

    def agregado(d):
        return (d["recall_alertas"] * d["alertas_alvo"]).sum() / d["alertas_alvo"].sum()

    def agregado_sem(d):
        return (d["recall_sem_historico"] * d["alvos_sem_historico"]).sum() / d["alvos_sem_historico"].sum()

    m2 = met[(met["fracao"] == ORC) & met["origem"].isin(aj)]
    escolha = {}
    for fam in ("T", "G", "GT"):
        r = m2[m2["familia"] == fam].groupby("config").apply(agregado, include_groups=False)
        escolha[fam] = r.idxmax()
    (args.saida / "selecao.json").write_text(json.dumps({
        "criterio": "maior recall agregado (alertas capturados / alertas-alvo) com 2%, origens de ajuste",
        "origens_ajuste": aj, "origens_avaliacao": av, "escolhas": escolha}, indent=2, ensure_ascii=False), encoding="utf-8")

    principais = ["A_propria", "C", "R1", "R3", escolha["T"], escolha["G"], escolha["GT"]]
    rotulo = {"A_propria": "A_propria", "C": "C", "R1": "R1", "R3": "R3",
              escolha["T"]: f"T* ({escolha['T']})", escolha["G"]: f"G* ({escolha['G']})", escolha["GT"]: f"GT* ({escolha['GT']})"}

    resumo = []
    for nome in principais:
        for f in FRACOES:
            d = met[(met["config"] == nome) & (met["fracao"] == f)]
            resumo.append({"modelo": rotulo[nome], "config": nome, "fracao": f,
                           "recall_agregado_6orig": agregado(d),
                           "recall_agregado_ajuste": agregado(d[d["origem"].isin(aj)]),
                           "recall_agregado_avaliacao": agregado(d[d["origem"].isin(av)]),
                           "recall_medio_origens": d["recall_alertas"].mean(),
                           "recall_sem_historico_6orig": agregado_sem(d)})
    resumo = pd.DataFrame(resumo)
    resumo.to_csv(args.saida / "resumo.csv", index=False, float_format="%.4f")

    rng = np.random.default_rng(SEMENTE)
    comps = []
    for grupo, origs in (("avaliacao", av), ("todas", nomes)):
        pg = pa_all[pa_all["origem"].isin(origs)]
        for f in FRACOES:
            for a, b in ((escolha["T"], "C"), (escolha["G"], "C"), (escolha["GT"], "C"), ("C", "A_propria"),
                         ("R1", "C"), ("R3", "C")):
                e, lo, hi = bootstrap(pg, f"{a}|{f}", f"{b}|{f}", rng)
                por = pg.groupby("origem").apply(lambda d: (d[f"{a}|{f}"].sum() - d[f"{b}|{f}"].sum()) / len(d),
                                                 include_groups=False)
                comps.append({"grupo": grupo, "fracao": f, "a": a, "b": b, "diferenca": e, "ic95_inf": lo, "ic95_sup": hi,
                              "ic_exclui_zero": bool(lo > 0 or hi < 0), "origens_positivas": int((por > 0).sum()),
                              "origens": len(por)})
    comp = pd.DataFrame(comps)
    comp.to_csv(args.saida / "comparacoes.csv", index=False, float_format="%.4f")

    # ---- figuras ---------------------------------------------------------------
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    cores = ["#9aa5b1", "#e07a1f", "#2a6f97", "#1b4965", "#6a994e", "#8e44ad", "#c0392b"]
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.4), sharey=True)
    for ax, (tit, origs) in zip(axs, (("origens de avaliação (4–6)", av), ("todas as 6 origens", nomes))):
        for nome, cor in zip(principais, cores):
            d = met[(met["config"] == nome) & met["origem"].isin(origs)]
            cur = d.groupby("fracao").apply(agregado, include_groups=False)
            ax.plot(100 * cur.index, cur.values, marker="o", ms=3, color=cor, label=rotulo[nome],
                    lw=2.2 if nome == "C" else 1.3)
        ax.set_xlabel("orçamento (% da área do universo)"); ax.set_title(tit, fontsize=10)
    axs[0].set_ylabel("recall agregado de alertas futuros")
    axs[1].legend(frameon=False, fontsize=8, loc="lower right")
    fig.suptitle("H3 r7 — grafo espaçotemporal × referências (EXPLORATÓRIO, desenvolvimento)", fontsize=11)
    fig.tight_layout(); fig.savefig(args.saida / "fig_recall_por_orcamento.png", dpi=160); plt.close(fig)

    # mapa do grafo na última origem de desenvolvimento
    t = origens[-1]
    cg = confs[escolha["G"]]
    hist = janela_historica(disponiveis(ev, t), t)
    e = arestas(hist["cx"].to_numpy(), hist["cy"].to_numpy(), hist["view_date"], cg["d_s_m"], cg["d_t_dias"])
    _, tam = componentes(len(hist), e)
    tgt = alvo(ev, t)
    lim = gpd.read_file(LIMITE_PADRAO).to_crs(CRS_METRICO)
    fig, axs = plt.subplots(1, 2, figsize=(13, 6.5))
    for ax, zoom in zip(axs, (False, True)):
        lim.boundary.plot(ax=ax, color="#888", lw=0.5)
        hx, hy = hist["cx"].to_numpy(), hist["cy"].to_numpy()
        dt = np.abs((hist["view_date"].to_numpy()[e[:, 0]] - hist["view_date"].to_numpy()[e[:, 1]]).astype("timedelta64[D]").astype(int))
        for (i, j), dd in zip(e, dt):
            ax.plot([hx[i], hx[j]], [hy[i], hy[j]], color=plt.cm.viridis(dd / cg["d_t_dias"]), lw=0.6, alpha=0.8)
        sc = ax.scatter(hx, hy, c=np.log(tam), s=8, cmap="magma_r", zorder=3)
        ax.scatter(tgt["cx"], tgt["cy"], marker="x", s=14, color="#2a6f97", zorder=4, label="alertas do trimestre seguinte")
        if zoom:  # janela de ±15 km centrada no maior episódio
            i0 = int(np.argmax(tam))
            xm, ym = hx[i0], hy[i0]
            ax.set_xlim(xm - 15_000, xm + 15_000); ax.set_ylim(ym - 15_000, ym + 15_000)
            ax.set_title("zoom ±15 km no maior episódio", fontsize=9)
        ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    axs[0].legend(frameon=False, fontsize=8, loc="lower left")
    fig.colorbar(sc, ax=axs, shrink=0.6, label="ln(tamanho do episódio)")
    fig.suptitle(f"Grafo espaçotemporal na origem {t.date()} — {escolha['G']} (d_s={cg['d_s_m']//1000} km, d_t={cg['d_t_dias']} dias); "
                 f"arestas coloridas por Δt", fontsize=10)
    fig.savefig(args.saida / "fig_mapa_grafo.png", dpi=150, bbox_inches="tight"); plt.close(fig)

    pd.set_option("display.width", 220)
    print(json.dumps(escolha))
    print(resumo[resumo["fracao"] == ORC].round(3).to_string(index=False))
    print(comp[comp["fracao"] == ORC].round(3).to_string(index=False))
    print(est.groupby(["d_s_km", "d_t_dias"])[["pct_alertas_isolados", "maior_episodio", "tamanho_medio_por_alerta"]].mean().round(1))


if __name__ == "__main__":
    main()
