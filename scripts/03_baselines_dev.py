"""Grade de 5 km, universo elegível, variáveis por origem e métodos de referência A/B.

Avaliação SOMENTE no período de desenvolvimento (2024-01 → 2025-06). O período de
teste não é lido para nada além do corte de datas.

Protocolo por origem t (trimestral):
    informação disponível : alertas com view_date < t − GAP (GAP = 1 mês, pois o DETER
                            público não informa a data real de publicação)
    universo elegível U_t : células de 5 km a até 10 km (Chebyshev, 2 células) de
                            alguma célula com alerta disponível
    alvo                  : células de U_t com alerta em [t, t + 3 meses)
    orçamento             : k células (1%, 2%, 5% de |U_t| e k absoluto)

Métodos:
    A_L  quantidade de alertas na célula nos últimos L meses antes do corte
    B_L  área (km²) de alertas na célula nos últimos L meses antes do corte
    L ∈ {3, 12, 24, 60, todo o histórico}
    aleatorio : expectativa analítica k/|U_t|
    oraculo   : limite superior (seleciona as células-alvo)

Empates no ponto de corte são resolvidos pela EXPECTATIVA sob desempate aleatório,
para que o resultado não dependa da ordem das linhas.

Saídas (results/baselines_dev/):
    metricas_por_origem.csv, resumo_por_orcamento.csv, origens.csv,
    parametros_congelados.json, fig_recall_por_k.png, fig_recall_por_origem.png
    data/processed/variaveis_por_origem.csv.gz (variáveis de cada célula elegível)

Uso:
    python scripts/03_baselines_dev.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geodetect.avaliacao import GAP, HORIZONTE, RAIO_UNIVERSO_CEL, ganho_esperado, origens_dev  # noqa: E402
from geodetect.dados import DEV, carregar_preparado  # noqa: E402

JANELAS = {"3m": 3, "12m": 12, "24m": 24, "60m": 60, "tudo": None}
FRACOES = (0.01, 0.02, 0.05)
K_ABS = (25, 50, 100, 200)
ORCAMENTO_SELECAO = "2%"  # orçamento usado para escolher a janela de cada família
CURVA_K = np.unique(np.r_[np.arange(5, 100, 5), np.arange(100, 601, 25)])


def universo(disp: pd.DataFrame) -> pd.DataFrame:
    base = disp[["cel_i", "cel_j"]].drop_duplicates().to_numpy()
    r = np.arange(-RAIO_UNIVERSO_CEL, RAIO_UNIVERSO_CEL + 1)
    di, dj = np.meshgrid(r, r)
    viz = (base[:, None, :] + np.stack([di.ravel(), dj.ravel()], 1)[None, :, :]).reshape(-1, 2)
    u = pd.DataFrame(np.unique(viz, axis=0), columns=["cel_i", "cel_j"])
    u["celula"] = u["cel_i"].astype(str) + "_" + u["cel_j"].astype(str)
    return u


def variaveis(u: pd.DataFrame, disp: pd.DataFrame, corte: pd.Timestamp) -> pd.DataFrame:
    v = u.set_index("celula")[["cel_i", "cel_j"]].copy()
    for nome, meses in JANELAS.items():
        sub = disp if meses is None else disp[disp["view_date"] >= corte - pd.DateOffset(months=meses)]
        agg = sub.groupby("celula").agg(n=("chave", "size"), a=("area_km2", "sum"))
        v[f"A_{nome}"] = agg["n"].reindex(v.index).fillna(0)
        v[f"B_{nome}"] = agg["a"].reindex(v.index).fillna(0.0)
    ultimo = disp.groupby("celula")["view_date"].max().reindex(v.index)
    v["dias_desde_ultimo"] = (corte - ultimo).dt.days
    return v


def avaliar(v: pd.DataFrame, alvo: pd.DataFrame, origem: pd.Timestamp) -> list[dict]:
    n_u = len(v)
    por_cel = alvo.groupby("celula").agg(n=("chave", "size"), a=("area_km2", "sum"))
    dentro = por_cel.index.isin(v.index)
    y_cel = por_cel["n"].reindex(v.index).fillna(0).gt(0).astype(float).to_numpy()
    y_n = por_cel["n"].reindex(v.index).fillna(0).to_numpy()
    y_a = por_cel["a"].reindex(v.index).fillna(0).to_numpy()
    tot_cel, tot_cel_all = y_cel.sum(), len(por_cel)
    tot_n, tot_a = por_cel["n"].sum(), por_cel["a"].sum()

    orc = {f"{int(f*100)}%": max(1, int(round(f * n_u))) for f in FRACOES}
    orc |= {f"k={k}": k for k in K_ABS}

    metodos = {c: v[c].to_numpy(dtype=float) for c in v.columns if c[:2] in ("A_", "B_")}
    linhas = []
    for nome_orc, k in orc.items():
        for m, score in metodos.items():
            h = ganho_esperado(score, y_cel, k)
            linhas.append({
                "metodo": m, "orcamento": nome_orc, "k": k,
                "acertos": h,
                "recall": h / tot_cel if tot_cel else np.nan,
                "recall_total": h / tot_cel_all if tot_cel_all else np.nan,
                "precision": h / k,
                "recall_alertas": ganho_esperado(score, y_n, k) / tot_n if tot_n else np.nan,
                "recall_area": ganho_esperado(score, y_a, k) / tot_a if tot_a else np.nan,
            })
        linhas.append({"metodo": "aleatorio", "orcamento": nome_orc, "k": k,
                       "acertos": k * tot_cel / n_u, "recall": min(1.0, k / n_u),
                       "recall_total": min(1.0, k / n_u) * tot_cel / tot_cel_all if tot_cel_all else np.nan,
                       "precision": tot_cel / n_u, "recall_alertas": min(1.0, k / n_u),
                       "recall_area": min(1.0, k / n_u)})
        h_or = min(k, tot_cel)
        linhas.append({"metodo": "oraculo", "orcamento": nome_orc, "k": k, "acertos": h_or,
                       "recall": h_or / tot_cel if tot_cel else np.nan,
                       "recall_total": h_or / tot_cel_all if tot_cel_all else np.nan,
                       "precision": h_or / k, "recall_alertas": np.nan, "recall_area": np.nan})
    for l in linhas:
        l["origem"] = origem.date().isoformat()
    return linhas


def curva(v: pd.DataFrame, alvo: pd.DataFrame, metodos: list[str]) -> pd.DataFrame:
    y = alvo.groupby("celula").size().reindex(v.index).fillna(0).gt(0).astype(float).to_numpy()
    tot = y.sum()
    linhas = []
    for m in metodos:
        s = v[m].to_numpy(dtype=float)
        for k in CURVA_K:
            linhas.append({"metodo": m, "k": int(k), "recall": ganho_esperado(s, y, int(k)) / tot if tot else np.nan})
    for k in CURVA_K:
        linhas.append({"metodo": "aleatorio", "k": int(k), "recall": min(1.0, k / len(v))})
        linhas.append({"metodo": "oraculo", "k": int(k), "recall": min(1.0, k / tot) if tot else np.nan})
    return pd.DataFrame(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", default="results/baselines_dev", type=Path)
    ap.add_argument("--processados", default="data/processed", type=Path)
    args = ap.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    args.processados.mkdir(parents=True, exist_ok=True)

    g = carregar_preparado()
    fim_dev = pd.Timestamp(DEV[1])
    g = g[g["view_date"] <= fim_dev]  # o teste nunca entra na memória deste script

    metricas, curvas, origens, todas_vars = [], [], [], []
    for t in origens_dev():
        corte = t - GAP
        disp = g[g["view_date"] < corte]
        alvo = g[(g["view_date"] >= t) & (g["view_date"] < t + HORIZONTE)]
        u = universo(disp)
        v = variaveis(u, disp, corte)
        metricas += avaliar(v, alvo, t)
        c = curva(v, alvo, [f"A_{j}" for j in JANELAS] + [f"B_{j}" for j in JANELAS])
        c["origem"] = t.date().isoformat()
        curvas.append(c)
        cel_alvo = set(alvo["celula"])
        origens.append({
            "origem": t.date().isoformat(), "corte_informacao": corte.date().isoformat(),
            "alvo_ate": (t + HORIZONTE - pd.Timedelta(days=1)).date().isoformat(),
            "alertas_disponiveis": len(disp), "celulas_universo": len(v),
            "alertas_alvo": len(alvo), "celulas_alvo": len(cel_alvo),
            "celulas_alvo_no_universo": len(cel_alvo & set(v.index)),
            "celulas_alvo_com_historico": int((v.loc[v.index.isin(cel_alvo), "A_tudo"] > 0).sum()),
        })
        todas_vars.append(v.assign(origem=t.date().isoformat(), alvo=v.index.isin(cel_alvo).astype(int)))

    met = pd.DataFrame(metricas)
    met.to_csv(args.saida / "metricas_por_origem.csv", index=False, float_format="%.4f")
    org = pd.DataFrame(origens)
    org.to_csv(args.saida / "origens.csv", index=False)
    pd.concat(todas_vars).reset_index(names="celula").to_csv(
        args.processados / "variaveis_por_origem.csv.gz", index=False, float_format="%.5f")

    # resumo: média entre origens (macro) e agregado (micro = acertos totais / alvos totais)
    alvos = org.set_index("origem")["celulas_alvo_no_universo"]
    met["alvos"] = met["origem"].map(alvos)
    resumo = (
        met.groupby(["orcamento", "metodo"])
        .apply(lambda d: pd.Series({
            "k_medio": d["k"].mean(),
            "recall_medio": d["recall"].mean(), "recall_dp": d["recall"].std(),
            "recall_min": d["recall"].min(), "recall_max": d["recall"].max(),
            "recall_agregado": d["acertos"].sum() / d["alvos"].sum(),
            "precision_media": d["precision"].mean(),
            "recall_alertas_medio": d["recall_alertas"].mean(),
            "recall_area_medio": d["recall_area"].mean(),
        }), include_groups=False)
        .reset_index()
    )
    resumo.to_csv(args.saida / "resumo_por_orcamento.csv", index=False, float_format="%.4f")

    # escolha da janela de cada família (somente desenvolvimento) → congelada para o teste
    sel = resumo[resumo["orcamento"] == ORCAMENTO_SELECAO]
    congelados = {}
    for fam in ("A", "B"):
        s = sel[sel["metodo"].str.startswith(fam + "_")].sort_values(
            ["recall_medio", "recall_agregado"], ascending=False)
        congelados[fam] = {
            "metodo": s.iloc[0]["metodo"],
            "criterio": f"maior recall médio entre origens de desenvolvimento, orçamento {ORCAMENTO_SELECAO}",
            "recall_medio_dev": round(float(s.iloc[0]["recall_medio"]), 4),
        }
    congelados["protocolo"] = {
        "gap_meses": 1, "horizonte_meses": 3, "raio_universo_km": RAIO_UNIVERSO_CEL * 5,
        "orcamentos": [f"{int(f*100)}%" for f in FRACOES] + [f"k={k}" for k in K_ABS],
        "desempate": "expectativa sob desempate aleatório",
        "origens_dev": [o["origem"] for o in origens],
    }
    (args.saida / "parametros_congelados.json").write_text(
        json.dumps(congelados, indent=2, ensure_ascii=False), encoding="utf-8")

    # figuras
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    cv = pd.concat(curvas).groupby(["metodo", "k"])["recall"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    estilos = {
        congelados["A"]["metodo"]: dict(color="#2a6f97", lw=2.2, label=f"A — {congelados['A']['metodo']}"),
        congelados["B"]["metodo"]: dict(color="#e07a1f", lw=2.2, label=f"B — {congelados['B']['metodo']}"),
        "oraculo": dict(color="#333", lw=1, ls="--", label="oráculo (limite superior)"),
        "aleatorio": dict(color="#9aa5b1", lw=1, ls=":", label="aleatório no universo"),
    }
    for m, d in cv.groupby("metodo"):
        if m in estilos:
            ax.plot(d["k"], d["recall"], **estilos[m])
        else:
            ax.plot(d["k"], d["recall"], color="#c9d1d9", lw=0.8)
    ax.plot([], [], color="#c9d1d9", lw=0.8, label="outras janelas A/B")
    ax.set_xlabel("orçamento k (células de 5×5 km selecionadas)")
    ax.set_ylabel("Recall@k (células com novo alerta)")
    ax.set_ylim(0, 1.02)
    ax.set_title("Métodos de referência — média de 6 origens trimestrais (desenvolvimento)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout(); fig.savefig(args.saida / "fig_recall_por_k.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.8))
    d = met[met["orcamento"] == ORCAMENTO_SELECAO].pivot(index="origem", columns="metodo", values="recall")
    cols = [congelados["A"]["metodo"], congelados["B"]["metodo"], "aleatorio", "oraculo"]
    d[cols].plot.bar(ax=ax, color=["#2a6f97", "#e07a1f", "#9aa5b1", "#333"], width=0.8)
    for i, (o, r) in enumerate(org.set_index("origem")["celulas_alvo_no_universo"].items()):
        ax.text(i, 1.03, f"{r} alvos", ha="center", fontsize=8)
    ax.set_ylim(0, 1.12); ax.set_ylabel(f"Recall@{ORCAMENTO_SELECAO}"); ax.set_xlabel("origem")
    ax.set_title(f"Recall por origem — orçamento {ORCAMENTO_SELECAO} do universo")
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.25))
    plt.xticks(rotation=0)
    fig.tight_layout(); fig.savefig(args.saida / "fig_recall_por_origem.png", dpi=160); plt.close(fig)

    print(org.to_string(index=False))
    print()
    print(resumo[resumo["metodo"].isin(cols + ["A_tudo", "A_12m", "B_tudo"])]
          .pivot(index="metodo", columns="orcamento", values="recall_medio").round(3).to_string())
    print()
    print(json.dumps(congelados, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
