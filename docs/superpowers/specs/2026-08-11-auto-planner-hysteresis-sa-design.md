# Auto Planner: histerese entre replanejamentos + estratégia Simulated Annealing (estudo comparativo, sem UI)

## Contexto

Depois de fechar a arquitetura de estratégia plugável (`GreedyUrgencyStrategy` + `RollingHorizonILPStrategy`, ver spec/plano de 2026-08-11 anteriores) e corrigir 2 bugs reais no ILP (penalidade de atraso ausente; manutenção pulada ao passar por trecho vencido fora do alvo modelado), Bruno testou a versão corrigida e aprovou. Pediu explicitamente pra seguir com um estudo mais amplo de algoritmos antes de comprometer com um só, citando pesquisa operacional (gatilhos + tempo de deslocamento + chegar no lugar certo na hora certa) como referência.

Pesquisa real feita (12 fontes novas verificadas, salvas em `SecondBrain/fontes/`, somando 20 no total desta linha) identificou:
- A oscilação residual do ILP (máquina fica indo e voltando entre 2 estações já atendidas) é um fenômeno conhecido na literatura de rolling-horizon/MRP, chamado **"nervousness"** (Jensen 1993; Heisig 2002; Kimms 1997) - causado por replanejar do zero a cada passo real, sem memória do plano anterior.
- Técnica mais aplicável encontrada: Tamar et al. (2016, MPC/robótica) - entre execuções reais, mantém um plano de horizonte mais longo e só o refaz quando necessário, em vez de reotimizar cego a cada passo.
- GRASP (metaheurística) bateu MILP exato em qualidade e tempo num VRP com prioridade/atraso (Jaikishan/Patil 2019) - evidência real de que metaheurística pode competir com o solver exato nesse tipo de problema.
- Reinforcement Learning para manutenção preventiva aparece, nas fontes verificadas, como majoritariamente experimental - sem relato de implantação real. **Descartado desta rodada** por falta de evidência de ganho prático.

## Decisões de escopo (confirmadas com Bruno)

1. **Sem mudança de UI nesta rodada.** O objetivo é testar os algoritmos de verdade, olhar os planos gerados e o comportamento, e só depois decidir se algo vale a pena virar UI/produção. "Não quero mais botões e configurações no nosso UI."
2. **Entrega: script(s) + relatório dos planos gerados.** Evolução do `scripts/compare_auto_strategies.py` já existente, rodando as estratégias e escrevendo um relatório (markdown) com o passo a passo e as métricas de cada combinação, para revisão humana.
3. **2 candidatos novos a implementar**: (a) mecanismo de histerese/compromisso entre replanejamentos, aplicado ao `RollingHorizonILPStrategy`; (b) `SimulatedAnnealingStrategy` nova, usando o mesmo objetivo (cobertura/deslocamento/proximidade) e os mesmos blocos (`project_due_candidates`, `build_travel_graph`), só trocando o motor de busca.
4. **Horizonte de projeção vira parâmetro de estudo**, não mais um valor fixo de UI: testar 60/90/120/180 dias em cada estratégia baseada em janela, para entender se "enxergar mais meses à frente" (pedido explícito do Bruno: "o algoritmo sempre tem que olhar para o futuro, avaliando como vai se comportar o volume de cada trecho nos meses subsequentes") melhora a qualidade da rota ou só deixa o solver mais lento sem ganho real.
5. **Configuração compartilhada, não duplicada por algoritmo**: os 3 pesos (cobertura/deslocamento/proximidade) e o horizonte de janela passam a ser conceitos únicos, usados tanto pelo ILP quanto pela nova estratégia SA - evita crescer a superfície de configuração por algoritmo (coerente com o pedido de não multiplicar "botões").

## Arquitetura: base de compromisso compartilhada

Hoje `RollingHorizonILPStrategy.decide_next_action()` resolve o modelo do zero a cada passo real. Isso causa "nervousness" (oscilação) quando duas rotas ficam com custo muito próximo entre replanejamentos sucessivos.

**`CommittedWindowStrategy`** (nova classe base, em `auto_planner_strategies/committed_window.py`): encapsula o ciclo de "resolver uma vez, executar o plano até invalidar":

- Estado interno: `self._cached_plan: Optional[WindowPlan]` (o plano de janela em execução) e `self._cached_candidate_names: Set[str]` (quais candidatos existiam quando o plano foi calculado).
- `decide_next_action(sim)`:
  1. Recalcula `project_due_candidates(sim, self.window_days)` (operação barata, sempre feita).
  2. **Invalida o cache** se: (a) não há plano em cache; (b) o plano em cache já foi totalmente executado (todas as paradas atendidas); (c) existe um candidato **já vencido agora** (`days_until_due == 0`) que não estava no conjunto de candidatos quando o plano foi calculado (válvula de segurança - não pode ficar cego a um trecho que vence no meio da execução de um plano longo).
  3. Se o cache foi invalidado: chama `self._solve_window(candidates, graph, ...)` (método abstrato, implementado por cada estratégia concreta - CP-SAT ou SA), guarda o plano novo e o conjunto de candidatos usados.
  4. Traduz a **primeira parada ainda não atendida** do plano em cache para um passo real (mesma lógica de `_next_real_move_toward` que já existe - maintém sempre que o segmento sendo atravessado está vencido, independente de ser a parada modelada ou não).
  5. Quando uma parada do plano em cache é fisicamente alcançada/atendida, remove da lista (não recalcula o resto do plano).
