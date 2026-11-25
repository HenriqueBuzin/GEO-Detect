# Fontes para previsão de alertas de mineração

## Usadas nesta rodada

| Fonte | Papel | Disponibilidade e tratamento |
|---|---|---|
| [INPE / DETER Amazônia](https://terrabrasilis.dpi.inpe.br/downloads/) | Série de alertas de mineração e alvo trimestral | Avisos em floresta. Os atributos usam a data de detecção com intervalo de um mês. O alvo é a presença de alerta por célula. |
| [HydroRIVERS v1.0](https://www.hydrosheds.org/products/hydrorivers) | Distância ao trecho fluvial mais próximo e a trechos de ordem Strahler ≥ 5 | Rede da América do Sul a partir de HydroSHEDS, arquivo distribuído em 2019. Usamos o mesmo retrato em todas as origens. |
| [IBGE / Cadastro de Localidades Selecionadas](https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/cadastro_de_localidades_selecionadas_2010/) | Distância à localidade mais próxima | Cadastro de 2010. A variável aproxima a acessibilidade por distância em linha reta. |

## Fontes candidatas registradas

| Fonte | Possível uso | Condição para inclusão |
|---|---|---|
| [MapBiomas Mineração](https://brasil.mapbiomas.org/iniciativas-e-produtos/cobertura-e-uso-da-terra/mineracao/substancia-minerada/) | Histórico de superfície minerada, garimpo e mineração industrial | Congelar a coleção e usar somente mapas cuja disponibilização preceda o corte. As coleções revisam a série histórica. |
| [Amazon Mining Watch](https://amazonminingwatch.org/en/about) | Inventário complementar de superfície afetada por mineração | Verificar datas e versões dos produtos. Lidar com sobreposição de observações de satélite e avaliar a concordância separadamente. |
| [DNIT / Sistema Nacional de Viação](https://www.gov.br/dnit/pt-br/assuntos/atlas-e-mapas/pnv-e-snv/capa-snv/) | Acessibilidade por rodovias, complementar à distância a rios e localidades | Recuperar a camada vetorial histórica disponível antes do período de treino. |
| [ANM / SIGMINE e SICOP](https://dadosabertos.anm.gov.br/) | Contexto de processos, polígonos e situação na data de interesse | Reconstruir o estado cadastral na data da previsão a partir de registros históricos. Polígonos e fases do cadastro atual não substituem essa reconstrução. |

## Fluxo de extração, transformação e integração

1. Preservar o GeoJSON DETER do Pará com o hash do protocolo.
2. Salvar o ZIP sul-americano de [HydroRIVERS v1.0](https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_sa_shp.zip) em `data/raw/hydrorivers_v10_sa.zip`. Salvar `BR_Localidades_2010_v1.shp` e os arquivos `.dbf`, `.shx` e `.prj` da pasta oficial do IBGE em `data/raw/ibge_localidades_2010/`.
3. Limpar e projetar geometrias no CRS métrico de área equivalente ESRI:102033. Usar os centroides dos alertas para a atribuição às células e os centroides das células para as distâncias a rios e localidades.
4. Em cada origem trimestral, construir a região pontuada e os atributos com os alertas anteriores ao corte. Na LSTM, montar a sequência mensal. Nas árvores, agregar recência, área, sazonalidade e densidade. Juntar as três distâncias estáticas pelo identificador de célula.
5. Ajustar os modelos somente com trimestres-alvo encerrados antes do corte. Pontuar todas as células do universo e avaliar na grade de 1,25 km.
