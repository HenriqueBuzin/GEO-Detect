# Redes de Kanoga e Mayfield aplicadas aos alertas DETER

Revisado em 25/11/2026 antes dos ajustes das duas redes nesta execução. O experimento anterior com arquiteturas adicionais foi interrompido a pedido do usuário. A referência é a literatura já citada no manuscrito.

Testamos a rede densa de uma camada oculta de 60 unidades inspirada em Mayfield et al. (2020, DOI 10.1016/j.envsoft.2020.104741). Comparamos com a LSTM adaptada de Kanoga et al. (2024, DOI 10.1109/IGARSS53475.2024.10642628). A rede densa recebe as mesmas duas séries de 24 meses, achatadas, e as mesmas três distâncias geográficas. Ambos os métodos usam DETER, HydroRIVERS e IBGE. O alvo, grade de 1,25 km, janelas de treino, amostragem, otimizador, épocas e precisão média (AP) seguem o protocolo local da LSTM. Usamos a topologia densa do artigo de Mayfield, com dados, alvo e esquema de treino adaptados à tarefa local.

Reportamos os seis trimestres de 2024 a junho de 2025. A reprodução da LSTM anterior nessas seis origens é verificada com tolerância de 1e-7. A avaliação também informa a AP dentro de células com e sem alerta DETER anterior ao corte. Grupos usam todo o histórico disponível. A AP do grupo multiplica a precisão média na região pontuada pela fração de células positivas que estavam nessa região.