- `RollingHorizonILPStrategy` e `SimulatedAnnealingStrategy` passam a herdar de `CommittedWindowStrategy`, cada uma só implementando `_solve_window(...)` (chamando `rolling_ilp.solve_window` ou a função SA nova).

## `SimulatedAnnealingStrategy`: como decide

Novo módulo `auto_planner_strategies/simulated_annealing.py`, função `solve_window_sa(candidates, graph, start_station, *, weight_coverage, weight_travel, weight_proximity, iterations=2000, initial_temperature=100.0, cooling_rate=0.995) -> WindowPlan` (mesmo tipo de retorno que `rolling_ilp.solve_window`, para plugar na mesma base de compromisso sem duplicar lógica de execução):

1. **Solução inicial**: ordena os candidatos alcançáveis por `days_until_due` (mais vencido primeiro) - mesmo critério que o Greedy já usa, serve de ponto de partida razoável.
2. **Avaliação de custo de uma ordem**: percorre a sequência simulando chegada (soma `shortest_travel_days` entre paradas consecutivas), calculando o mesmo custo do ILP - atraso (`lateness`) e folga (`earliness`) ponderados por `weight_coverage`/`weight_proximity`, deslocamento total ponderado por `weight_travel`. Reaproveita a mesma fórmula, não uma função nova e divergente.
3. **Busca**: a cada iteração, troca a posição de 2 candidatos na sequência (vizinhança clássica de troca), recalcula o custo; aceita se melhorou, ou aceita mesmo piorando com probabilidade `exp(-Δcusto / temperatura)` (critério de Metropolis); multiplica a temperatura por `cooling_rate` a cada iteração. Guarda a melhor sequência já vista.
4. `iterations`/`initial_temperature`/`cooling_rate` são constantes internas do algoritmo (não expostas em nenhuma UI ou config pública) - controlam só o comportamento de busca, sem equivalente físico no domínio.
5. **Estocasticidade**: diferente do CP-SAT (que tende a devolver o mesmo plano pra mesma entrada), o SA pode devolver planos ligeiramente diferentes entre execuções. O script de comparação roda cada combinação **N vezes com seeds diferentes** (não só uma) e reporta a variação, não só um número único.

## Refatoração de config (sem crescer a superfície)

`AutoPlanConfig` ganha campos genéricos (renomeando os atuais `ilp_*` para não ficarem amarrados a um único algoritmo): `planning_window_days`, `weight_coverage`, `weight_travel`, `weight_proximity`, `solver_time_limit_s` (usado só pelo CP-SAT; SA ignora, usa `iterations` fixo internamente). `strategy` ganha o valor novo `"simulated_annealing"` no registro. Nenhum desses campos é exposto em `auto_simulation.py`/UI - continuam existindo só como parâmetros de função, usados pelo script de estudo.

## Script de comparação e relatório

`scripts/compare_auto_strategies.py` evolui para:
- Rodar as 3 estratégias (`greedy`, `rolling_ilp`, `simulated_annealing`) × 4 horizontes (60/90/120/180 dias, os 2 últimos não afetam o Greedy - registrar isso no relatório) contra a rede real.
- Pra `simulated_annealing`, rodar 3 sementes diferentes por combinação e reportar min/média/max das métricas.
- Gerar um relatório markdown (`docs/2026-08-11-auto-planner-algorithm-comparison.md` ou nome com a data real de execução) com: tabela de métricas por combinação (dias totais, deslocamento, manutenção, contagem de ações, segmentos ainda acima do limite ao final), e um trecho do log passo a passo (primeiros ~40 passos, como o diagnóstico usado para achar os 2 bugs) de cada estratégia no horizonte padrão (90 dias), para inspeção visual do comportamento.

## Testes

- `CommittedWindowStrategy`: TDD cobrindo (1) plano em cache é executado sem novo replanejamento enquanto válido; (2) plano é invalidado e recalculado quando esgotado; (3) plano é invalidado quando surge candidato novo já vencido não coberto pelo plano em cache.
- `solve_window_sa`: TDD com o mesmo cenário determinístico já usado para o CP-SAT (`test_solve_window_prioritizes_already_due_candidate_over_cheaper_route` adaptado) - mesmo com busca estocástica, o SA deve convergir pra visitar o trecho já vencido primeiro dado peso suficiente, testável com uma seed fixa.
- Regressão completa da suíte após cada mudança (zero regressão é o padrão já estabelecido nesta sessão).
- Validação final: rodar o script de comparação e revisar o relatório junto com o Bruno antes de considerar essa rodada fechada - decisão de qual (se algum) vira UI/produção fica pra depois dessa revisão.

## Fora de escopo desta rodada

- Qualquer mudança de UI (`auto_simulation.py`, `comparison.py`) - script e relatório são a entrega.
- GRASP e outras metaheurísticas além do SA - candidatos futuros, não implementados agora.
- Reinforcement Learning - descartado por falta de evidência de ganho prático nas fontes pesquisadas.
- A programação manual de 2026 que o Bruno está fazendo em paralelo, e a comparação Manual × Automático que vai usar esse material - fica para quando ele terminar.
