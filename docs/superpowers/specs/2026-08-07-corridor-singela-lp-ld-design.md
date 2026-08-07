# Corredor Singela + LP/LD — Design

Data: 2026-08-07

## Contexto

Onde a malha tem Singela (via única compartilhada) + Linha Principal (LP,
sentido exportação) + Linha Desviada (LD, sentido importação) entre o mesmo
par de estações — hoje modelados como 3 `Segment` independentes
(`TAG-TRO`, `TAG-TRO-LP`, `TAG-TRO-LD`) — o motor de simulação trata os três
como **rotas alternativas**: `_get_possible_moves` (`src/simulator/network_utils.py`)
devolve um `(segmento, estação)` por segmento adjacente que permite aquele
sentido, e o planejador (manual ou automático) escolhe UM deles.

Fisicamente está errado: pra ir de uma estação à outra nesses trechos, a
máquina passa **sempre pelos dois** — a Singela inteira e, dentro dela, o
trecho direcional (LP ou LD, conforme o sentido: exportação→LP,
importação→LD). Confirmado com o Bruno em 2026-08-07: um deslocamento nesses
trechos é **um único passo lógico** que afeta os dois segmentos físicos ao
mesmo tempo — não dois passos, não uma escolha entre rotas.

Achado colateral: `DirectionModel` (`src/simulator/direction_model.py`)
constrói um dicionário `(origem, destino) -> segmento` **sobrescrevendo**
entradas quando mais de um segmento permite o mesmo par (que é exatamente o
caso Singela+LP/LD, já que a Singela permite os dois sentidos e a LD/LP
também cobre um deles) — bug latente na mesma área, resolvido como
consequência natural da correção abaixo (o agrupamento por corredor passa a
ser a fonte única de verdade para "qual segmento cobre esse sentido").

## Decisões confirmadas com o Bruno

1. **Passo único lógico** por deslocamento/manutenção, mesmo afetando dois
   segmentos físicos — mas o plano/timeline precisa mostrar **qual linha
   direcional (LP/LD) foi usada** naquela passada, não só o nome do corredor.
2. **Manutenção sempre nos dois juntos**: `maintain` completo reseta
   curva+tangente da Singela E da direcional; `maintain_curves` reseta só a
   curva dos dois. Não existe manutenção parcial de só um dos dois segmentos
   do par nessa v1.
3. **Duração = soma dos dois** (`move_time_days`/`maintenance_time_days` da
   Singela + da direcional).
4. **Trechos sem Singela não mudam** (ex.: `ZKE-ZBL`/`ZEV-ZKE`/`ZPT-ZEV`/
   `ZPG-ZPT` — só Carregado/Vazio, sem trecho compartilhado): continuam
   sendo 2 vias paralelas independentes, escolhe uma por vez, como hoje.

## Conceito novo: agrupamento por corredor

Em vez de introduzir uma classe `Corridor` persistida, o agrupamento é
**derivado on-the-fly** a partir de `Segment.allowed_movements`, do mesmo
jeito que `DirectionModel` já tenta fazer hoje (só que corrigido):

- Agrupar todos os segmentos por par de estação não-ordenado
  (`frozenset({seg.start_station.name, seg.end_station.name})`).
- Dentro de cada grupo, um segmento é **bidirecional** (Singela) se
  `len(seg.allowed_movements) >= 2`; é **direcional** (LP, LD, Carregado ou
  Vazio) se permite exatamente 1 sentido.
- Padrões de grupo esperados na malha real:
  - **1 segmento** (bidirecional, sem par direcional): trecho simples de
    hoje, sem mudança — o "corredor" é só ele mesmo.
  - **2 segmentos, ambos direcionais, sentidos opostos**: par
    Carregado/Vazio sem Singela — sem mudança, escolhe o que bate com o
    sentido, como hoje.
  - **3 segmentos** (1 bidirecional + 2 direcionais, sentidos opostos): o
    caso Singela+LP+LD — **aqui entra a correção**: mover no sentido A→B usa
    `[bidirecional, direcional_que_permite_A→B]` juntos.

## Mudanças por camada

### 1. Novo helper de agrupamento (`src/simulator/network_utils.py`)

`_get_possible_moves(segments, station)` muda de retornar
`List[Tuple[Segment, Station]]` para `List[Tuple[Tuple[Segment, ...], Station]]`
— cada movimento possível vem com a tupla de 1 ou 2 segmentos físicos que
ele atravessa (bidirecional primeiro quando presente, depois o direcional),
resolvidos pelo agrupamento acima. `_get_adjacent` continua igual (ainda
enumera segmentos por estação); a lógica de agrupamento entra como uma nova
função privada `_group_by_station_pair` chamada de dentro de
`_get_possible_moves`.

### 2. `Simulator` (`src/simulator/core.py`)

- `get_possible_moves()` e `get_all_moves_any_direction()` passam a devolver
  `List[Tuple[Tuple[Segment, ...], Station]]`, refletindo a mudança acima.
  A filtragem por `machine.global_direction` em `get_possible_moves()`
  continua igual, só que `self._direction_model.classify(...)` passa a
  classificar usando exclusivamente o **segmento direcional** da tupla (o
  último elemento), nunca o bidirecional (que não carrega sentido).
