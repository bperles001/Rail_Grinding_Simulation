# MTBT Threshold separado por Curva/Tangente — Design

Data: 2026-08-06

## Contexto

Hoje `Segment` tem um único par `load` (MTBT acumulado) × `mtbt_threshold` (limite de
vencimento) por trecho. No domínio real, curva e tangente degradam em ritmos
diferentes e têm limiares diferentes (C1/C2 vs C3/C4 no CLAUDE.md do projeto) — mas
o modelo de dados nunca refletiu isso: existe uma ação `ACTION_MAINTAIN_CURVES`
("manutenção só de curva") desde a sessão de 2026-07, mas ela opera sobre o mesmo
par único `load`/`mtbt_threshold` que a manutenção completa. Esse gap já estava
registrado em `SecondBrain/projetos/simulador-esmerilhamento/decisoes.md` (entrada
de 2026-08-04) como pendente de resolução.

Pedido do Bruno: a tabela **Segments** do Network Editor precisa de dois limites de
MTBT Threshold — um para Curva, um para Tangente — em vez de um único.

## Decisões confirmadas com o Bruno

1. **O load acumulado também se divide em dois** (`load_curva`/`load_tangente`), não
   só o threshold — senão a comparação fica ambígua (um load único contra qual dos
   dois limites?).
2. **Semântica de manutenção**: `maintain` completo zera os dois acumuladores;
   `maintain_curves` zera só o de curva (a razão de existir manutenção só-de-curva é
   justamente ter limites diferentes).
3. **Timeline (Gantt)**: label/tooltip passa a mostrar os dois valores (Curva e
   Tangente); a cor da barra continua única por trecho, baseada no pior caso
   (maior razão load/threshold entre os dois componentes).

## Achado durante a investigação: bug latente

`GrinderMachine.perform_maintenance()` (`src/models/__init__.py`) chama
`segment.reset_maintenance()` sem olhar qual ação foi executada — hoje
`maintain_curves` já reseta o segmento inteiro, igual a `maintain` completo, o que
anula a distinção pretendida entre as duas ações. Esta mudança corrige isso como
parte do mesmo trabalho (não é escopo à parte: a correção só faz sentido depois que
existir um `load_curva` para resetar isoladamente).

## Mudanças por camada

### 1. Modelo de dados (`src/models/__init__.py`)

`Segment`:
- Remove `load: float`, `mtbt_threshold: float`
- Adiciona `load_curva: float = 0.0`, `load_tangente: float = 0.0`,
  `mtbt_threshold_curva: float = 0.0`, `mtbt_threshold_tangente: float = 0.0`
- Adiciona `maintenance_due_curva: bool = False`, `maintenance_due_tangente: bool = False`
  (mantém `maintenance_due: bool` como OR dos dois, para código que só precisa saber
  "este trecho está vencido em algo")
- `add_load(amount)` → aplica o mesmo incremento aos dois acumuladores (o CSV de
  tráfego não diferencia curva/tangente hoje) e recalcula os dois flags de
  vencimento + o flag geral
- `reset_maintenance(component: Literal["both", "curva", "tangente"] = "both")` →
  zera o(s) acumulador(es) e flag(s) correspondente(s)
- `increment_mtbt()`/`add_mtbt()` continuam como wrappers finos de `add_load`

`GrinderMachine.perform_maintenance(segment, component)` passa `component` adiante
para `reset_maintenance`.

### 2. Simulador (`src/simulator/core.py`)

`move_to()`: ao chamar `machine.perform_maintenance(seg, ...)`, decide o `component`
pela `action` recebida — `ACTION_MAINTAIN_CURVES` → `"curva"`, `ACTION_MAINTAIN` →
`"both"`.

### 3. Planejador automático (`src/railroad_backend/services/auto_planner.py`)

