# Literatura e comparação experimental do GEO-Detect

Consulta às fontes primárias em 17 de novembro de 2026. Esta seleção situa o trabalho; não constitui uma revisão sistemática nem demonstra ineditismo mundial.

## Antecedentes relevantes

| Trabalho | Relação com o GEO-Detect | Limite da comparação |
|---|---|---|
| [Larrea-Gallegos et al. (2023)](https://doi.org/10.1016/j.cscee.2023.100353), *A machine learning approach to understand how accessibility influences alluvial gold mining expansion in the Peruvian Amazon* | Random Forest para previsão de expansão da mineração, com variáveis de acessibilidade e histórico. É o antecedente mais próximo desta seleção. | Madre de Dios, outras variáveis e horizontes; ACC, AUC, F1 e recall publicados foram medidos para outra tarefa e outro protocolo. |
| [Kanoga et al. (2024)](https://doi.org/10.1109/IGARSS53475.2024.10642628), *A Recurrent Deep Learning-Based Monthly Deforestation Prediction Model in Eight Areas for Brazilian Amazon: A Pilot Study* — IEEE IGARSS | Rede com duas camadas LSTM, histórico DETER e previsão mensal em células de 1 km. [Código dos autores](https://github.com/aistairc/Recurrent_deep_learning_based_monthly_deforestation_prediction). | O estudo publicado prevê desmatamento mensal. A adaptação ao GEO-Detect usa mineração, horizonte trimestral e fontes geográficas auxiliares. |
| [Mayfield et al. (2020)](https://www.sciencedirect.com/science/article/pii/S1364815219309272), *Considerations for selecting a machine learning technique for predicting deforestation* — Environmental Modelling & Software, Elsevier/ScienceDirect | Estudou uma rede densa com uma camada de 60 unidades, além de outras famílias, para previsão de desmatamento. | Adaptamos a rede densa ao histórico mensal de mineração e às variáveis geográficas disponíveis. |

## Comparação na tarefa GEO-Detect

O GEO-Detect adapta a arquitetura de Kanoga et al. ao histórico trimestral de mineração, complementado por dados geográficos. Nos seis trimestres do Pará, a AP foi de 1,36%. A Random Forest de Larrea-Gallegos et al. adaptada à mesma tarefa obteve 1,29%. A rede densa de Mayfield et al., com uma camada de 60 unidades e entrada mensal achatada, obteve 1,14%. Os números foram medidos neste estudo. A comparação com os resultados originais é metodológica, porque as tarefas, dados e métricas diferem.

- [Protocolo das redes](../../results/redes_temporais/PLANO.md)
- [Resultados por trimestre](../../results/redes_temporais/por_origem.csv)
- [Relatório da comparação](../../results/redes_temporais/RELATORIO.md)
