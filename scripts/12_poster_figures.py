"""Gera a figura de precisão média publicada no artigo."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]

R = RAIZ / "results"
OUT = R / "poster"
FUNDO = "#FAFAF7"
TINTA = "#1B1F24"
CINZA = "#8A9099"
AZUL = "#1F5F8B"     # quadrado 2,5 km (principal operacional)
LARANJA = "#C8641E"  # H3 r7 (controle)
plt.rcParams.update({
    "font.family": ["Helvetica Neue", "DejaVu Sans"], "font.size": 15, "axes.edgecolor": TINTA, "axes.labelcolor": TINTA,
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
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / nome, dpi=300, bbox_inches="tight")
    plt.close(fig)


def fig_precisao_alertas():
    """Compara a LSTM do GEO-Detect com adaptações de dois artigos publicados."""
    redes = pd.read_csv(R / "redes_temporais/por_origem.csv", parse_dates=["origem"])
    floresta = pd.read_csv(R / "multiescala/bases_por_origem.csv", parse_dates=["origem"])
    floresta = floresta[floresta.modelo == "random_forest_adaptada"]
    resultados = pd.concat([redes, floresta], ignore_index=True)
    tabela = resultados.pivot(index="origem", columns="modelo", values="precisao_media") * 100
    rotulos = [f"{t.year} T{t.quarter}" for t in tabela.index]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    pos = np.arange(len(tabela))
    ax.bar(pos - .25, tabela["lstm_kanoga"], width=.24, label="GEO-Detect (LSTM)", color=AZUL)
    ax.bar(pos, tabela["random_forest_adaptada"], width=.24,
           label="Larrea-Gallegos (adapt.)", color=LARANJA)
    ax.bar(pos + .25, tabela["ann_mayfield"], width=.24, label="Mayfield (adapt.)", color="#518778")
    ax.set_ylabel("Precisão média (AP, %)")
    ax.set_xticks(pos, rotulos)
    ax.grid(axis="y", color="#E3E3DE", zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc="lower center", bbox_to_anchor=(.5, 1.01), ncol=3, frameon=False, fontsize=9)
    eixo_br(ax, "y", casas=1)
    salvar(fig, "fig_precisao_alertas.png")



if __name__ == "__main__":
    fig_precisao_alertas()
