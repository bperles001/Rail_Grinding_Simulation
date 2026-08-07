# Manual Route: per-step Days override — Design

Data: 2026-08-07

## Contexto

`Segment` guarda uma média de dias por atividade (`move_time_days` para
deslocamento, `maintenance_time_days` para manutenção) — a "base" usada tanto
pelo Auto Simulation quanto pelo Manual Route Builder para calcular a duração
de cada passo do plano.

O Manual Route já tem uma tabela editável (`src/railroad_frontend/views/manual.py`,
`st.data_editor` em `_manual_plan_dataframe`) com uma coluna "Days" e a dica
"Click Action or Days cells to edit directly" — mas essa edição só está
implementada para passos do tipo `wait` (idle days). Para passos `move`
(deslocamento ou manutenção, "Traverse" na tabela), a coluna sempre mostra
`None` e qualquer edição é descartada silenciosamente: `duration` em
`Simulator.move_to()` (`src/simulator/core.py`) sempre vem de
`seg.maintenance_time_days`/`seg.move_time_days`, sem parâmetro de override.

Pedido do Bruno: poder editar a duração de **um passo específico** de
deslocamento/manutenção dentro de um plano manual (ex.: "esse trecho, dessa
vez, levou 5 dias em vez dos 3 de costume"), sem alterar a base do segmento —
que continua valendo para o Auto Simulation e para qualquer outro passo/plano
que use o mesmo segmento.

## Decisão confirmada com o Bruno

- Escopo fechado no Manual Route. O Auto Simulation não muda — continua usando
  `move_time_days`/`maintenance_time_days` do segmento como já faz hoje.
- A coluna Days de um passo Traverse ainda não editado mostra a base do
  segmento já preenchida (não fica em branco) — o Bruno vê o valor padrão e só
  digita algo diferente quando quiser o override.

## Mudanças por camada

### 1. Modelo do passo do plano (dict, sem dataclass formal)

Novo campo opcional `days_override: int` em passos com `mode == "move"`.
Ausente = usa a base do segmento (comportamento atual, sem migração
necessária em planos já salvos).

### 2. Backend (`src/simulator/core.py`)

`Simulator.move_to(self, seg, next_station, action="v", duration_override=None)`:
o bloco que hoje calcula

```python
if performed:
    duration = seg.maintenance_time_days
    ...
else:
    duration = seg.move_time_days
    ...
```

passa a usar `duration = duration_override if duration_override is not None else <o mesmo cálculo de hoje>`
em cada um dos dois ramos. Nenhum outro efeito de `move_to` muda — carga de
MTBT, flags de vencimento e classificação da ação continuam calculados do
jeito que já são; só o número de dias usado no avanço de data e nos totais
acumulados (`maintenance_days_total`/`movement_days_total`) respeita o
override quando presente.

### 3. Execução do plano manual (`src/railroad_backend/services/manual_planner.py`)

`_handle_move_step` lê `step.get("days_override")` e repassa como
`duration_override` na chamada a `simulator.move_to(...)`.

### 4. UI (`src/railroad_frontend/views/manual.py`)

`_manual_plan_dataframe(plan, config, segments)` ganha o parâmetro `segments`
(via `callbacks.network_segments_provider()`, já disponível na view). Para
cada passo Traverse, resolve a base do segmento pela ação (`maintenance_time_days`
se `Maintenance`/`Curves only`, senão `move_time_days`) e preenche `Days` com
`step.get("days_override")` se presente, senão a base resolvida.

No loop que aplica as edições da tabela (`_new_plan`/`_changed`), o ramo hoje
exclusivo de `_mode == "wait"` ganha um irmão para `_mode == "move"`: compara
o valor editado com a base resolvida da linha — diferente grava
`days_override`; igual remove a chave do passo (se existir), mantendo o plano
limpo e deixando claro (para uma eventual UI futura) quais passos foram
customizados manualmente.

## Fora de escopo

- Qualquer mudança no Auto Simulation/`auto_planner.py`.
- Indicador visual (cor/ícone) marcando linhas com override — pode vir depois,
  não foi pedido agora.
- Editar a base do segmento a partir do Manual Route (isso já existe via
  Network Editor, não muda aqui).

## Testes

- `Simulator.move_to()` com `duration_override` definido avança a data pelo
  valor do override, não pela base do segmento, tanto no ramo de manutenção
  quanto no de deslocamento.
- `_handle_move_step` repassa `step["days_override"]` para `move_to` quando
  presente, e não repassa (usa a base) quando ausente.
- `_manual_plan_dataframe`: passo Traverse sem override mostra a base
  resolvida; com override mostra o valor customizado.
- Round-trip do loop de edição da tabela: valor igual à base remove
  `days_override`; valor diferente grava.
- Suíte completa (136 testes hoje) continua verde — nenhuma mudança de
  comportamento quando `days_override` está ausente.
