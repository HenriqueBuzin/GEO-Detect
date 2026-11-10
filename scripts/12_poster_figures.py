"""Figuras do pôster GEOMRIT 2027 a partir dos resultados já registrados.

Não executa nenhuma avaliação nova: as figuras de resultado leem os CSVs existentes.
O mapa calcula a seleção de UMA origem de desenvolvimento (2025-04) com o código congelado
(geodetect/modelos.py), apenas para ilustrar o método. O teste de 2026 não é recalculado.

Saídas: results/poster/fig_*.png (300 dpi)

Uso:
    python scripts/12_poster_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from geodetect.avaliacao import alvo, disponiveis, selecao_deterministica, universo_quadrados  # noqa: E402
from geodetect.dados import CRS_METRICO, DEV, LIMITE_PADRAO, carregar_preparado  # noqa: E402
from geodetect.grades import GradeQuadrada  # noqa: E402
from geodetect.modelos import k_orcamento, pontuacoes  # noqa: E402

R = RAIZ / "results"
OUT = R / "poster"
FUNDO = "#FAFAF7"
TINTA = "#1B1F24"
CINZA = "#8A9099"
AZUL = "#1F5F8B"     # quadrado 2,5 km (principal operacional)
LARANJA = "#C8641E"  # H3 r7 (controle)
plt.rcParams.update({
    "font.family": "Helvetica Neue", "font.size": 15, "axes.edgecolor": TINTA, "axes.labelcolor": TINTA,
    "xtick.color": TINTA, "ytick.color": TINTA, "text.color": TINTA, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": FUNDO, "axes.facecolor": FUNDO, "savefig.facecolor": FUNDO,
})


def br(v: float, casas: int = 1, sinal: bool = False) -> str:
    """Número no formato brasileiro, com sinal de menos tipográfico."""
    t = f"{v:+.{casas}f}" if sinal else f"{v:.{casas}f}"
    return t.replace("-", "−").replace(".", ",")


def eixo_br(ax, eixo="y", casas=2):
    f = matplotlib.ticker.FuncFormatter(lambda v, _: br(v, casas))
    (ax.yaxis if eixo == "y" else ax.xaxis).set_major_formatter(f)


def salvar(fig, nome):
    fig.savefig(OUT / nome, dpi=300, bbox_inches="tight")
    plt.close(fig)


def fig_resultado():
    """Teste independente: Recall@2% agregado e por origem, com as diferenças pré-especificadas."""
    ag = pd.read_csv(R / "avaliacao_final/teste/agregado.csv")
    po = pd.read_csv(R / "avaliacao_final/teste/por_origem.csv")
    cp = pd.read_csv(R / "avaliacao_final/teste/comparacoes.csv")
    sel = lambda d: d[(d["grupo"] == "independente") & (d["orcamento"].round(3) == 0.02)]
    ag, po, cp = sel(ag).set_index("modelo"), sel(po), sel(cp).set_index("id")
    modelos = [("quadrado_5km_A", "Grade original\nquadrado 5 km", CINZA),
               ("quadrado_2.5km_C", "Quadrado 2,5 km\n+ vizinhança", AZUL),
               ("h3_r7_C", "H3 resolução 7\n+ vizinhança", LARANJA)]
    fig, ax = plt.subplots(figsize=(8.6, 6.4))
    for i, (m, rot, cor) in enumerate(modelos):
        v = ag.loc[m, "recall_agregado"]
        ax.bar(i, v, width=0.62, color=cor, zorder=2)
        ax.text(i, 0.014, br(v, 3), ha="center", va="bottom", fontsize=24, fontweight="bold", color="white", zorder=4)
        pts = po[po["modelo"] == m]["recall_alertas"].to_numpy()
        ax.scatter(np.full(len(pts), i) + np.array([-0.12, 0, 0.12]), pts, s=34, color="white",
                   edgecolor=TINTA, linewidth=1.2, zorder=3)
    ax.set_xticks(range(3)); ax.set_xticklabels([r for _, r, _ in modelos], fontsize=15)
    ax.set_ylabel("Recall@2% — fração dos alertas futuros\ncapturada com 2% da área", fontsize=15)
    ax.set_ylim(0, 0.37)
    s4, p1 = cp.loc["S4"], cp.loc["P1"]
    ax.annotate("", xy=(1, 0.262), xytext=(0, 0.188), arrowprops=dict(arrowstyle="->", color=TINTA, lw=1.6))
    rel = ag.loc["quadrado_2.5km_C", "recall_agregado"] / ag.loc["quadrado_5km_A", "recall_agregado"] - 1
    ax.text(0.30, 0.300, f"resolução: {br(s4['diferenca']*100, 1, True)} p.p. ({br(rel*100, 0, True)}%)\n"
            f"IC 95% [{br(s4['ic95_inf']*100, 1, True)}; {br(s4['ic95_sup']*100, 1, True)}]", fontsize=13.5, ha="center")
    ax.plot([1, 1, 2, 2], [0.250, 0.272, 0.272, 0.250], color=TINTA, lw=1.2)
    ax.text(1.5, 0.282, f"forma: {br(p1['diferenca']*100, 1, True)} p.p.\n"
            f"IC 95% [{br(p1['ic95_inf']*100, 1, True)}; {br(p1['ic95_sup']*100, 1, True)}]", fontsize=13.5, ha="center")
    ax.scatter([], [], s=34, color="white", edgecolor=TINTA, label="cada trimestre independente (2026)")
    ax.legend(frameon=False, fontsize=12.5, loc="upper left")
    ax.grid(axis="y", color="#E3E3DE", zorder=0)
    eixo_br(ax)
    salvar(fig, "fig_resultado_teste.png")


def fig_resolucao():
    """Curva de resolução H3 (exploratória, desenvolvimento)."""
    r = pd.read_csv(R / "resolucao/curva_resumo.csv")
    r = r[r["fracao"].round(3) == 0.02]
    ref = pd.read_csv(R / "hexagonal/comparacao_resumo.csv")
    ref5 = ref[(ref["grade"] == "quadrado_5km") & (ref["modelo"] == "A") & (ref["orcamento"] == "2%")]["recall_alertas_6orig"].iloc[0]
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    for modelo, cor, rot in (("C*", LARANJA, "célula + vizinhança"), ("A", CINZA, "só a própria célula")):
        d = r[r["modelo"] == modelo].sort_values("res")
        ax.plot(d["res"], d["recall_6orig"], marker="o", ms=8, lw=2.6, color=cor, label=rot)
    ax.axhline(ref5, color=TINTA, ls="--", lw=1.2)
    ax.text(9.95, ref5 + 0.006, "quadrado 5 km", fontsize=12, ha="right")
    areas = {6: "40 km²", 7: "5,7 km²", 8: "0,8 km²", 9: "0,12 km²", 10: "0,017 km²"}
    ax.set_xticks(list(areas)); ax.set_xticklabels([f"r{k}\n{v}" for k, v in areas.items()], fontsize=13)
    ax.set_ylabel("Recall@2% (desenvolvimento)", fontsize=15)
    ax.set_ylim(0, 0.36); ax.legend(frameon=False, fontsize=13, loc="upper right")
    ax.grid(axis="y", color="#E3E3DE", zorder=0)
    eixo_br(ax)
    salvar(fig, "fig_resolucao.png")


def fig_forma_posicao():
    """Variação com o deslocamento da grade × efeito da forma (exploratório, desenvolvimento)."""
    r = pd.read_csv(R / "decisao_grade/recall_agregado_por_configuracao.csv")
    r = r[(r["modelo"] == "C") & (r["orcamento"].round(3) == 0.02)]
    fams = [("quadrado_2.5km", "quadrado\n6,25 km²", AZUL), ("hex_plano_6.25km2", "hexágono\n6,25 km²", LARANJA),
            ("quadrado_aream_h3", "quadrado\n5,75 km²", AZUL), ("hex_plano_aream_h3", "hexágono\n5,75 km²", LARANJA)]
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    rng = np.random.default_rng(0)
    for i, (f, rot, cor) in enumerate(fams):
        v = r[r["familia"] == f]["recall_agregado"].to_numpy()
        ax.scatter(i + rng.uniform(-0.14, 0.14, len(v)), v, s=40, color=cor, alpha=0.85, zorder=3)
        ax.plot([i - 0.25, i + 0.25], [v.mean()] * 2, color=TINTA, lw=2.4, zorder=4)
    h3 = r[r["familia"] == "h3_r7"]["recall_agregado"].iloc[0]
    ax.axhline(h3, color=LARANJA, ls=":", lw=1.6)
    ax.text(3.45, h3 + 0.002, "H3 r7 (posição fixa)", fontsize=12, ha="right", va="bottom", color=LARANJA)
    ax.set_xticks(range(4)); ax.set_xticklabels([x[1] for x in fams], fontsize=13)
    ax.set_ylabel("Recall@2% (desenvolvimento)", fontsize=15)
    ax.set_ylim(0.225, 0.31)
    ax.grid(axis="y", color="#E3E3DE", zorder=0)
    eixo_br(ax, casas=2)
    salvar(fig, "fig_forma_posicao.png")


def fig_temporal():
    """Grafo espaçotemporal e decaimento × vizinhança simples (exploratório)."""
    c = pd.read_csv(R / "grafos/comparacoes.csv")
    c = c[(c["grupo"] == "avaliacao") & (c["fracao"].round(3) == 0.02) & (c["b"] == "C") & c["a"].isin(["T_730", "G_1_90", "GT_365_2_60"])]
    rot = {"T_730": "decaimento temporal", "G_1_90": "episódios do grafo", "GT_365_2_60": "grafo + decaimento"}
    c = c.set_index("a").loc[["T_730", "G_1_90", "GT_365_2_60"]]
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    y = np.arange(len(c))[::-1]
    ax.errorbar(100 * c["diferenca"], y, xerr=[100 * (c["diferenca"] - c["ic95_inf"]), 100 * (c["ic95_sup"] - c["diferenca"])],
                fmt="o", ms=9, color=TINTA, capsize=5, lw=1.8)
    ax.axvline(0, color=CINZA, lw=1.2)
    ax.set_yticks(y); ax.set_yticklabels([rot[a] for a in c.index], fontsize=14)
    ax.set_xlabel("diferença de Recall@2% em relação à vizinhança simples (p.p., IC 95%)", fontsize=13.5)
    ax.set_xlim(-6, 6)
    eixo_br(ax, "x", casas=0)
    salvar(fig, "fig_temporal.png")


def fig_mapa():
    """Pará: alertas e células selecionadas (quadrado 2,5 km + vizinhança, 2%) numa origem de desenvolvimento."""
    t = pd.Timestamp("2025-04-01")
    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]].copy()
    grade = GradeQuadrada(2500)
    g["celula"] = grade.celula_dos_centroides(g).to_numpy()
    disp = disponiveis(g, t)
    tgt = alvo(g, t)
    u = universo_quadrados(disp["cel_i"].to_numpy(), disp["cel_j"].to_numpy())
    cel = grade.celulas_por_quadrado(u).index.to_numpy()
    viz_d = grade.vizinhos(cel)
    viz = np.array([viz_d[c] for c in cel], dtype=object)
    s = pontuacoes(cel, viz, disp[["view_date", "celula", "chave"]], t, {"C": 0.5})["C"]
    k = k_orcamento(0.02, 25.0 * len(u), 6.25)
    sel = cel[selecao_deterministica(s, k)]
    pol = grade.poligonos(sel)
    hist = disp[disp["view_date"] >= t - pd.DateOffset(months=25)]
    lim = gpd.read_file(LIMITE_PADRAO).to_crs(CRS_METRICO)
    fig, axs = plt.subplots(1, 2, figsize=(14, 7.4), gridspec_kw={"width_ratios": [1, 1]})
    for ax, zoom in zip(axs, (False, True)):
        lim.plot(ax=ax, color="#EEEDE7", edgecolor="#9A9C98", lw=0.8)
        gpd.GeoSeries(pol.to_numpy(), crs=CRS_METRICO).plot(ax=ax, color=AZUL, alpha=0.55, linewidth=0)
        ax.scatter(hist["cx"], hist["cy"], s=3 if not zoom else 10, color="#5C6168", alpha=0.6, lw=0, label="alertas dos 24 meses anteriores")
        ax.scatter(tgt["cx"], tgt["cy"], s=22 if not zoom else 60, marker="x", color=LARANJA, lw=1.6,
                   label="alertas do trimestre seguinte")
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal"); ax.set_xlabel(""); ax.set_ylabel("")
        for sp in ax.spines.values():
            sp.set_visible(zoom)
    cx, cy = tgt["cx"].median(), tgt["cy"].median()
    axs[1].set_xlim(cx - 45_000, cx + 45_000); axs[1].set_ylim(cy - 45_000, cy + 45_000)
    axs[0].add_patch(plt.Rectangle((cx - 45_000, cy - 45_000), 90_000, 90_000, fill=False, ec=TINTA, lw=1.4))
    axs[0].scatter([], [], marker="s", s=80, color=AZUL, alpha=0.55, label="células selecionadas (2% da área)")
    axs[0].legend(frameon=False, fontsize=13, loc="upper center", bbox_to_anchor=(1.0, -0.02), ncol=3, markerscale=1.6)
    axs[1].text(0.02, 0.97, "zoom 90 × 90 km — bacia do Tapajós", transform=axs[1].transAxes, fontsize=12.5, va="top")
    salvar(fig, "fig_mapa.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_resultado()
    fig_resolucao()
    fig_forma_posicao()
    fig_temporal()
    fig_mapa()
    print(sorted(p.name for p in OUT.glob("*.png")))
