# Auto Planner: arquitetura de estratégia plugável + estratégia Rolling-Horizon ILP

## Contexto

O Manual Route acabou de fechar uma campanha de fuzz-testing (12.000 cenários, 4 bugs reais corrigidos, ver `docs/2026-08-11-manual-route-fuzz-report.md`). Bruno decidiu seguir para o Auto Planner. Diferente do Manual Route (onde o pedido era "fechar/endurecer o que já existe"), aqui o pedido é **estudar algoritmos alternativos sem se comprometer com um único**: "buscar algoritmos que façam mais sentido pra esse tipo de problema, não quero me apegar a um só... o que for entendido que for mais ajustado, melhor ou mais utilizado".

Hoje `src/railroad_backend/services/auto_planner.py` implementa uma única heurística gulosa (prioriza segmento mais urgente por carga; decide curva/completa por componente; se nada está vencido, espera até o próximo threshold). Essa lógica está embutida direto no loop de execução (`run_auto_plan`/`_perform_next_step`), sem separação entre "decisão" e "execução".

## Objetivo composto (confirmado com Bruno)

Ao decidir a rota automática, a máquina deve equilibrar três coisas, sem uma hierarquia fixa entre elas — os pesos relativos ficam ajustáveis, não fixos no código:

1. **Cobertura**: atender o máximo de trechos garantindo o MTBT (não deixar vencer).
2. **Custo de deslocamento**: minimizar movimentações que não produzem manutenção (dias de deslocamento são pagos).
3. **Aproveitamento de ciclo**: esmerilhar o mais próximo possível do limite de volume de cada segmento, não gastar o recurso de manutenção cedo demais.

Restrição de domínio explícita: **manutenção nunca é interrompida no meio** — uma vez iniciada, executa a duração inteira sem fracionamento.

## Pesquisa: algoritmos reais para essa classe de problema

Não existe literatura publicada especificamente sobre otimização de *rail grinding* (busca acadêmica só retorna física de desgaste/RCF e normas — lacuna real, não limitação de busca). Mas a classe de problema — VRP periódico com deadline por deterioração acumulada, veículo único — é bem estabelecida em inspeção ferroviária, manutenção de frota e manutenção de linha de aeronaves. Fontes reais verificadas (salvas em `SecondBrain/fontes/`):

