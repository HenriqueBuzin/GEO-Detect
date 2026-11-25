# Plano científico do GEO-Detect

Revisão de 25/11/2026. Previsão espacial de alertas de mineração na Amazônia, com estudo no Pará e avaliação de transferência geográfica da versão com histórico DETER.

## Pergunta e dados

Como prever se uma célula terá pelo menos um alerta de mineração do DETER no próximo trimestre? O DETER fornece a série temporal e o alvo. Usamos também a rede hidrográfica HydroRIVERS v1.0 e o cadastro histórico de localidades do IBGE (2010). A extração, o tratamento e a integração espacial estão descritos no [registro das fontes](../../results/multiescala/FONTES.md).

## Experimento

Células quadradas de 1,25 km. Os preditores são construídos com dados anteriores ao corte, um mês antes do trimestre. O treino é expansivo desde 2021. A precisão média (AP) resume o ranking completo a cada trimestre. O denominador de recall inclui células positivas fora da região pontuada. Resultados no Pará cobrem seis trimestres de janeiro de 2024 a junho de 2025, já examinados durante o desenvolvimento.

O GEO-Detect usa uma LSTM inspirada em Kanoga et al. (2024), com 24 meses de histórico próprio e de vizinhança e três distâncias geográficas. A comparação científica inclui a Random Forest adaptada de Larrea-Gallegos et al. (2023) e a rede densa adaptada de Mayfield et al. (2020). Os modelos recebem as mesmas fontes, alvo, divisões temporais e métrica, com representações adequadas às arquiteturas.

Os artigos publicaram resultados para outros alvos, recortes e métricas. A avaliação numérica testa as adaptações no mesmo protocolo local. A validação temporal independente exige novos períodos completos e uma configuração congelada.

- [Plano da comparação com fontes auxiliares e LSTM](../../results/multiescala/PLANO_BASES.md)
- [Resultados e reprodução](../../results/redes_temporais/RELATORIO.md)
- [Protocolo da rede densa de Mayfield](../../results/redes_temporais/PLANO.md)