- `_needs_maintenance(seg)` → `seg.maintenance_due_curva or seg.maintenance_due_tangente`
- `_days_until_next_threshold` → escaneia os dois acumuladores/limites, retorna o
  menor prazo entre os dois componentes
- Nova função para decidir a ação: só curva vencida → `ACTION_MAINTAIN_CURVES`;
  tangente vencida (com ou sem curva) → `ACTION_MAINTAIN` completo (não existe ação
  "só tangente" — o grind completo cobre as duas)

### 4. Persistência / schema JSON

`_REQUIRED_SEGMENT_FIELDS` (`src/utils/network_loader.py` e
`src/railroad_backend/domain/validation.py`): troca `mtbt_threshold` por
`mtbt_threshold_curva` e `mtbt_threshold_tangente`.

`_build_segments` (`network_loader.py`) e `serialize_network_editor_state`
(`network_editor.py` service): leem/escrevem os dois campos novos em vez do único.

**Migração dos 4 arquivos de rede existentes** (`data/networks/default.json`,
`rumo.json`, `teste_cria_o.json`, `network_20251223_115340.json`): duplicar o valor
atual de `mtbt_threshold` nos dois campos novos como ponto de partida (mesmo valor
nos dois — o Bruno ajusta os limites reais de curva depois pela UI). Campo antigo
removido, sem alias de compatibilidade (não há consumidor externo desses arquivos
fora deste repo).

### 5. UI — Network Editor (`src/railroad_frontend/views/network_editor.py`,
`src/railroad_backend/domain/network_editor.py`, `src/railroad_backend/services/network_editor.py`)

Coluna única "MTBT threshold" → duas colunas "MTBT threshold (curva)" e "MTBT
threshold (tangente)", mesmo padrão de `NumberColumn` já usado para
`Curve length (km)`/`Tangent length (km)`. Atualiza `network_editor_segment_df`,
`serialize_network_editor_state`, `collect_network_editor_issues` (validação de
negativos) e o diff summary (`network_editor_diff_summary`) para os dois campos.

`streamlit_app.py` (formulário de quick-add de segmento, ~linha 443): troca o
default único `mtbt_threshold: 1000.0` por dois defaults.

### 6. Timeline (`src/simulator/timeline.py`, `src/utils/timeline_generator.py`)

`prepare_timeline_rows` passa a carregar `mtbt_before_curva`/`mtbt_before_tangente` e
os dois thresholds por trecho. `_get_label_color` calcula a cor pelo pior caso
(maior razão load/threshold entre os dois). O texto do label/tooltip mostra os dois
valores lado a lado (ex.: `Curva: 12/15 · Tangente: 8/30`).

## Fora de escopo (explicitamente, por enquanto)

- Diferenciar o **tráfego** (CSV de MTBT mensal) por curva/tangente — continua um
  valor único aplicado aos dois acumuladores.
- Reestruturar o Gantt em sub-linhas separadas por componente — descartado nesta
  rodada, o Bruno confirmou label combinado + cor única basta.
- Separação adicional por Linha Principal × Desviada dentro do mesmo trecho —
  limitação conhecida #1 do CLAUDE.md do projeto, continua resolvida via segmentos
  duplicados no JSON, não alterada aqui.

## Impacto em testes

Arquivos que hoje constroem `Segment(mtbt_threshold=...)` ou dicts de rede com
`"mtbt_threshold"` precisam de atualização (grep prévio encontrou 24 arquivos
tocando o termo, a maioria dados/testes): `tests/test_models.py`,
`tests/test_edge_cases.py`, `tests/test_network_loader.py`,
`tests/test_network_editor.py`, `tests/test_streamlit_app_ui.py`,
`tests/test_validation.py`, `tests/test_direction_logic.py`, `tests/test_basic.py`.
Novos testes cobrindo: reset seletivo por componente (`maintain_curves` não deve
mais afetar `load_tangente`), decisão de ação no auto-planner quando só um
componente vence, e round-trip do loader/serializer com os campos novos.
