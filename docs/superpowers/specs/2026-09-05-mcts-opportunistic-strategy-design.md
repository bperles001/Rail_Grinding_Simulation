# Auto Planner: estratégia MCTS com agrupamento oportunista de manutenção

## Contexto

Depois de implementar e comparar três estratégias (`GreedyUrgencyStrategy`, `RollingHorizonILPStrategy` via CP-SAT, `SimulatedAnnealingStrategy`), a comparação contra 5 planos manuais reais do Bruno (replay no simulador + 4 planilhas históricas de anos anteriores) mostrou uma lacuna consistente e grande: o especialista humano gasta **81-93% do tempo em manutenção real**, contra **65-71%** das três estratégias automáticas. A causa identificada (análise passo a passo dos planos reais): o humano consistentemente aproveita o deslocamento pra manter trechos que estão no caminho, mesmo não sendo os mais criticamente vencidos - um padrão que nenhuma das três estratégias atuais modela, porque todas decidem "qual é o trecho mais urgente agora" isoladamente a cada passo/janela, sem noção de "já que vou passar por ali, aproveito".

Pesquisa real (13 fontes verificadas) confirmou duas técnicas de pesquisa operacional que, juntas, endereçam essa lacuna:
- **Opportunistic Maintenance Grouping**: agrupar manutenção de itens próximos ao limite quando o recurso já está no local por outro motivo. Caso real documentado (Ribeiro & Cabral Seixas Costa, 2025, distribuidora de energia): -44,4% de paradas programadas, -25,5% de downtime total.
- **Monte Carlo Tree Search (MCTS) / Pilot method / rollout algorithms**: simular jogadas futuras antes de decidir a próxima - técnica estabelecida (Runarsson/Schoenauer/Sebag 2012), já aplicada com sucesso documentado a VRP e roteamento de frota em escala real (até 1000 veículos, MCTS+MILP híbrido pra UAS Traffic Management da FAA). Nenhuma fonte encontrada combina as duas técnicas - é uma lacuna real da literatura, não algo já resolvido em algum lugar que estaríamos reinventando.

Confirmado com o Bruno: quer a versão mais sofisticada de MCTS (árvore real com UCB1, não o Pilot method simplificado), com bônus explícito de agrupamento oportunista na função de avaliação, orçamento de tempo intermediário por decisão (~10s).

## Objetivo

Uma quarta estratégia (`MCTSStrategy`) que decide um movimento real de cada vez simulando o futuro antes de escolher, com viés estrutural pra aproveitar deslocamentos e manter trechos próximos do limite mesmo sem estarem oficialmente vencidos - fechando a lacuna medida contra os planos manuais reais.

## Arquitetura

`MCTSStrategy` implementa `AutoPlanStrategy` diretamente (`decide_next_action(sim) -> StepDecision`) - **não** herda de `CommittedWindowStrategy`. A lógica de "resolver uma janela e seguir o plano em cache" (o que `CommittedWindowStrategy` faz pro ILP/SA) não se aplica aqui: o MCTS já reavalia a cada passo real por natureza, de um jeito muito mais informado que o replanejamento ingênuo que motivou o `CommittedWindowStrategy` originalmente (aquele problema era especificamente do replanejamento sem memória nenhuma entre passos - o MCTS tem o oposto disso).

**Reaproveitamento de árvore entre passos reais**: depois de escolher e executar um movimento real, a sub-árvore correspondente àquele movimento vira a raiz da próxima busca (técnica padrão em motores de jogo) - evita descartar simulações já feitas.

Módulo novo: `src/railroad_backend/services/auto_planner_strategies/mcts.py` (mecânica de busca + nó da árvore) e `mcts_strategy.py` (`MCTSStrategy`, a classe pública registrada no `STRATEGY_REGISTRY`).

## Mecânica do MCTS

Cada nó da árvore representa um estado simulado: posição, direção, cargas MTBT de todos os segmentos, e data simulada. Quatro fases por simulação, repetidas até o orçamento de tempo (10s, constante interna, não exposta em UI) esgotar:

1. **Seleção**: desce da raiz escolhendo em cada nó o filho que maximiza UCB1 = `valor_médio + C * sqrt(ln(visitas_pai) / visitas_filho)`. `C` é constante interna calibrada durante a validação (ponto de partida: `sqrt(2)`, valor clássico da literatura de bandits, ajustável se a validação de campo mostrar convergência ruim).
2. **Expansão**: ao chegar num nó com movimentos reais ainda não representados (via `sim.get_possible_moves()`/`get_all_moves_any_direction()`, os mesmos métodos reais já usados pelo resto do sistema - nunca uma reimplementação paralela, mesmo princípio já estabelecido pro `travel_graph.py`), cria um filho novo pra um desses movimentos.
3. **Rollout**: a partir do nó novo, simula uma sequência de passos futuros (até um limite de profundidade em dias simulados, constante interna, ponto de partida 30-60 dias) usando uma heurística rápida com viés de agrupamento oportunista (próxima seção) - não é busca exaustiva, é uma estimativa barata de "que futuro esse ramo tende a produzir".
4. **Retropropagação**: o resultado da função de avaliação (seção seguinte) atualiza a média de valor de todos os nós no caminho da raiz até o nó expandido.

Ao esgotar o orçamento, `decide_next_action` retorna o movimento real correspondente ao filho da raiz **mais visitado** (padrão MCTS - mais robusto que "maior valor médio" quando a busca é ruidosa/incompleta).

