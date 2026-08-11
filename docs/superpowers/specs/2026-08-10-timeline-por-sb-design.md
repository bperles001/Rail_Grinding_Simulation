# Timeline por SB (par de estações), cor por direção, letra curva/completa — Design

Data: 2026-08-10

## Contexto

Bruno testou o Manual Route real (`"Plano - Nós (v2 segment_actions)"`) e
achou o timeline atual pouco legível: uma linha por segmento físico (até 3
por par de estações — Singela + LP + LD), cor por status genérico
(move/maintenance/maintenance_curves/wait/turn), sem indicar por qual ramal
(Principal/Carregado x Desviada/Vazio) a manutenção passou.

Pedido: colapsar as linhas por **SB** (par de estações, ex. `ZTO-ZCZ`, sem
sufixo `-LP`/`-LD`/`-C`/`-V`), codificar o **ramal** por cor, e sinalizar
manutenção só-curva vs. completa por uma letra no rótulo. A ideia de mostrar
o **MTBT acumulado por trecho** ao longo do tempo fica fora desta rodada —
Bruno vai trazer essa ideia depois, como camada separada.

## Decisões confirmadas com o Bruno (2026-08-10)

1. **SB = par de estações**, obtido removendo o sufixo direcional
   (`-LP`/`-LD`/`-C`/`-V`) do nome do segmento mais específico do passo.
   Singela + LP + LD do mesmo corredor sempre compartilham o mesmo par-base
   — colapsar é seguro, sem ambiguidade.
2. **Cor por ramal, só quando há manutenção**: se algum segmento
   **mantido** no passo termina em `-LD`/`-V` → verde (Desviada); senão
   (termina em `-LP`/`-C`, ou é só Singela sem sufixo) → azul (Principal/
   Carregado, default). Segmentos com token `none` no passo não entram
   nessa decisão.
3. **Movimento puro (sem manutenção) não distingue ramal** — uma cor só
   (laranja), independente de Carregado/Vazio.
4. **Espera (wait) continua amarela** como hoje — cor diferente do
   movimento puro, pra não confundir "parado" com "deslocando".
5. **Giro (turn) continua cinza** como hoje.
6. **Letra no rótulo**: `A` quando algum segmento mantido no passo foi
   `completa`, `C` quando só houve `curva` (mesma regra já usada pra
   classificar `step["action"]` desde a sessão de 2026-08-10 cedo — reuso
   direto, sem recalcular).
7. **Letra + número no mesmo rótulo** (ex. `"A 8"`, `"C 8"`), na mesma
   posição inteligente que o número de MTBT já usa hoje — sem rótulo
   separado disputando espaço.
8. **Número de MTBT mantido como está** (o "pior caso" curva/tangente
   corrigido na sessão anterior) — não é substituído nesta rodada.
9. **Fora de escopo**: visualização de MTBT acumulado por trecho ao longo
   do tempo (ideia futura do Bruno, ainda não especificada).

## Paleta nova

| Situação                                   | Cor        | Hex       |
|---------------------------------------------|------------|-----------|
| Manutenção via Principal/Carregado (default) | Azul       | `#3B82F6` |
| Manutenção via Desviada/Vazio                | Verde      | `#22C55E` |
| Movimento puro (sem manutenção)              | Laranja    | `#F97316` |
| Espera (wait/idle)                           | Amarelo    | `#F2C744` (inalterado) |
| Giro (turn)                                  | Cinza      | `#777777` (inalterado) |

As cores antigas de `maintenance`/`maintenance_curves` (verde `#4EA24E` e
roxo `#9B59B6`) são removidas — a distinção curva/completa passa a ser só a
letra do rótulo, não mais a cor.

## Mudanças por camada

### 1. `src/simulator/timeline.py`

