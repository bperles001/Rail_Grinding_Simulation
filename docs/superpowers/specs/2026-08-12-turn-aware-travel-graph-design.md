# Auto Planner: grafo de deslocamento consciente de giro (turn-aware)

## Contexto

A implementação de histerese + Simulated Annealing (spec/plano de 2026-08-11) corrigiu 4 bugs reais, mas a verificação de campo (systematic-debugging) revelou uma limitação de arquitetura, não mais um bug pontual: `build_travel_graph` (usado por `RollingHorizonILPStrategy` e `SimulatedAnnealingStrategy` via `CommittedWindowStrategy`) trata cada estação como um único nó, sem modelar que a máquina só pode percorrer trechos compatíveis com sua direção atual (`CARREGADO`/`VAZIO`), e que mudar de direção exige estar numa estação com `can_turn=True` e custa 1 dia real (confirmado em `Simulator.flip_global_direction`).

Resultado observado (diagnóstico real, `network_20251223_115340.json`): a máquina ficou presa oscilando entre duas estações vizinhas (ZQX↔ZIQ) por dezenas de passos, porque o alvo escolhido pelo solver "parecia" alcançável no grafo simplificado mas na prática exigia um giro que nem o grafo nem a execução sabiam que era necessário. 4 fixes pontuais (histerese, fallback de giro, invalidação por alvo inalcançável) não resolveram - o sintoma se repetiu idêntico, trocando só qual estação era o alvo "impossível" da vez. Isso é exatamente o padrão que a skill de debug sistemático descreve como "questionar a arquitetura em vez de continuar tentando patch".

**Confirmado com o Bruno**: o Manual Route **não é afetado** - ele sempre usou os métodos reais do `Simulator` (`get_all_moves_any_direction()`, `get_turn_choices()`) diretamente, nunca o grafo simplificado (que só existe desde a sessão do Auto Planner). Nenhum ajuste retroativo necessário no Manual nem no plano `"Plano - Nós (v2 segment_actions)"` já feito lá.

## Objetivo

Fazer o grafo de planejamento e a execução real do Auto Planner enxergarem a mesma regra que o `Simulator` já aplica corretamente: nem todo trecho é alcançável de qualquer direção, e mudar de direção tem custo. Sem isso, nenhuma comparação entre algoritmos (Greedy/ILP/SA) é justa - todos sofrem do mesmo problema de navegação, mascarando diferenças reais de qualidade de decisão.

## Desenho: grafo de estado (estação, direção)

**Nó do grafo passa a ser `(nome_da_estação, direção)`** em vez de só `nome_da_estação`, `direção ∈ {"CARREGADO", "VAZIO"}`.

**Arestas de movimento**: construídas reaproveitando a mesma lógica que o `Simulator` real usa para decidir o que é válido - `_get_possible_moves` (`src/simulator/network_utils.py`, já usado pelo motor) para enumerar as opções físicas de cada estação, e `_classify_directional_segment` (`src/simulator/core.py`, já usado por `Simulator.get_possible_moves()`) para classificar cada opção. **Reaproveitar essas funções diretamente, não recriar uma versão paralela** - foi exatamente uma versão paralela desalinhada que causou o problema atual.
- Se a classificação for `None` (trecho sem restrição de direção): aresta em ambas as direções, `(estação, CARREGADO)→(destino, CARREGADO)` e `(estação, VAZIO)→(destino, VAZIO)`.
- Se for `"CARREGADO"` ou `"VAZIO"`: aresta só nessa direção.
- Peso da aresta = soma de `move_time_days` de todos os segmentos da opção (mesma conta que `Simulator.move_to` usa pra duração real de um movimento puro).

**Arestas de giro**: para cada estação com `can_turn=True`, aresta `(estação, CARREGADO)→(estação, VAZIO)` e a recíproca, peso 1 (mesmo custo de `flip_global_direction`).

## Duas funções de distância, para dois usos diferentes