| Fonte | Algoritmo | Relevância |
|---|---|---|
| Peng, Ouyang, Somani (2013), *J. Rail Transport Planning & Management* — [doi.org/10.1016/j.jrtpm.2014.02.003](https://doi.org/10.1016/j.jrtpm.2014.02.003) | Heurística "incremental horizon" + busca local | **Adotado em produção** numa ferrovia Classe I real (~700 segmentos, ~24 equipes) — prova que essa classe escala pra ferrovia de verdade |
| Van den Bergh et al. (KU Leuven), manutenção de linha de aeronaves — PDF aberto em lirias.kuleuven.be | Rolling-horizon + guloso por urgência | Estrutura quase idêntica ao `auto_planner.py` atual (baseline) |
| Rolling stock maintenance (2024), *Computers & Industrial Engineering* — open access | Rolling-horizon decompõe em ILP sucessivos | Objetivo explícito de agendar o mais próximo possível do deadline — é literalmente o objetivo 3 |
| Younes, Eltawil, Ali (2025), *Logistics* (MDPI) — [doi.org/10.3390/logistics9030120](https://doi.org/10.3390/logistics9030120) | MILP (ótimo, não escala) + Simulated Annealing | Padrão: MILP pra ótimo em janela pequena, metaheurística quando cresce — referência pra evolução futura se o ILP não escalar |
| Nguyen, Do, Iung, Vu (2018), IMA — PDF aberto | LSGA (metaheurística) + Branch & Bound exato | Alternativa híbrida, não escolhida nesta rodada |
| Demirci et al. (2024), *Flexible Services and Manufacturing Journal* — [doi.org/10.1007/s10696-024-09544-y](https://doi.org/10.1007/s10696-024-09544-y) | Whittle index / restless bandit | Pensado pra múltiplas máquinas disputando capacidade — fora de escopo hoje (1 máquina só), candidato natural se o simulador ganhar multi-máquina |

Rede real (`network_20251223_115340.json`): 57 segmentos, 22 estações — porte pequeno-médio, compatível com resolver um MILP/CP por janela (não só heurística).

## Decisão: 2 estratégias nesta rodada, arquitetura pronta para mais

Em vez de escolher "o" algoritmo, a rodada entrega uma arquitetura que permite comparar estratégias lado a lado, com 2 implementações concretas:

1. **`GreedyUrgencyStrategy`** — migração 1:1 da lógica atual (baseline de comparação, sem mudança de comportamento).
2. **`RollingHorizonILPStrategy`** — estratégia nova, candidata principal pra atacar os 3 objetivos ao mesmo tempo.

Metaheurísticas (SA/GA) e restless bandits ficam documentados como próximos candidatos, não implementados agora — decisão explícita de Bruno de não se comprometer, mas também de não implementar tudo de uma vez sem primeiro ver os números dos dois candidatos acima na rede real.

## Arquitetura: `AutoPlanStrategy`

- **Interface** (`src/railroad_backend/services/auto_planner_strategies/base.py`): método central `decide_next_action(sim: Simulator) -> StepDecision`, onde `StepDecision` é uma união de três casos — mover (segmentos + estação destino + ação de manutenção), esperar N dias, ou "sem opção viável".
- `run_auto_plan()` (em `auto_planner.py`) permanece com o mesmo loop (`for` até `steps`/`limit_date`), só troca a chamada direta pra `strategy.decide_next_action(sim)` seguida da execução real via `sim.move_to()`/`sim.wait_days()`/`sim.flip_global_direction()` — a estratégia decide, o loop executa. Isso preserva 100% do comportamento de `AutoPlanResult`, `stop_reason` etc.
- `AutoPlanConfig` ganha `strategy: str` (`"greedy"` | `"rolling_ilp"`, default `"greedy"` — não muda o comportamento de quem já usa o Auto Planner sem tocar em nada novo) e, quando `"rolling_ilp"`, os campos de configuração da janela e dos pesos (ver abaixo).
- `AutoPlanResult` ganha `strategy_name: str` — usado pra rotular runs salvos e na comparação.
- `GreedyUrgencyStrategy` recebe o código hoje solto em `_perform_next_step`/`_move_priority`/`_maintenance_action_for`/`_needs_maintenance`/`_component_due`/`_days_until_next_threshold` (essas últimas duas seguem como funções utilitárias compartilhadas — a projeção de "quando um segmento vence" é útil pras duas estratégias, não só pra Greedy).

## `RollingHorizonILPStrategy`: formulação

O `Simulator` só executa um passo real de cada vez (mover pra estação adjacente ou esperar) — não tem noção de "planejar N dias à frente". A estratégia adiciona uma camada de planejamento que roda a cada replanejamento:

1. **Matriz de deslocamento**: grafo da rede (via `networkx`, já é dependência do projeto) ponderado por `move_time_days` de cada segmento (campo real já usado em `move_to`). Caminho mais curto (Dijkstra) da posição atual até qualquer segmento candidato dentro da janela — pode envolver múltiplos saltos.
2. **Janela de replanejamento**: tamanho configurável (default 60 dias, ajustável na UI). A cada replanejamento, projeta quais segmentos vencem o MTBT dentro da janela usando o `daily_map` real (mesma lógica de projeção já usada em `_days_until_next_threshold`) e monta a lista de candidatos de visita.
3. **Modelo**: **OR-Tools CP-SAT** (constraint programming, grátis, sem licença — escolhido sobre PuLP/CBC porque a função objetivo composta com 3 pesos e a restrição de não-fracionamento de manutenção são mais diretas de expressar em CP do que via MILP puro com big-M). Variáveis: ordem de visita dos candidatos na janela + dia de execução de cada um (bloco atômico, duração fixa = `move_time_days` de deslocamento + duração de manutenção do segmento, sem fracionamento). Função objetivo, com pesos `w_cobertura`, `w_deslocamento`, `w_proximidade` configuráveis na UI (defaults a calibrar durante a validação contra a rede real, não travados de antemão):
   - Penalidade `w_cobertura` por segmento que estouraria o MTBT sem ser atendido dentro da janela.
   - Custo `w_deslocamento` por dia de deslocamento sem produzir manutenção.
   - Bônus `w_proximidade` por executar a manutenção o mais próximo possível do dia em que o segmento venceria (em vez de cedo demais).
4. **Execução real**: resolve o modelo com limite de tempo (default 20s, configurável), extrai a **primeira ação** do plano ótimo/melhor-encontrado, executa via `Simulator` de verdade, e replaneja do zero no próximo passo — a projeção de carga real do dia-a-dia diverge da projeção da janela anterior, então não faz sentido reaproveitar o plano inteiro.
5. **Fallback obrigatório**: se o CP-SAT não retornar nenhuma solução viável dentro do tempo limite, a estratégia cai pro `GreedyUrgencyStrategy` só naquele passo específico — a simulação nunca trava por causa do solver.

## UI e comparação

- Tela "Auto Simulation": seletor de estratégia no formulário (`Greedy (atual)` / `Rolling-horizon ILP`). Quando ILP é escolhido, aparecem os sliders dos 3 pesos + tamanho da janela + limite de tempo do solver.
- `saved_runs`: `config` passa a incluir `strategy` e (quando aplicável) os parâmetros do ILP — sem mudança de schema de persistência, só campos novos no dict já existente.
- Tela "Comparison" (hoje só Auto×Manual): ganha a capacidade de comparar **N runs auto salvos entre si**, reaproveitando a tabela de métricas e os gráficos existentes — a fonte dos dois resultados deixa de ser fixa (auto atual + manual atual) e passa a aceitar seleção de 2+ runs salvos da lista (que já inclui `strategy_name` pra rotular).

## Testes e validação

- TDD para o solver: casos pequenos e determinísticos (ex. 3 segmentos, deadlines conhecidos onde a resposta ótima dá pra calcular na mão) comparando com o que o CP-SAT devolve.
- Teste de fallback: cenário forçado sem solução viável (ou timeout artificial) confirmando que cai pro Greedy sem exceção.
- `GreedyUrgencyStrategy`: testes de regressão garantindo que o comportamento é idêntico ao `_perform_next_step` atual (mesma sequência de decisões pros cenários já cobertos pela suíte existente) — a migração não pode mudar resultado.
- Validação final: rodar as duas estratégias contra a rede real (`network_20251223_115340.json`) e comparar métricas lado a lado (mesmo padrão de fechamento usado no Manual Route) antes de considerar essa rodada pronta.

## Fora de escopo nesta rodada

- Metaheurísticas (Simulated Annealing, Algoritmo Genético) — candidatas registradas na tabela de pesquisa acima, ficam pra depois de ver os números do ILP.
- Whittle index / restless bandit — pensado pra múltiplas máquinas, não se aplica ao simulador de máquina única de hoje.
- Calibração final dos pesos default — fica pra rodada de validação contra a rede real, não travada nesta spec.