- Função nova `_sb_key(segment_name: str) -> str`: remove o sufixo
  `-LP`/`-LD`/`-C`/`-V` do fim do nome, se presente; senão devolve o nome
  inalterado. Usada em vez de `_base_label` (hoje idêntica a "não faz
  nada") para computar o rótulo de linha (`step`) e a chave de
  `segment_thresholds`.
- Função nova `_direction_role(step, maintained_names) -> Optional[str]`:
  devolve `"vazio"` se algum nome em `maintained_names` termina em
  `-LD`/`-V`; `"carregado"` se `maintained_names` não é vazio (default,
  cobre LP/C e Singela pura); `None` se não houve manutenção nesse passo
  (`maintained_names` vazio — inclui `move`).
- `_create_timeline_row`: ganha o campo novo `"direction"` no
  `base_row` (valor de `_direction_role`, só relevante quando
  `status in ("maintenance", "maintenance_curves")`; `None` nos demais
  status). `"step"` passa a usar `_sb_key(...)` no lugar do nome bruto do
  segmento/junção.
- `prepare_timeline_rows`: `segment_thresholds` passa a ser chaveado por
  `_sb_key(seg_obj.name)` (pode haver colisão entre Singela/LP/LD do mesmo
  par — como os 3 hoje já compartilham a mesma dupla de thresholds na
  prática real do Bruno, usa o último segmento processado; não é uma
  regressão porque hoje cada linha já tinha seu próprio threshold
  igualmente aproximado). `y_order`/`timeline_order` também passam pelo
  `_sb_key(...)` antes de montar a lista, deduplicando preservando ordem.

### 2. `src/utils/timeline_generator.py`

- `create_timeline_plot`: troca a lógica de cor —
  ```
  if status == 'turn': cinza
  elif status == 'wait': amarelo
  elif status == 'move': laranja
  elif status in ('maintenance', 'maintenance_curves'):
      verde se row['direction'] == 'vazio' else azul
  ```
- `_should_add_label`/`_add_bar_label`: o texto do rótulo passa a ser
  `f"{letra} {mtbt_before:.0f}"` quando `status` é `maintenance`/
  `maintenance_curves` e há `mtbt_before` numérico (`letra` = `"A"` ou
  `"C"` conforme `status`); mantém só o número quando não há letra
  aplicável (não deveria ocorrer pra esses status, mas por segurança);
  mantém `"turn"` como está pro giro. `move`/`wait` continuam sem rótulo
  (como hoje, já que `_should_add_label` só dispara pra `turn` ou
  `mtbt_before` numérico presente — `move`/`wait` não carregam
  `mtbt_before` hoje).
- `customize_plot`: legenda atualizada com as 5 entradas novas (Principal/
  Carregado, Desviada, Movimento, Espera, Giro) substituindo as antigas
  (Move/Maintenance/Maintenance curves/Turn); acrescenta uma nota de texto
  fixa no canto (`fig.text`) explicando `"C = só curva · A = completa"`.

### 3. Consumidores (`manual.py`, `auto_simulation.py`, `comparison.py`)

Nenhuma mudança de código — já passam `steps`/`segments`/`timeline_order`
pro `prepare_timeline_rows`/`TimelineGenerator` sem conhecer o formato
interno das linhas.

## Fora de escopo

- Visualização de MTBT acumulado por trecho ao longo do tempo (próxima
  ideia do Bruno, ainda não especificada).
- Mudança no motor (`core.py`) — todos os dados necessários já existem
  (`maintained_segments`, `action`, `mtbt_before_curva/tangente`).
- Auto Planner: já não usa `segment_actions` (ação única por trecho), então
  toda manutenção do Auto Planner cai no ramo `maintained_names` não-vazio
  — comportamento de cor ainda se aplica normalmente (`carregado` por
  default quando o trecho mantido não tem sufixo `-LD`/`-V`), sem mudança
  de escopo necessária ali.

## Testes

- `_sb_key`: remove sufixo `-LP`/`-LD`/`-C`/`-V`; nome sem sufixo fica
  igual; não quebra nomes de estação com hífen legítimo (não há hoje na
  rede real, mas o strip é só do sufixo final, não de qualquer hífen).
- `prepare_timeline_rows`: passo com `segments=["A-B", "A-B-LD"]`,
  `maintained_segments=["A-B", "A-B-LD"]` → `row["step"] == "A-B"`,
  `row["direction"] == "vazio"`. Passo só com Singela mantida
  (`maintained_segments=["A-B"]`, sem sufixo) → `direction == "carregado"`.
  Passo `move` (sem manutenção) → `direction is None`.
- `TimelineGenerator.create_timeline_plot`: cor da barra bate com
  `(status, direction)` pra cada combinação da tabela de paleta; rótulo de
  uma barra `maintenance` com `mtbt_before=8.0` é `"A 8"`; `maintenance_curves`
  com `mtbt_before=8.0` é `"C 8"`.
- Regressão: suíte completa (`pytest`) sem quebrar os testes existentes de
  `prepare_timeline_rows`/`TimelineGenerator` já presentes em
  `test_basic.py` (ajustados pro novo schema, mesmo padrão da sessão
  anterior).
