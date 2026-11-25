# Inclusão de fontes espaciais e comparação com a literatura

Definido em 25/11/2026 antes do primeiro ajuste com as fontes auxiliares. A configuração de 1,25 km e a regra de avaliação foram definidas no estudo multiescala. O alvo segue sendo a presença de alertas trimestrais do DETER. A métrica usa o ranking completo.

Acrescentar três variáveis aos atributos históricos: distância ao trecho mais próximo da rede HydroRIVERS v1.0, distância ao trecho de ordem Strahler igual ou superior a 5 mais próximo e distância à localidade mais próxima do cadastro selecionado de 2010 do IBGE. As distâncias são calculadas do centro da célula no mesmo CRS métrico usado pelos alertas. São retratos históricos disponíveis antes do período de treino e podem ter omissões.

Comparar GEO-Detect (Extra Trees, parâmetros já escolhidos) e Random Forest com os mesmos atributos, base, grade, corte, horizonte e métrica. A floresta usa os parâmetros já registrados no script 16 e representa a família usada por Larrea-Gallegos et al. (2023), com proxies de acessibilidade e histórico. É uma adaptação à tarefa DETER, sem reprodução do agrupamento, amostragem, covariáveis completas, alvo ou recorte peruano do artigo. Kanoga et al. e Mayfield et al. entram na discussão metodológica.

Reportar as seis origens de 2024 a junho de 2025, períodos conhecidos do desenvolvimento. Preservar os resultados mesmo que as fontes auxiliares diminuam a AP. A referência interna do GEO-Detect só com DETER já está registrada no experimento multiescala.

## Rede neural recorrente

A pedido do usuário, comparar também uma adaptação da arquitetura de Kanoga et al. (2024), com duas camadas LSTM de 16 unidades, duas camadas densas de 16 e 8 unidades e saída binária. A entrada sequencial consiste em 24 meses de contagem própria e densidade gaussiana de alertas vizinhos (escala de 3 km), com transformação log1p. As três distâncias estáticas entram após a recorrência, normalizadas em log1p de quilômetros e divididas por 5. Usamos as mesmas fontes, o mesmo alvo trimestral, grade e métrica das árvores. A representação temporal, a arquitetura, a amostragem e o treinamento abaixo são adaptações; o artigo original usa previsão mensal de desmatamento.

Treino expansivo desde 2021 com os mesmos cortes das árvores. Cada ajuste inclui todos os positivos e até dez negativos aleatórios por positivo de cada trimestre de treino, com semente 2027 e peso 10 para a classe positiva. Usamos Adam (0,002), lotes de 256 e 12 épocas fixas, sem ajuste pelos trimestres de avaliação. A avaliação usa todas as células do universo, sem amostragem. Os escores são apropriados para ranking. Todos os resultados são reportados independentemente da posição da rede.