- `move_to(self, segments: Sequence[Segment], next_station: Station, action="v", duration_override=None)`
  — troca o parâmetro único `seg: Segment` por `segments: Sequence[Segment]`
  (1 ou 2 elementos). Efeitos aplicados a **cada** segmento da sequência:
  - `add_load`/`increment_mtbt` (cada segmento já tem sua própria linha no
    `mtbt_schedule.csv`, isso não muda).
  - `reset_maintenance(component)` quando `performed=True` — mesmo
    `component` ("both" ou "curva") em todos os segmentos da sequência.
  - `duration` (quando sem `duration_override`) = soma de
    `seg.maintenance_time_days`/`seg.move_time_days` de todos os segmentos
    da sequência.
  - `machine.front_car_position` recebe o **último** segmento da sequência
    (o direcional, mais perto da estação de chegada — ou o único, quando não
    há par).
  - O step dict devolvido troca a chave `"segment": seg.name` por
    `"segments": [s.name for s in segments]` (lista; 1 elemento nos casos
    sem mudança). Mantém `"segment"` também, apontando pro último elemento
    (o direcional/mais relevante), só por conveniência de quem já lê essa
    chave — ver nota de compatibilidade abaixo.
  - `mtbt_before_curva`/`mtbt_before_tangente` capturados do **último**
    segmento (o direcional) — é o dado mais específico pro trecho que
    acabou de ser tratado; a Singela pode ser inspecionada separadamente
    pelo nome dela na tabela de segmentos.

### 3. Auto-planner (`src/railroad_backend/services/auto_planner.py`)

- `_needs_maintenance(pair_segments)` e `_maintenance_action_for(pair_segments)`
  passam a aceitar uma sequência de segmentos: due = `any` componente due em
  `any` segmento da sequência; ação = `ACTION_MAINTAIN` se a tangente de
  `any` segmento estiver due, senão `ACTION_MAINTAIN_CURVES`.
- `_move_priority`, `_perform_next_step`, `_days_until_next_threshold`:
  ajustados para iterar sobre a tupla de segmentos de cada opção de
  movimento (vinda do novo formato de `get_possible_moves()`), agregando
  `load`/`threshold` da mesma forma (`any`/`max` conforme o caso, seguindo o
  padrão já usado pro corte curva/tangente).

### 4. Manual planner (`src/railroad_backend/services/manual_planner.py`)

- `ManualMoveOption.segment: str` → `ManualMoveOption.segments: Tuple[str, ...]`.
- `_find_segment_for_move` → `_find_segments_for_move`, procurando a tupla
  de segmentos (não mais um único) que liga a estação atual ao destino
  informado.
- `_handle_move_step` lê `step.get("segments") or [step["segment"]]` (aceita
  planos salvos antigos com a chave singular — compatibilidade de dado
  gravado em disco, não hack de código; mesmo padrão já usado pros códigos
  legados de ação `"m"`/`"v"`) e repassa a tupla resolvida pro `move_to`.

### 5. UI — Manual Route (`src/railroad_frontend/views/manual.py`)

- `_manual_plan_dataframe`: coluna "Segment" mostra os nomes dos segmentos
  da passada (ex.: `TAG-TRO + TAG-TRO-LD`); nova informação de sentido
  (Carregado/Vazio) exibida ao lado — reaproveita a mesma classificação
  CARREGADO/VAZIO que o `DirectionModel` já calcula, não inventa rótulo novo.
- `_format_option` (lista de próximos destinos) mostra o corredor + sentido,
  não os nomes crus dos segmentos.

### 6. Timeline (`src/simulator/timeline.py`, `src/utils/timeline_generator.py`)

- `prepare_timeline_rows` usa `step["segments"]` (lista) pra rotular a linha
  do Gantt; label passa a incluir o sentido (Carregado/Vazio) quando o passo
  tiver 2 segmentos.

### 7. Persistência de planos salvos

`plan_storage.py` não precisa de migração ativa — planos salvos antes desta
mudança têm `"segment"` singular, que o `_handle_move_step` atualizado já
sabe ler (ver item 4). Planos novos gravam `"segments"` (lista).

## Fora de escopo

- Trechos sem Singela (Carregado/Vazio puro) — comportamento intocado.
- Qualquer mudança na regra de 70%/30% do MTBT (isso já foi resolvido com
  dado real por segmento, sessão anterior).
- Manutenção parcial de só um dos dois segmentos do par (Bruno confirmou que
  não existe esse caso na v1).

## Testes

- Agrupamento: grupo de 1 segmento (sem mudança), grupo de 2 direcionais
  sem Singela (sem mudança), grupo de 3 (Singela+LP+LD) resolve a tupla
  certa pra cada sentido.
- `Simulator.move_to()` com 2 segmentos: MTBT acumula nos dois, duração é a
  soma, `maintain`/`maintain_curves` reseta os dois juntos.
- Regressão: todos os testes hoje passando que usam segmento único (rede
  padrão `default.json`, sem trios Singela+LP+LD) continuam passando sem
  alteração — é a garantia de que o caso "grupo de 1" não regride nada.
- Auto-planner: prioriza corredor cujo qualquer um dos dois segmentos esteja
  vencido; escolhe `maintain` completo quando a tangente de qualquer um dos
  dois está vencida.
- Manual planner: `_find_segments_for_move` resolve a tupla certa; plano
  salvo com `"segment"` singular antigo ainda executa.
- UI: dataframe mostra os dois nomes de segmento + sentido para um passo de
  corredor com Singela.
