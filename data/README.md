# Dados e proveniência

| Fonte | Arquivo e função |
|---|---|
| DETER Amazônia, INPE/TerraBrasilis | [GeoJSON congelado](raw/deter_amz_mineracao_pa.geojson), com classe Mineração e UF Pará. Fornece o histórico e os alertas usados como alvo. A extração de 10/11/2026 contém 6.770 registros brutos. [Metadados da extração](raw/download_metadata.json). |
| HydroRIVERS v1.0 | Camada vetorial sul-americana. Fornece as distâncias a rios e a trechos de ordem Strahler 5 ou maior. O script obtém o ZIP no distribuidor oficial. [Fonte e termos](https://www.hydrosheds.org/products/hydrorivers). |
| IBGE, Cadastro de Localidades Selecionadas de 2010 | Arquivos vetoriais de localidades. Fornecem a distância ao ponto cadastrado mais próximo. O script os obtém no distribuidor oficial. [Fonte](https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/cadastro_de_localidades_selecionadas_2010/). |

O código verifica os hashes no [manifesto das fontes auxiliares](../reproducao/fontes_auxiliares.json). A cópia do DETER é atribuída a **INPE/DETER Amazônia, TerraBrasilis**. O INPE indica licença [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) para os dados do DETER. [Página do programa](https://www.obt.inpe.br/OBT/assuntos/programas/amazonia/deter/deter).

A etapa de transformação corrige geometrias, remove polígonos abaixo de 0,1 hectare, projeta os dados em ESRI:102033 e atribui cada alerta a uma célula pelo centroide. Em cada trimestre, as séries mensais e as três distâncias geográficas são unidas pelo identificador da célula. Consulte [Dados e método](../output/pdf/artigo_ieee.pdf) e o [guia de reprodução](../reproducao/README.md).
