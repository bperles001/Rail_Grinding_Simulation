# Manutenção parcial de corredor (só Singela ou só pátio) — Design

Data: 2026-08-07

## Contexto

A correção anterior (`docs/superpowers/specs/2026-08-07-corridor-singela-lp-ld-design.md`)
tornou o deslocamento/manutenção num trecho Singela+LP/LD um passo lógico
único que sempre afeta os dois segmentos físicos juntos — decisão confirmada
na época: "esmerilha as duas juntas sempre".

Uso real revelou o furo dessa decisão: ao ir de TRO a TAG, Bruno já
esmerilhou a Singela + a Desviada. Na volta (TAG a TRO), a Singela já foi
feita — não faz sentido esmerilhar ela de novo, só falta a linha do pátio
que ainda não foi tratada no sentido oposto (Principal).

## Decisões confirmadas com o Bruno (2026-08-07)

1. Escopo: só **Manual Route** — o Auto Simulation continua tratando o
   par como unidade, sem essa granularidade.
2. Os dois casos existem: manter **só a Singela** (sem o pátio) OU **só o
   pátio** (sem a Singela) — não é só o caso "pátio sem Singela".
3. Deslocamento (MTBT acumulado) continua sempre nos dois segmentos —
   fisicamente você sempre passa pelos dois. Só a **manutenção** (reset do
   MTBT) fica seletiva.

## Mudanças por camada

### 1. `Simulator.move_to()` (`src/simulator/core.py`)

Novo parâmetro opcional `maintain_segments: Optional[Sequence[Segment]] = None`.
Quando `action` é `ACTION_MAINTAIN`/`ACTION_MAINTAIN_CURVES`:
- Sem `maintain_segments` (`None`): comportamento atual, mantém todos os
  segmentos do passo (compatibilidade total com planos já salvos).
- Com `maintain_segments`: só os segmentos dessa lista têm
  `reset_maintenance(component=...)` chamado; os demais segmentos do passo
  **não são resetados**, mas continuam acumulando MTBT normalmente (não
  muda o carregamento, só o reset).

**Duração**: por segmento, não mais uniforme. Cada segmento do passo
contribui `maintenance_time_days` se estiver em `maintain_segments`
(ou se `maintain_segments` for `None`, isto é, todos), senão contribui
`move_time_days` (você só está passando por ele, não esmerilhando). A
duração total continua sendo a soma — só muda o que cada segmento
contribui.

O step dict devolvido ganha `"maintained_segments": [nomes dos segmentos
efetivamente resetados nesta passada]` (lista vazia se nenhum foi mantido,
ex.: ação `move`), ao lado das chaves já existentes `"segment"`/`"segments"`.

### 2. Execução do plano manual (`src/railroad_backend/services/manual_planner.py`)

`_handle_move_step` lê `step.get("maintain_segments")` (lista de nomes) e
resolve pros objetos `Segment` correspondentes (mesmo padrão de
`_find_segments_for_move`), repassando como `maintain_segments` pro
`move_to`. Ausente/`None` = comportamento atual (mantém todos).

### 3. UI — Manual Route "Add move" (`src/railroad_frontend/views/manual.py`)

Quando a opção de movimento selecionada tem 2 segmentos (`len(selected_option.segments) == 2`)
e a ação escolhida é "Maintenance" ou "Curves only", aparece um seletor
adicional: **"Manutenção: Ambos / Só a Singela (`<nome>`) / Só o pátio
(`<nome>`)"** — os nomes reais dos segmentos aparecem no rótulo, não
"Singela"/"pátio" genérico, pra ficar claro qual dos dois. Quando o
movimento tem só 1 segmento (sem par), esse seletor não aparece (não há
escolha a fazer).

O passo salvo no plano ganha `"maintain_segments": [nome]` quando o Bruno
escolher "só um dos dois"; ausente quando escolher "Ambos" (mesmo
resultado que hoje, sem a chave nova).

### 4. Tabela do plano / timeline

Fora de escopo nesta rodada — o texto "Segment" da tabela (`" + ".join(...)`)
já mostra os dois nomes; não vamos diferenciar visualmente qual foi mantido
vs. só percorrido por enquanto. Pode virar um passo seguinte se o Bruno
sentir falta.

## Fora de escopo

- Auto Simulation — continua tratando o par como unidade, sem essa escolha.
- Editar `maintain_segments` de um passo já criado pela tabela do plano
  (`plan_step_editor`) — a escolha é feita só no momento de adicionar o
  passo, pelo formulário "Add move".

## Testes

- `move_to()` com `maintain_segments` restrito a 1 dos 2 segmentos: só esse
  segmento é resetado; o outro mantém o load acumulado; duração é a soma
  mista (maintenance_time_days do mantido + move_time_days do não-mantido).
- `move_to()` sem `maintain_segments` continua resetando os dois (regressão
  do comportamento atual, já coberto pelos testes existentes).
- `_handle_move_step` repassa `step["maintain_segments"]` corretamente.
- UI: seletor de manutenção parcial só aparece quando a opção tem 2
  segmentos e a ação não é "Move"; passo salvo carrega `maintain_segments`
  só quando um subconjunto foi escolhido.