**Clonagem de estado pra simulação**: cada simulação (rollout) precisa de um clone do `Simulator` que não afete o real. `copy.deepcopy` ingênuo do `Simulator` inteiro é um risco de desempenho real (a topologia da rede - `Segment`/`Station` com referências circulares - não muda entre simulações, só o estado mutável muda: cargas dos segmentos, posição/direção da máquina, data). **Validar o custo de clonagem é a primeira tarefa técnica do plano de implementação**, antes de escrever o MCTS em si - se `deepcopy` ingênuo não permitir centenas de simulações em 10s, a solução é um clone leve que copia só o estado mutável e referencia a topologia fixa compartilhada.

## Agrupamento oportunista

Entra em dois pontos:

**1. Política de rollout**: a simulação rápida usada dentro de cada rollout não usa `GreedyUrgencyStrategy` sem modificação (que só mantém trechos oficialmente vencidos via `needs_maintenance`/`component_due`, ambos em `greedy.py`). Uma variante nova (`_opportunistic_rollout_policy` ou similar, dentro de `mcts.py`) adiciona: **se o movimento real já escolhido cruza um segmento cuja carga está acima de um limiar de proximidade** (constante interna, ponto de partida 0.7 - 70% do limite MTBT de cada componente, curva/tangente independentes, mesmo padrão de `_severity_if_due` em `horizon.py`), mantém esse segmento também, mesmo sem estar tecnicamente vencido. Sem isso, o rollout nunca descobriria que agrupar é melhor, porque a política de simulação nunca agruparia pra começo de conversa.

**2. Função de avaliação (reward)**: reaproveita os 3 fatores já usados no ILP/SA (cobertura, deslocamento, proximidade do limite - todos ponderados por gravidade, mesmo campo `DueCandidate.severity` de `horizon.py`), **mais um termo bônus novo**: para cada segmento mantido oportunisticamente durante o rollout (mantido acima do limiar de proximidade mas sem estar tecnicamente vencido), soma um bônus proporcional a quanto aproveitou um deslocamento que já ia acontecer por outro motivo - maior quando a manutenção acontece durante um movimento que seria feito de qualquer forma, menor/zero se o único propósito do deslocamento fosse chegar especificamente nesse segmento. Constante de peso interna, calibrável na validação.

**3. Execução real**: ao traduzir a raiz-filho escolhida em `StepDecision`, a ação (manter/curva/completa/só mover) usa a mesma regra de proximidade do rollout, não a checagem binária estrita de `needs_maintenance` que o resto do sistema usa hoje - o comportamento real precisa ser consistente com o que a árvore avaliou.

## Configuração

Todos os parâmetros (orçamento de tempo, `C` do UCB1, profundidade de rollout, limiar de proximidade, peso do bônus oportunista) são **constantes internas do módulo `mcts.py`/`MCTSStrategy`, não expostas em nenhuma UI ou config pública** - mesmo padrão já estabelecido pro `SimulatedAnnealingStrategy` (iterações/temperatura/resfriamento também são internos). `AutoPlanConfig`/`run_auto_plan_from_args` ganham só `strategy="mcts"` no registro (`STRATEGY_REGISTRY["mcts"] = MCTSStrategy`), sem novos campos de configuração pública.

## Testes

- **Mecânica MCTS determinística**: cenários pequenos (2-3 estações, mesmo padrão de fixtures já usado no ILP/SA) onde a melhor sequência de jogadas é calculável na mão - confirma que o MCTS converge pra ela com um orçamento de simulações fixo (usar contagem de simulações como orçamento nos testes, não tempo de parede, pra determinismo).
- **Limiar de proximidade / agrupamento**: cenário onde um segmento perto do limite (mas não vencido) fica no caminho de um movimento já necessário por outro motivo - confirma que a política de rollout e a execução real mantêm esse segmento; um segmento na mesma condição mas fora do caminho não deve ser perseguido à toa (nenhum movimento extra só pra alcançá-lo).
- **Validação de desempenho** (primeira tarefa do plano, antes do MCTS em si): medir tempo real de clonagem do `Simulator` e de um rollout completo, confirmando quantas simulações cabem em 10s na rede real (57 segmentos) - define se o clone ingênuo (`copy.deepcopy`) serve ou se precisa de um clone leve dedicado.
- **Validação de campo**: reexecutar o diagnóstico de 40 passos contra a rede real (mesmo usado pra achar os bugs de oscilação nas rodadas anteriores) e comparar visualmente o comportamento com Greedy/ILP/SA.
- **Comparação final**: rodar o MCTS no mesmo script de estudo (`scripts/compare_auto_strategies.py`) contra Greedy/ILP/SA **e contra o replay do plano manual real** (mesma base ZTO→ZCZ/2026/2º KLD já usada nas comparações anteriores) - essa é a régua que importa, já que foi o manual que expôs a lacuna que esta estratégia tenta fechar.

## Fora de escopo

- Qualquer mudança de UI - mesmo padrão da rodada anterior (histerese/SA), sem exposição de parâmetros novos.
- Rede neural de política/valor (estilo AlphaZero) - o MCTS aqui usa rollout com heurística fixa, não uma política aprendida. Considerar só se a validação mostrar que o rollout heurístico não converge bem o suficiente.
- Paralelização das simulações MCTS (rodar múltiplos rollouts em threads/processos separados) - otimização de desempenho a considerar depois, se o orçamento de 10s se mostrar insuficiente mesmo com clone leve.
