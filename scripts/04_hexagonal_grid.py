"""Atribui os alertas às grades quadradas (5; 2,5; 1 km) e H3 (res. 6, 7, 8) e descreve as grades.

Para cada grade:
    - célula do centroide de cada alerta (usada para CONTAGEM);
    - interseção polígono × célula (usada para ÁREA, sem dupla contagem);
    - validação: a soma das interseções deve reproduzir a área do alerta;
    - tempo de processamento e pico de memória (tracemalloc, só alocações Python/NumPy).

Usa apenas alertas até o fim do desenvolvimento (2025-06-30) nas tabelas e mapas.
As atribuições de TODOS os alertas até essa data são salvas para os scripts 05 e 06.

Saídas:
    data/processed/atribuicao_<grade>.csv.gz    chave, celula, area_km2 (interseção)
    data/processed/centroide_<grade>.csv.gz     chave, celula
    results/hexagonal/tabela_grades.csv         tamanho das células, células ocupadas, divisão de alertas, custo
    results/hexagonal/validacao_area.json       conservação de área por grade
    results/hexagonal/fig_mapa_grades.png       mesma região nas seis grades (histórico 2016–2023)
    results/hexagonal/fig_mapa_h3_r7_para.png   distribuição histórica no Pará em H3 res. 7

Uso:
    python scripts/04_hexagonal_grid.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.dados import CRS_METRICO, DEV, LIMITE_PADRAO, carregar_preparado  # noqa: E402
from geodetect.grades import grades_padrao  # noqa: E402

HIST_FIM = "2023-12-31"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/hexagonal", type=Path)
    ap.add_argument("--processados", default="data/processed", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    args.processados.mkdir(parents=True, exist_ok=True)

    g = carregar_preparado()
    g = g[g["view_date"] <= DEV[1]].copy()  # teste fora da memória
    hist = g["view_date"] <= HIST_FIM
    dev = g["view_date"] >= DEV[0]

    linhas, validacao, centroides, atribs = [], {}, {}, {}
    for grade in grades_padrao():
        tracemalloc.start()
        t0 = time.perf_counter()
        cent = grade.celula_dos_centroides(g)
        t_cent = time.perf_counter() - t0
        t1 = time.perf_counter()
        inter = grade.intersecoes(g)
        t_inter = time.perf_counter() - t1
        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        cent_df = pd.DataFrame({"chave": g["chave"].to_numpy(), "celula": cent.to_numpy()})
        cent_df.to_csv(args.processados / f"centroide_{grade.nome}.csv.gz", index=False)
        inter.to_csv(args.processados / f"atribuicao_{grade.nome}.csv.gz", index=False, float_format="%.7f")
        centroides[grade.nome], atribs[grade.nome] = cent_df, inter

        soma = inter.groupby("chave")["area_km2"].sum().reindex(g["chave"]).fillna(0).to_numpy()
        erro_rel = np.abs(soma - g["area_km2"].to_numpy()) / g["area_km2"].to_numpy()
        n_cel = inter.groupby("chave").size().reindex(g["chave"]).fillna(0).to_numpy()
        # a célula do centroide é a de maior interseção?
        maior = inter.sort_values("area_km2").groupby("chave").tail(1).set_index("chave")["celula"]
        coincide = (maior.reindex(g["chave"]).to_numpy() == cent.to_numpy()).mean()

        validacao[grade.nome] = {
            "erro_relativo_area_max": float(erro_rel.max()),
            "erro_relativo_area_medio": float(erro_rel.mean()),
            "alertas_sem_intersecao": int((n_cel == 0).sum()),
            "area_total_alertas_km2": round(float(g["area_km2"].sum()), 4),
            "area_total_intersecoes_km2": round(float(inter["area_km2"].sum()), 4),
        }

        cel_hist = set(cent[hist.to_numpy()])
        cel_dev = set(cent[dev.to_numpy()])
        todas = sorted(set(cent) | set(inter["celula"]))
        areas = grade.area_km2(todas)
        a_media = float(areas.mean())
        n_pent = int(sum(1 for c in todas if grade.nome.startswith("h3") and __import__("h3").is_pentagon(c)))
        linhas.append({
            "grade": grade.nome,
            "area_celula_media_km2": round(a_media, 3),
            "area_celula_min_km2": round(float(areas.min()), 3),
            "area_celula_max_km2": round(float(areas.max()), 3),
            "razao_area_vs_quadrado_25km2": round(a_media / 25, 3),
            "papel": "referência" if grade.nome == "quadrado_5km" else ("controle de resolução" if grade.nome.startswith("quadrado") else "hexagonal"),
            "vizinhos_imediatos": 8 if grade.nome.startswith("quadrado") else 6,
            "pentagonos_entre_celulas_usadas": n_pent,
            "celulas_com_alerta_2016_2023": len(cel_hist),
            "area_dessas_celulas_km2": round(len(cel_hist) * a_media, 1),
            "celulas_com_alerta_dev": len(cel_dev),
            "alertas_dev_por_celula_ocupada": round(int(dev.sum()) / len(cel_dev), 2),
            "pct_alertas_em_mais_de_uma_celula": round(100 * float((n_cel > 1).mean()), 2),
            "celulas_por_alerta_media": round(float(n_cel.mean()), 3),
            "pct_centroide_na_celula_de_maior_area": round(100 * float(coincide), 2),
            "tempo_centroides_s": round(t_cent, 3),
            "tempo_intersecoes_s": round(t_inter, 3),
            "pico_memoria_mb": round(pico / 2**20, 1),
        })
        print(f"{grade.nome}: {linhas[-1]['celulas_com_alerta_2016_2023']} células históricas, "
              f"erro máx. de área {erro_rel.max():.2e}, {t_inter:.1f}s")

    tab = pd.DataFrame(linhas)
    tab.to_csv(args.saida / "tabela_grades.csv", index=False)
    (args.saida / "validacao_area.json").write_text(json.dumps(validacao, indent=2), encoding="utf-8")

    # ---- mapas ---------------------------------------------------------------
    plt.rcParams.update({"font.size": 10})
    limite = gpd.read_file(LIMITE_PADRAO).to_crs(CRS_METRICO)
    chaves_hist = set(g.loc[hist, "chave"])
    # região de zoom: núcleo do Tapajós (percentis 10–90 dos alertas históricos, com margem)
    gh = g[hist]
    cx, cy = gh.geometry.centroid.x, gh.geometry.centroid.y
    x0, x1 = cx.quantile(0.05), cx.quantile(0.55)
    y0, y1 = cy.quantile(0.15), cy.quantile(0.85)
    grades = {gr.nome: gr for gr in grades_padrao()}

    def contagem(nome):
        c = centroides[nome]
        return c[c["chave"].isin(chaves_hist)].groupby("celula").size()

    vmax = max(int(contagem(n).max()) for n in grades)
    norm = matplotlib.colors.LogNorm(vmin=1, vmax=vmax)
    fig, axs = plt.subplots(2, 3, figsize=(15, 10))
    for ax, (nome, gr) in zip(axs.ravel(), grades.items()):
        cont = contagem(nome)
        pol = gr.poligonos(cont.index)
        gpd.GeoDataFrame({"n": cont.to_numpy()}, geometry=pol.to_numpy(), crs=CRS_METRICO).plot(
            ax=ax, column="n", cmap="viridis", norm=norm, linewidth=0)
        limite.boundary.plot(ax=ax, color="#555", linewidth=0.6)
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_xticks([]); ax.set_yticks([])
        lin = tab.set_index("grade").loc[nome]
        ax.set_title(f"{nome} — célula ≈ {lin['area_celula_media_km2']} km²\n"
                     f"{len(cont)} células com alerta (2016–2023)", fontsize=10)
    sm = matplotlib.cm.ScalarMappable(norm=norm, cmap="viridis")
    fig.colorbar(sm, ax=axs, shrink=0.6, label="alertas por célula, 2016–2023 (log)")
    fig.suptitle("Mesma região (núcleo do Tapajós) em seis grades — contagem por centroide", fontsize=12)
    fig.savefig(args.saida / "fig_mapa_grades.png", dpi=150, bbox_inches="tight"); plt.close(fig)

    gr = grades["h3_r7"]
    cont = contagem("h3_r7")
    fig, ax = plt.subplots(figsize=(8, 8))
    limite.boundary.plot(ax=ax, color="#555", linewidth=0.6)
    gpd.GeoDataFrame({"n": cont.to_numpy()}, geometry=gr.poligonos(cont.index).to_numpy(), crs=CRS_METRICO).plot(
        ax=ax, column="n", cmap="viridis", norm=matplotlib.colors.LogNorm(vmin=1, vmax=cont.max()),
        linewidth=0, legend=True, legend_kwds={"shrink": 0.6, "label": "alertas por hexágono (log)"})
    ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
    ax.set_title("Alertas de mineração 2016–2023 em H3 resolução 7 (≈5,6 km²)")
    fig.tight_layout(); fig.savefig(args.saida / "fig_mapa_h3_r7_para.png", dpi=150); plt.close(fig)

    print(tab.to_string(index=False))


if __name__ == "__main__":
    main()