1. **`shortest_travel_days(graph, from_state, to_station)`** - `from_state` é um par `(estação, direção)` conhecido de verdade (a posição real da máquina agora). Retorna o menor caminho considerando as duas direções possíveis de chegada no destino. Usada pela execução real (ver abaixo) e pela checagem de "alvo ainda alcançável" em `_should_replan`.
2. **`shortest_travel_days_any_direction(graph, from_station, to_station)`** - não conhece a direção real (usada dentro do CP-SAT/SA pra estimar distância entre dois candidatos arbitrários dentro de uma janela, onde não dá pra saber de antemão em que direção a máquina vai chegar em cada parada sem re-arquitetar o modelo inteiro pra rastrear direção como variável de decisão - fora de escopo desta rodada). Toma o mínimo entre as 4 combinações de direção de partida/chegada. **Simplificação documentada explicitamente**: só para ranquear candidatos dentro do modelo; a execução real (função 1) é sempre exata.

## Execução real vira "seguir o caminho mais curto", não mais "vizinho mais próximo"

Hoje `_next_real_move_toward` escolhe, entre as opções imediatas (`sim.get_possible_moves()`), a que minimiza a distância até o alvo - uma heurística gulosa de 1 salto que pode entrar em becos sem saída (foi a causa raiz confirmada da oscilação). Passa a:
1. Calcular o caminho mais curto de verdade (Dijkstra no grafo de estado) da posição+direção real atual até o alvo.
2. Olhar só o **primeiro passo** desse caminho: é um giro, ou um movimento pra outra estação?
3. Se giro: `StepDecision(kind="turn")`.
4. Se movimento: procurar entre `sim.get_possible_moves()` (ou `get_all_moves_any_direction()` se a direção atual não tiver opção) a opção real cuja estação de destino bate com o primeiro passo do caminho calculado - garante que os `Segment` object executados são sempre os reais e válidos segundo as regras do motor, o grafo só decide "pra onde", nunca "com qual Segment".

Isso garante corretude por construção: um caminho mais curto de verdade nunca escolhe uma rota sem contar o giro necessário, ao contrário da heurística gulosa atual.

## Impacto nos arquivos existentes

- `travel_graph.py`: reescrito (grafo de estado + as 2 funções de distância + `shortest_path_first_step`).
- `committed_window.py`: `_next_real_move_toward` reescrito pra seguir caminho em vez de vizinho mais próximo; `_should_replan` passa a receber a direção real atual.
- `rolling_ilp.py`/`simulated_annealing.py`: trocam as chamadas a `shortest_travel_days(graph, station_a, station_b)` (assinatura antiga, sem direção) por `shortest_travel_days_any_direction(graph, station_a, station_b)` (mesma simplificação de antes, só renomeada pra deixar explícito que é uma aproximação).
- `horizon.py`, `rolling_horizon_ilp.py`, `simulated_annealing_strategy.py`: sem mudança de interface pública.

## Testes

- `travel_graph.py`: casos determinísticos cobrindo (a) trecho só-CARREGADO não aparece no grafo em estado VAZIO; (b) giro custa 1 dia e só existe em estação `can_turn=True`; (c) caminho que exige giro é calculado corretamente (ex.: A→B só vazio, precisa girar em A antes) com o custo certo incluindo o giro; (d) `shortest_travel_days_any_direction` toma o mínimo entre as combinações.
- `committed_window.py`: cenário onde o vizinho mais próximo por distância ingênua leva a um beco sem saída, mas o caminho mais curto real passa por giro primeiro - a estratégia deve escolher o giro, não o vizinho.
- Regressão completa da suíte (269 testes hoje) após cada mudança - zero regressão é o padrão já estabelecido.
- Validação final: reexecutar o script de diagnóstico usado pra achar o problema (`ZTO→ZCZ`, rede real, 40 passos) e confirmar que a oscilação ZQX↔ZIQ não se repete mais. Só depois disso o script de estudo multi-horizonte (já pronto, `scripts/compare_auto_strategies.py`) é rodado de verdade.

## Fora de escopo desta rodada

- Rastrear direção como variável de decisão dentro do modelo CP-SAT/SA (permitiria order de visita ótimo considerando giros explicitamente no modelo, não só na execução) - mudança maior, considerar depois de ver se a execução turn-aware sozinha já resolve o problema observado.
- Qualquer mudança de UI.
- Rodar o estudo multi-horizonte - só acontece depois da validação de campo confirmar que o problema sumiu.
