# GEO-Detect

**GEO-Detect: uma rede neural para previsão espacial de alertas de mineração na Amazônia**

O projeto prevê onde o DETER pode registrar alertas de mineração no trimestre seguinte. No estudo retrospectivo do Pará, a LSTM usa 24 meses de alertas e três atributos geográficos de hidrografia e localidades. A comparação usa métodos da literatura adaptados à mesma tarefa e mede a precisão média no ranking completo.

## Artigo e materiais

| Material | Arquivo |
|---|---|
| Artigo completo, formato IEEE | [PDF](output/pdf/artigo_ieee.pdf) · [LaTeX](submissao/geomrit2027/artigo_ieee.tex) |
| Resumo expandido da GEOMRIT | [PDF A4](output/pdf/resumo_expandido.pdf) · [Texto editável](submissao/geomrit2027/resumo_expandido.md) |
| Pôster preliminar da GEOMRIT | [PDF](output/pdf/poster_preliminar.pdf) |
| Plano e trabalhos relacionados | [Plano](submissao/geomrit2027/PLANO_PESQUISA.md) · [Literatura](submissao/geomrit2027/trabalhos_relacionados.md) |

## Organização

| Pasta | Conteúdo |
|---|---|
| [`data/`](data/README.md) | Extração congelada do DETER, metadados, fontes auxiliares e uso dos dados |
| [`geodetect/`](geodetect/) | Preparação geoespacial, grade, cortes temporais e métricas |
| [`scripts/`](scripts/README.md) | Aquisição, processamento, treino, avaliação e figura |
| [`results/`](results/redes_temporais/RELATORIO.md) | Resultados por trimestre, figura e registro metodológico |
| [`reproducao/`](reproducao/README.md) | Ambiente fixado, hashes das fontes e resultados esperados |
| [`submissao/geomrit2027/`](submissao/geomrit2027/README.md) | Fontes dos documentos e instruções de geração |
| [`output/`](output/) | PDFs científicos e pacote de reprodução |

## Reproduzir a comparação

Use o [pacote ZIP](output/reproducao/geodetect-reproducao.zip) ou clone este repositório. Em macOS/arm64, usamos Python 3.15.2 e CPU. A partir da raiz:

```sh
python3.15 -m venv .venv
.venv/bin/python -m pip install -r reproducao/requirements.txt
.venv/bin/python scripts/reproduzir_artigo.py
```

O programa verifica a extração congelada, obtém o HydroRIVERS e o IBGE dos provedores oficiais, recalcula as métricas e compara os 18 resultados modelo-trimestre com a referência. O [guia de reprodução](reproducao/README.md) lista entradas, saídas e verificações.

A LSTM obteve AP de **1,36%** nos seis trimestres. A Random Forest adaptada de Larrea-Gallegos et al. obteve **1,29%** e a rede densa adaptada de Mayfield et al. obteve **1,14%**. Os números foram medidos no protocolo GEO-Detect. [Relatório da comparação](results/redes_temporais/RELATORIO.md)

## Citação e licença

Para citar o código e o pacote experimental, use [CITATION.cff](CITATION.cff). O código usa a licença do [repositório](LICENSE), e os dados seguem os termos das respectivas fontes, indicados na [documentação de dados](data/README.md).
