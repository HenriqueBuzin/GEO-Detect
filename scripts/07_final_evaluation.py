"""Avaliação final pré-especificada do GEO-Detect (ver protocolo/PROTOCOLO_AVALIACAO_FINAL.md).

Modos:
    --modo dev    valida o pipeline nas 6 origens de desenvolvimento, sem ler o teste.
                  Deve reproduzir os números do script 05. A saída pode ser sobrescrita.
    --modo teste  avaliação final, uma única vez. Exige que protocolo, geodetect/ e este script
                  estejam commitados e sem alterações. Recusa sobrescrever a saída existente.

Tudo vem de protocolo/protocolo_avaliacao_final.json; nada é ajustável por linha de comando.

Saídas (results/avaliacao_final/<modo>/):
    por_origem.csv, agregado.csv, comparacoes.csv, verificacao_area.csv, estabilidade.csv,
    execucao.json, fig_recall_por_origem.png, fig_comparacoes.png

Uso:
    python scripts/07_final_evaluation.py --modo dev
    python scripts/07_final_evaluation.py --modo teste
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from geodetect.avaliacao import (  # noqa: E402
    HORIZONTE, alvo, disponiveis, jaccard, origens_dev, selecao_deterministica, universo_quadrados,
)
from geodetect.dados import DEV, carregar_preparado  # noqa: E402
from geodetect.grades import grades_padrao  # noqa: E402
from geodetect.modelos import k_orcamento, pontuacoes, prob_selecao  # noqa: E402

PROTOCOLO = RAIZ / "protocolo" / "protocolo_avaliacao_final.json"
CONGELADOS = ["protocolo", "geodetect", "scripts/07_final_evaluation.py"]
N_BOOT, SEMENTE = 2000, 2027


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True).stdout.strip()


def verificar_git() -> dict:
    sujo = subprocess.run(["git", "status", "--porcelain", "--", *CONGELADOS], cwd=RAIZ,
                          capture_output=True, text=True, check=True).stdout.strip()
    if sujo:
        raise SystemExit(f"Recusado: arquivos congelados com alterações não commitadas:\n{sujo}")
    return {"commit_head": git("rev-parse", "HEAD"),
            "commit_protocolo": git("log", "-1", "--format=%H", "--", "protocolo/protocolo_avaliacao_final.json"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD")}


def grupos_de_origens(proto: dict, modo: str) -> dict[str, list[pd.Timestamp]]:
    if modo == "dev":
        return {"desenvolvimento": origens_dev()}
    o = proto["origens"]
    return {"independente": [pd.Timestamp(x) for x in o["teste_independente"]],
            "semi_independente": [pd.Timestamp(x) for x in o["teste_semi_independente"]]}


def bootstrap_diferenca(pa: pd.DataFrame, a: str, b: str, rng: np.random.Generator) -> np.ndarray:
    """pa: linhas = alertas-alvo (origem, bloco) com colunas de probabilidade de captura por modelo."""
    reps = np.empty(N_BOOT)
    grupos = [d for _, d in pa.groupby("origem")]
    estrut = []
    for d in grupos:
        blocos = d.groupby("bloco")[[a, b]].agg(["sum", "size"])
        estrut.append((blocos[(a, "sum")].to_numpy(), blocos[(b, "sum")].to_numpy(), blocos[(a, "size")].to_numpy()))
    for r in range(N_BOOT):
        sa = sb = n = 0.0
        for xa, xb, cnt in estrut:
            idx = rng.integers(0, len(xa), len(xa))
            sa += xa[idx].sum(); sb += xb[idx].sum(); n += cnt[idx].sum()
        reps[r] = (sa - sb) / n
    return reps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["dev", "teste"], required=True)
    args = ap.parse_args()

    proto = json.loads(PROTOCOLO.read_text(encoding="utf-8"))
    saida = RAIZ / "results" / "avaliacao_final" / args.modo
    execucao = {"modo": args.modo, "inicio_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "protocolo_sha256": sha256(PROTOCOLO), "protocolo_versao": proto["versao"]}
    if args.modo == "teste":
        if saida.exists():
            raise SystemExit(f"Recusado: {saida} já existe. A avaliação final só pode ser executada uma vez.")
        execucao["git"] = verificar_git()

    dados = RAIZ / proto["dados"]["arquivo"]
    if sha256(dados) != proto["dados"]["sha256"]:
        raise SystemExit("Recusado: SHA-256 dos dados difere do protocolo.")
    execucao["dados_sha256_ok"] = True

    grupos = grupos_de_origens(proto, args.modo)
    todas = sorted(t for ts in grupos.values() for t in ts)
    fim_dados = DEV[1] if args.modo == "dev" else (todas[-1] + HORIZONTE - pd.Timedelta(days=1)).date().isoformat()
    g = carregar_preparado(dados)
    g = g[g["view_date"] <= fim_dados].copy()  # nada além do último alvo pré-especificado
    g["bloco"] = g["cel_i"].astype(str) + "_" + g["cel_j"].astype(str)
    execucao["dados_ate"] = fim_dados
    saida.mkdir(parents=True, exist_ok=True)

    modelos = proto["modelos"]
    nomes_grades = sorted({m["grade"] for m in modelos.values()})
    grades = {gr.nome: gr for gr in grades_padrao() if gr.nome in nomes_grades}
    fracoes = proto["orcamentos"]
    primario = proto["orcamento_primario"]

    disp_ult = disponiveis(g, todas[-1])
    quad_max = universo_quadrados(disp_ult["cel_i"].to_numpy(), disp_ult["cel_j"].to_numpy())

    prep = {}
    for nome, gr in grades.items():
        cent = gr.celula_dos_centroides(g)
        inter = gr.intersecoes(g[g["view_date"] >= todas[0]])  # área só é usada nos alvos
        mapa = gr.celulas_por_quadrado(quad_max)
        cel_all = mapa.index.to_numpy()
        viz = gr.vizinhos(cel_all)
        prep[nome] = {
            "ev": g.assign(celula=cent.to_numpy())[["chave", "view_date", "celula", "bloco"]],
            "inter": g[["chave", "view_date"]].merge(inter, on="chave"),
            "mapa": mapa, "cel": cel_all, "area": gr.area_km2(cel_all).to_numpy(),
            "viz": np.array([viz[c] for c in cel_all], dtype=object),
        }

    linhas, verif, prob_alertas, estab = [], [], [], []
    sel_prev: dict = {}
    for grupo, origens in grupos.items():
        for t in origens:
            nome_t = t.date().isoformat()
            u_quad = set(universo_quadrados(disponiveis(g, t)["cel_i"].to_numpy(), disponiveis(g, t)["cel_j"].to_numpy()))
            area_ref = 25.0 * len(u_quad)
            tgt_base = alvo(g, t)
            pa = pd.DataFrame({"origem": nome_t, "grupo": grupo, "chave": tgt_base["chave"].to_numpy(),
                               "bloco": tgt_base["bloco"].to_numpy()})
            for nome_gr, P in prep.items():
                no_u = P["mapa"].isin(u_quad).to_numpy()
                cel, area, viz = P["cel"][no_u], P["area"][no_u], P["viz"][no_u]
                disp = disponiveis(P["ev"], t)
                tgt = alvo(P["ev"], t)
                tgt_i = alvo(P["inter"], t)
                ms = {m: v["w"] for m, v in modelos.items() if v["grade"] == nome_gr}
                sc = pontuacoes(cel, viz, disp, t, ms)
                pos = pd.Series(np.arange(len(cel)), index=cel)
                y_alert = tgt.groupby("celula").size().reindex(cel).fillna(0).to_numpy(float)
                y_area = tgt_i.groupby("celula")["area_km2"].sum().reindex(cel).fillna(0).to_numpy(float)
                y_cel = (y_alert > 0).astype(float)
                verif.append({"grupo": grupo, "origem": nome_t, "grade": nome_gr, "area_referencia_km2": area_ref,
                              "area_universo_km2": float(area.sum()),
                              "razao_universo": float(area.sum()) / area_ref, "celulas_universo": len(cel)})
                idx_alerta = pos.reindex(tgt.set_index("chave").loc[pa["chave"], "celula"]).to_numpy()
                for m, s in sc.items():
                    for f in fracoes:
                        k = k_orcamento(f, area_ref, float(area.mean()))
                        p = prob_selecao(s, k)
                        verif.append({"grupo": grupo, "origem": nome_t, "grade": nome_gr, "modelo": m, "orcamento": f,
                                      "k": k, "area_orcamento_km2": f * area_ref,
                                      "area_selecionada_km2": float((p * area).sum()),
                                      "razao_selecionada": float((p * area).sum()) / (f * area_ref)})
                        linhas.append({
                            "grupo": grupo, "origem": nome_t, "modelo": m, "grade": nome_gr, "orcamento": f, "k": k,
                            "alertas_alvo": len(tgt), "capturados": float((p * y_alert).sum()),
                            "recall_alertas": float((p * y_alert).sum()) / len(tgt) if len(tgt) else np.nan,
                            "recall_area": float((p * y_area).sum()) / tgt_i["area_km2"].sum() if len(tgt) else np.nan,
                            "recall_celulas": float((p * y_cel).sum()) / y_cel.sum() if y_cel.sum() else np.nan,
                            "precision_celulas": float((p * y_cel).sum()) / k,
                        })
                        pa[f"{m}|{f}"] = np.where(np.isnan(idx_alerta), 0.0,
                                                  p[np.nan_to_num(idx_alerta, nan=0).astype(int)])
                        if f == primario:
                            sel = cel[selecao_deterministica(s, k)]
                            chave_e = (grupo, m)
                            if chave_e in sel_prev:
                                estab.append({"grupo": grupo, "modelo": m, "origem": nome_t,
                                              "jaccard_com_origem_anterior": jaccard(sel, sel_prev[chave_e])})
                            sel_prev[chave_e] = sel
            prob_alertas.append(pa)

    por_origem = pd.DataFrame(linhas)
    por_origem.to_csv(saida / "por_origem.csv", index=False, float_format="%.5f")
    pd.DataFrame(verif).to_csv(saida / "verificacao_area.csv", index=False, float_format="%.5f")
    pd.DataFrame(estab).to_csv(saida / "estabilidade.csv", index=False, float_format="%.4f")
    pa_all = pd.concat(prob_alertas, ignore_index=True)

    agg = (por_origem.groupby(["grupo", "modelo", "orcamento"])
           .agg(origens=("origem", "nunique"), alertas_alvo=("alertas_alvo", "sum"), capturados=("capturados", "sum"),
                recall_medio_origens=("recall_alertas", "mean"), recall_area_medio=("recall_area", "mean"),
                recall_celulas_medio=("recall_celulas", "mean"), precision_celulas_media=("precision_celulas", "mean"))
           .reset_index())
    agg["recall_agregado"] = agg["capturados"] / agg["alertas_alvo"]
    agg.to_csv(saida / "agregado.csv", index=False, float_format="%.5f")

    rng = np.random.default_rng(SEMENTE)
    comps = []
    regra = proto["estatistica"]["regra_de_decisao"]
    for grupo in grupos:
        pg = pa_all[pa_all["grupo"] == grupo]
        for f in fracoes:
            for c in proto["comparacoes"]:
                a, b = f"{c['a']}|{f}", f"{c['b']}|{f}"
                est = (pg[a].sum() - pg[b].sum()) / len(pg)
                reps = bootstrap_diferenca(pg, a, b, rng)
                lo, hi = np.percentile(reps, [2.5, 97.5])
                d_orig = pg.groupby("origem").apply(lambda d: (d[a].sum() - d[b].sum()) / len(d), include_groups=False)
                veredito = "superior" if lo > 0 else ("inferior" if hi < 0 else "inconclusivo")
                comps.append({"grupo": grupo, "orcamento": f, "id": c["id"], "primaria": c["primaria"] and f == primario,
                              "a": c["a"], "b": c["b"], "recall_a": pg[a].sum() / len(pg), "recall_b": pg[b].sum() / len(pg),
                              "diferenca": est, "ic95_inf": lo, "ic95_sup": hi, "veredito": veredito,
                              "origens_positivas": int((d_orig > 0).sum()), "origens": int(len(d_orig)),
                              "diferenca_por_origem": "; ".join(f"{o}: {v:+.3f}" for o, v in d_orig.items()),
                              "alertas_alvo": len(pg), "blocos": int(pg.groupby(["origem", "bloco"]).ngroups)})
    comp = pd.DataFrame(comps)
    comp.to_csv(saida / "comparacoes.csv", index=False, float_format="%.5f")

    execucao.update({"fim_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "bootstrap": {"replicas": N_BOOT, "semente": SEMENTE, "blocos": "origem × quadrado 5 km"},
                     "regra_de_decisao": regra,
                     "versoes": {p: __import__(p).__version__ for p in ("numpy", "pandas", "geopandas", "shapely", "h3")}})
    (saida / "execucao.json").write_text(json.dumps(execucao, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- figuras ---------------------------------------------------------------
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    ordem = ["h3_r7_C", "quadrado_2.5km_C", "h3_r7_A", "quadrado_2.5km_A", "quadrado_5km_A"]
    cores = ["#e07a1f", "#f2b880", "#8c3b00", "#a8763e", "#333333"]
    d = por_origem[por_origem["orcamento"] == primario].pivot(index="origem", columns="modelo", values="recall_alertas")[ordem]
    fig, ax = plt.subplots(figsize=(10, 4))
    d.plot.bar(ax=ax, color=cores, width=0.8)
    ax.set_ylabel(f"Recall@{primario:.0%}")
    ax.set_title(f"Avaliação final ({args.modo}) — recall de alertas por origem, orçamento {primario:.0%}")
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper left", bbox_to_anchor=(0, -0.15))
    plt.setp(ax.get_xticklabels(), rotation=0)
    fig.tight_layout(); fig.savefig(saida / "fig_recall_por_origem.png", dpi=160); plt.close(fig)

    cp = comp[comp["orcamento"] == primario]
    fig, axs = plt.subplots(1, len(grupos), figsize=(6 * len(grupos), 3.8), squeeze=False)
    for ax, grupo in zip(axs[0], grupos):
        x = cp[cp["grupo"] == grupo].iloc[::-1]
        ylab = [f"{r.id}: {r.a} − {r.b}" for r in x.itertuples()]
        ax.errorbar(x["diferenca"], range(len(x)), xerr=[x["diferenca"] - x["ic95_inf"], x["ic95_sup"] - x["diferenca"]],
                    fmt="o", color="#2a6f97", capsize=3)
        ax.axvline(0, color="#999", lw=0.8)
        ax.set_yticks(range(len(x))); ax.set_yticklabels(ylab, fontsize=8)
        ax.set_xlabel(f"diferença de Recall@{primario:.0%} (IC 95%, bootstrap espacial)")
        ax.set_title(f"origens: {grupo}", fontsize=10)
    fig.tight_layout(); fig.savefig(saida / "fig_comparacoes.png", dpi=160); plt.close(fig)

    pd.set_option("display.width", 220)
    print(agg[agg["orcamento"] == primario][["grupo", "modelo", "origens", "alertas_alvo", "recall_agregado", "recall_medio_origens"]].round(3).to_string(index=False))
    print(comp[comp["orcamento"] == primario][["grupo", "id", "a", "b", "diferenca", "ic95_inf", "ic95_sup", "veredito", "origens_positivas", "origens"]].round(3).to_string(index=False))
    v = pd.DataFrame(verif)
    print("razão universo/referência:", v["razao_universo"].dropna().agg(["min", "max"]).round(4).to_dict(),
          "| razão selecionada/orçamento:", v["razao_selecionada"].dropna().agg(["min", "max"]).round(4).to_dict())


if __name__ == "__main__":
    main()
