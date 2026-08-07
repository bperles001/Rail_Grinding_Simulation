# Manual Route: ação independente por segmento (Singela/LP/LD) — Design

Data: 2026-08-07

## Contexto

Simulação de uma rota real (ZTO → TMI → PSG → giro → TMI → TRO → ZPG → ZPT →
giro → ZBL → ZTO, com 2º KLD instalado) contra o motor do simulador, fora da
UI, revelou um gap concreto: no trecho final ZBL→ZTO ("curvas na Singela e
manutenção total nos pátios/vazio"), o modelo atual não permite duas ações
diferentes no mesmo passo. `move_to()` aplica **uma única ação** (curva OU
completa) ao subconjunto de segmentos escolhido em `maintain_segments`
(`docs/superpowers/specs/2026-08-07-partial-corridor-maintenance-design.md`)
— o outro componente do trecho fica sem manutenção nenhuma nesse passo, não
há como "passar de novo" no mesmo trecho pra cobrir a ação que faltou.

Este design **substitui** `action` + `maintain_segments` (do design anterior)
por uma escolha independente de ação por segmento dentro do mesmo passo.

## Decisões confirmadas com o Bruno (2026-08-07)

1. **Escopo: só Manual Route.** Auto Planner continua com a lógica de ação
   única por trecho, sem essa granularidade — `move_to()` mantém o parâmetro
   `action` antigo funcionando sem mudança pro caminho do Auto Planner.
2. **3 estados por segmento, iguais pra Singela/LP/LD:** `none` (não mexe) /
   `curva` (só reseta o acumulador de curva) / `completa` (reseta curva+
   tangente). Não existe estado "só tangente" isolado — na prática nunca
   vale a pena (ciclo maior, o dobro do de curva).
3. **Duração:** mesma `maintenance_time_days` por segmento pra `curva` ou
   `completa` — não há campo de duração diferenciado por tipo de ação nesta
   rodada (fica como melhoria futura separada, se precisar).
4. **Facing/KLD passa a ser uma flag, não um bloqueio.** Hoje, `move_to()`
   só executa a manutenção (`performed=True`) se
   `second_kld_installed OR edge_dir == machine.global_direction` — sem
   isso, o passo não faz nada (MTBT não reseta). No caminho novo
   (`segment_actions`), a manutenção **sempre executa** quando a ação não é
   `none` — o esmerilhamento em si não depende mais do alinhamento do
   facing. O alinhamento vira uma flag nova por segmento
   (`reading_captured`/`kld_reading`), sinalizando se a leitura pós-serviço
   do KLD foi capturada ou não. O MTBT reseta normalmente mesmo sem
   leitura — o trilho foi fisicamente esmerilhado, só falta o dado do
   perfil pós-serviço pra aquele trecho nessa passada.
5. **Onde mostrar a flag de "sem leitura":** só na tabela de resultados do
   Manual Route (`steps_df`) e como aviso no formulário "Add next step"
   antes de confirmar. Fora de escopo: timeline/Gantt
   (`src/railroad_frontend/components/timeline.py`).
6. **Migração de planos salvos:** só `"Plano - Nós"` (único plano salvo hoje
   com nomenclatura compatível com `network_20251223_115340.json`) é
   convertido pro formato novo. `"Original"` e `"2026-Original"` (nomenclatura
   de rede antiga/incompatível) são removidos de `data/saved_plans.json`.
   Migração é um script rodado uma vez, não um shim de compatibilidade
   permanente no código.

## Novo schema do passo "move"

```json
{
  "mode": "move",
  "segments": ["ZRC-ZBL", "ZRC-ZBL-LP", "ZRC-ZBL-LD"],
  "destination": "ZRC",
  "segment_actions": {
    "ZRC-ZBL": "curva",
    "ZRC-ZBL-LP": "completa",
    "ZRC-ZBL-LD": "none"
  }
}
```

`segment_actions` é obrigatório em passos "move" e deve ter exatamente uma
chave por nome em `segments`, com valor em `{"none", "curva", "completa"}`.

Nota de nomenclatura: `segment_alignment` (em `ManualMoveOption`, seção 3)
e `kld_reading` (no step dict devolvido por `move_to`, seção 2) vêm do
mesmo cálculo (`second_kld_installed or edge_dir == global_direction`) —
`segment_alignment` é o valor *previsto* mostrado no formulário antes de
confirmar a ação; `kld_reading` é o valor *registrado* depois que o passo
já foi executado.
Os campos antigos `action` e `maintain_segments` deixam de ser usados nos
passos do Manual Route (continuam existindo em `move_to()` só pro caminho
legado do Auto Planner).

## Mudanças por camada

### 1. `src/models/__init__.py`

Nenhuma mudança. `GrinderMachine.perform_maintenance()`/
`Segment.reset_maintenance()` já aceitam `component` por segmento
individualmente — o ajuste é todo em como `move_to()` os chama.

### 2. `Simulator.move_to()` (`src/simulator/core.py`)

Novo parâmetro opcional `segment_actions: Optional[Dict[str, str]] = None`.

- **Quando presente** (caminho novo, usado só pelo Manual Route): para cada
  segmento em `segments`, resolve o token (`none`/`curva`/`completa`); se
  != `none`, chama `machine.perform_maintenance(component_seg, component="curva"
  if token=="curva" else "both")` incondicionalmente (sem checar
  alinhamento). Calcula `edge_dir` do segmento e grava
  `reading_captured = second_kld_installed or edge_dir == machine.global_direction`
  por segmento maintido. Duração por segmento: `maintenance_time_days` se
  token != `none`, senão `move_time_days`; total é a soma.
- **Quando ausente** (`None`): comportamento atual inalterado, inclusive a
  trava de alinhamento — usado pelo Auto Planner e por qualquer chamada
  legada.

O step dict devolvido ganha `"kld_reading": {nome_segmento: bool, ...}`
(só para os segmentos efetivamente mantidos nesse passo) ao lado das chaves
já existentes.

### 3. `src/railroad_backend/services/manual_planner.py`

- `_handle_move_step`: lê `step["segment_actions"]`, resolve pros objetos
  `Segment` pelo nome (mesmo padrão de `_find_segments_for_move`), repassa
  como `segment_actions` pro `move_to`. Deixa de ler `action`/
  `maintain_segments` nos passos "move".
- `ManualMoveOption`/`list_available_moves`: `maintenance_aligned: bool`
  (hoje por trecho inteiro) vira `segment_alignment: Dict[str, bool]` (por
  segmento), computado com `_classify_directional_segment` de cada segmento
  vs. `machine.global_direction` (mais `second_kld_installed`). Alimenta o
  aviso "sem leitura" no formulário antes de confirmar.

### 4. `src/railroad_backend/domain/validation.py`

`validate_manual_plan_step`: para `mode == "move"`, passa a exigir
`segment_actions` (dict) em vez de `action`; valida que as chaves batem
exatamente com `segments`/`segment` e que cada valor está em
`{"none", "curva", "completa"}`.

### 5. UI — `src/railroad_frontend/views/manual.py`

**Formulário "Add next step":**
- Um radio group por segmento do trecho selecionado (1 quando não há
  Singela ou não há pátio; 2 no caso comum Singela+pátio), cada um com
  `Nada / Só curva / Completa`, rotulado pelo papel (Singela / Pátio
  Carregado (LP) / Pátio Vazio (LD)).
- Ao lado de cada radio, mostra `✓ leitura OK` ou `⚠ sem leitura KLD`
  (quando `curva`/`completa` estiver selecionado e o segmento não estiver
  alinhado nem houver 2º KLD), usando `segment_alignment`.
- No submit, monta `segment_actions` e chama `update_manual_plan`.

**Tabela de passos planejados** (`_manual_plan_dataframe`): a coluna
"Action" vira resumo somente-leitura (ex: `Singela: Curva · LP: Completa`).
Não dá pra editar ação por segmento inline numa grade de colunas fixas
(número de segmentos varia por passo) — pra mudar a ação de um passo já
criado, remove e recria pelo formulário. "Days" continua editável inline
como hoje.

**Tabela de resultados** (`manual_result["steps"]` → `steps_df`): nova
coluna "Leitura KLD" com `OK` / `⚠ sem leitura` / `—` (passos sem
manutenção), derivada de `kld_reading`.

### 6. Migração — `data/saved_plans.json`

Script único (não fica no código de produção):
- `"Plano - Nós"`: para cada passo `mode="move"`, cada segmento em
  `segments` recebe `curva`/`completa` (conforme `action` era
  `maintain_curves`/`maintain`) se estava em `maintain_segments` (ou, se
  `maintain_segments` ausente, todos os segmentos recebem o mesmo valor);
  os demais recebem `none`. Passos `turn`/`wait` não mudam.
- `"Original"` e `"2026-Original"`: removidos do arquivo.

## Fora de escopo

- Auto Planner — continua com ação única por trecho, sem granularidade por
  segmento nem a flag de leitura KLD.
- Duração diferenciada por tipo de ação (curva vs. completa).
- Estado "só tangente" isolado no schema (o `component="tangente"` já existe
  em `reset_maintenance`, só não é exposto — pode virar um passo futuro se
  precisar).
- Flag de "sem leitura" na timeline/Gantt visual — só tabela nesta rodada.
- Edição de `segment_actions` de um passo já criado pela tabela do plano.

## Testes

- `move_to()` com `segment_actions` misto (curva + completa + none no mesmo
  passo): duração correta, MTBT resetado certo por segmento,
  `kld_reading` certo (alinhado/desalinhado, com/sem 2º KLD) — incluindo o
  caso desalinhado sem 2º KLD **ainda assim resetando o MTBT** (mudança de
  comportamento vs. hoje).
- `move_to()` com `segment_actions=None` continua idêntico ao
  comportamento atual (regressão, já coberta pelos testes existentes).
- `validate_manual_plan_step` rejeitando passos "move" sem `segment_actions`
  ou com chave que não bate com `segments`.
- `list_available_moves`: `segment_alignment` por segmento bate com
  `_classify_directional_segment` vs. `global_direction`.
- Migração do `saved_plans.json`: roundtrip do formato antigo pro novo,
  valores batendo com a simulação manual já rodada nesta sessão;
  `"Original"`/`"2026-Original"` removidos.
- UI via `AppTest`: formulário renderiza um radio por segmento com o aviso
  de leitura; tabela de resultados mostra a coluna "Leitura KLD".
