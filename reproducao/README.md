# Reprodução dos resultados do artigo

Este pacote reproduz a figura de precisão média do artigo e a comparação do GEO-Detect com as duas referências adaptadas da literatura. As três abordagens usam os mesmos seis trimestres de 2024 a junho de 2025. A avaliação é retrospectiva.

## Ambiente e execução

A execução de referência usou Python 3.15.2 em macOS/arm64, com processamento em CPU. As versões das bibliotecas, inclusive dependências transitivas, estão em `reproducao/requirements.txt`. Da raiz da pasta extraída:

```sh
python3.15 -m venv .venv
.venv/bin/python -m pip install -r reproducao/requirements.txt
.venv/bin/python scripts/reproduzir_artigo.py
```

A execução completa pode levar vários minutos. O script confirma o hash do GeoJSON congelado do DETER, baixa o ZIP HydroRIVERS e os quatro arquivos vetoriais do IBGE dos provedores oficiais, verifica os hashes e executa os scripts 23, 24 e 25. Por fim, confere os CSVs com os resultados de referência e gera `results/poster/fig_precisao_alertas.png`. A verificação exige as mesmas contagens e diferença máxima de 0,0000001 na AP por modelo e trimestre. Diferenças de plataforma ou bibliotecas nativas podem afetar a validação numérica.

Para conferir as entradas antes de instalar as bibliotecas de aprendizado de máquina, execute `python3.15 scripts/reproduzir_artigo.py --verificar-fontes`. Para verificar uma execução já salva, use `python3.15 scripts/reproduzir_artigo.py --conferir-resultados`.

## Entradas e direitos de uso

- **DETER/INPE.** Este pacote inclui a extração de 10/11/2026 da camada DETER Amazônia em floresta, com classe Mineração e UF Pará. A base pública é atualizada ao longo do tempo. A cópia congelada e o hash em `data/raw/download_metadata.json` mantêm a entrada idêntica à do estudo. Fonte e atribuição: [INPE / TerraBrasilis](https://terrabrasilis.dpi.inpe.br/downloads/). [Licença indicada pelo INPE para o DETER](https://www.obt.inpe.br/OBT/assuntos/programas/amazonia/deter/deter).
- **HydroRIVERS v1.0 e IBGE 2010.** Os endereços oficiais e hashes constam em `reproducao/fontes_auxiliares.json`. O script obtém esses arquivos diretamente dos provedores. Se houver arquivo local com hash diferente, o script interrompe a execução e informa o caminho. Fontes: [HydroRIVERS e seus termos](https://www.hydrosheds.org/products/hydrorivers) e [Cadastro de Localidades Selecionadas 2010](https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/cadastro_de_localidades_selecionadas_2010/).

## Saídas

| Arquivo | Conteúdo |
|---|---|
| `results/multiescala/bases_por_origem.csv` | Resultados da Random Forest e do Extra Trees utilizado no desenvolvimento |
| `results/multiescala/lstm_por_origem.csv` | Resultados da LSTM por trimestre |
| `results/redes_temporais/por_origem.csv` | Resultados da LSTM e da rede densa de Mayfield |
| `results/redes_temporais/por_historico.csv` | Diagnóstico por histórico |
| `results/poster/fig_precisao_alertas.png` | Gráfico publicado no artigo |

O CSV `results/multiescala/por_origem.csv` acompanha o pacote para que os scripts confirmem os universos e as contagens por trimestre. O CSV `reproducao/resultados_esperados.csv` contém as 18 linhas da comparação principal para checagem ao final do treino.

Para compilar o artigo IEEE após reproduzir a figura, use Tectonic:

```sh
mkdir -p output/pdf
tectonic --outdir "$(pwd)/output/pdf" submissao/geomrit2027/artigo_ieee.tex
```
