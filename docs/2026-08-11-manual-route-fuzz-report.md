# Manual Route — Relatório da campanha de fuzz-testing overnight

Data: 2026-08-11 (noite) → 2026-08-12 (madrugada)

## Contexto e pedido

Antes de seguir para o Auto Planner, o Bruno pediu uma bateria exaustiva de
cenários contra a rede real (`network_20251223_115340.json`), variando anos
2026-2027, com/sem 2º KLD, com/sem giros, e o máximo de combinações de
`segment_actions` — incluindo cenários **deliberadamente extremos e
ilógicos** ("mesmo que ilógicos... a ideia é ver os comportamentos mais
aleatórios e impossíveis") — para achar falhas de verdade antes de
considerar o Manual Route pronto.

## O que foi feito

- **Backup da rede**: `data/networks/network_20251223_115340_original.json`
  — cópia intocada antes de qualquer teste (os testes só leem a rede, nunca
  escrevem nela).
- **Duas ferramentas novas** (`scripts/`, não fazem parte do produto):
  - `overnight_manual_route_fuzz.py` — caminhadas aleatórias *realistas*:
    inicializa o `Simulator` do jeito real (`initialize_simulation_from_args`,
    mesmo caminho de produção do Manual Route), escolhe movimentos via
    `list_available_moves` com `segment_actions` aleatórios (none/curva/
    completa por segmento), giros e esperas ocasionais, durações variadas
    (20 a 240 passos).
  - `overnight_manual_route_adversarial.py` — cenários **extremos de
    propósito**: sequências só-de-giro, só-de-espera (dias grandes, até
    10000), só-completa, só-curva, só-none, caminhos de até 1500 passos, e
    uma bateria de probes diretos em entradas inválidas (ano fora de
    1900-2200, par estação/facing inexistente ou repetido, token de
    `segment_actions` inválido, segmento inexistente, `wait_days` ≤ 0).
  - Ambos rodam o pipeline de timeline inteiro (`prepare_timeline_rows` +
    `TimelineGenerator.create_timeline_plot()`) ao final de cada cenário —
    mesmo código que a UI usa pra renderizar.
  - Checagem de invariantes por passo: sem carga negativa,
    `maintained_segments`/`action`/`kld_reading` consistentes com os tokens
    usados.

## Volume rodado

| Lote | Cenários | Resultado |
|---|---|---|
| Fuzz realista (`overnight_manual_route_fuzz.py`) | 8.000 | **100% ok**, zero achados |
| Adversarial extremo, lote 1 (código antes dos fixes) | 3.000 | 75 exceções (1 causa raiz), 202 avisos de renderização (1 causa raiz), resto ok |
| Adversarial extremo, lote de confirmação (após fix 1) | 500 | **0 exceções**, 33 avisos (código ainda sem o fix 2) |
| Adversarial extremo, lote de confirmação final (após os 2 fixes) | 300 | **100% ok** (0 exceções, 0 avisos de renderização) |
| Validações manuais menores durante o desenvolvimento | ~150 | 0 achados novos |

**Total: ~12.000 cenários simulados** contra a rede real, cobrindo toda a
combinação de ano (2026/2027) × 2º KLD (sim/não) × giros (permitidos/não) ×
extensão de caminhada (curta a muito longa) × padrão de `segment_actions`
(aleatório misto, só-completa, só-curva, só-none).

## Bugs reais encontrados e corrigidos

### 1. Plano começando com giro quebrava o timeline

**Sintoma**: se o plano começa com um giro *antes de qualquer movimento*
(possível sempre que a estação inicial tem `can_turn=True` — `ZTO`, `TRO`,
`RDA`, `ZPT`, `PSG` na rede real), `prepare_timeline_rows` devolvia uma
lista vazia, e `TimelineGenerator.process_data()` quebrava com
`ValueError: Timeline data is missing required column(s)`.

**Causa raiz**: `src/simulator/timeline.py` só desenhava o passo de giro se
já existisse uma linha anterior (`last_step_label`), que só é setada nos
ramos de movimento/espera. Sem nenhum movimento prévio, o giro era
descartado silenciosamente.

**Fix**: giro sem movimento anterior usa o nome da própria estação como
rótulo da linha, em vez de ser descartado. Commit `f14858a`.

### 2. Plano com muitas esperas longas em sequência estourava o eixo do gráfico

**Sintoma**: um plano com muitas esperas longas seguidas (cenário
deliberadamente ilógico pedido pelo Bruno — ex. 1500 esperas de até 365
dias cada, cobrindo centenas de anos) fazia o `MonthLocator(interval=1)`
fixo do timeline tentar gerar milhares de ticks, estourando
`Locator.MAXTICKS` (1000) do matplotlib. Não quebrava (matplotlib só
registra um aviso via `logging`, não levanta exceção), mas produzia um
eixo X ilegível — passaria despercebido no app real, sem nenhum erro
visível além do gráfico corrompido.

**Causa raiz**: intervalo do locator fixo em 1 mês, independente da
duração total do plano.

**Fix**: intervalo do locator agora escala com o intervalo de tempo total
do gráfico, mirando ~30 ticks. Commit `0c8e71e`.

**Achado de processo relevante**: a primeira tentativa de capturar esse
aviso via `warnings.catch_warnings()` não pegava nada — o matplotlib usa
`logger.warning()` (módulo `logging`), não `warnings.warn()`. Sem
adicionar um `logging.Handler` também, esse gap real teria passado batido
pela campanha inteira.

## Robustez de validação confirmada (não são bugs)

Todos os 15 probes de entrada inválida vieram como `expected_error` — o
motor rejeita corretamente:
- Ano fora de 1900-2200 (`ValueError`).
- Par estação/facing inexistente ou igual — `init_machine` cai pro
  fallback TRO/TMI de forma sã, sem produzir máquina quebrada.
- Token de `segment_actions` inválido e nome de segmento inexistente
  (`ValueError`, sem corromper `sim.steps`).
- `wait_days` ≤ 0 (`ValueError`).

## Gap aberto — decisão de negócio, não bug de código

`Simulator.wait_days()` **não tem limite superior** no motor nem na
validação de plano salvo (`validate_manual_plan_step`) — só o widget da UI
(`st.number_input(..., max_value=365)`) restringe a 365 dias, e só quando
o passo é criado interativamente pelo formulário. Um plano importado via
JSON (import de planos salvos) poderia ter `wait_days` arbitrariamente
grande sem ser rejeitado.

**Recomendação**: espelhar o limite de 365 dias também no motor
(`wait_days()`) e na validação (`validate_manual_plan_step`), como defesa
em profundidade. **Não implementei isso** porque é uma regra de negócio
(qual o limite operacional real de espera num único passo) que cabe ao
Bruno confirmar, não uma correção de código com resposta óbvia.

## O que esta campanha NÃO cobre (limitações conhecidas)

- Camada de UI Streamlit (formulários, botões, `AppTest`) — só o motor
  (`core.py`/`manual_planner.py`) e o pipeline de timeline foram
  exercitados diretamente.
- Edição de `days_override` de um passo já criado.
- Fuzzing da persistência de planos salvos (import/export/roundtrip de
  `saved_plans.json`).
- Auto Planner — fora de escopo desta rodada, por pedido explícito do
  Bruno (fechar o Manual antes de seguir).

## Conclusão

Depois de ~12.000 cenários (realistas + deliberadamente extremos/ilógicos)
e a correção dos 2 bugs reais encontrados, o motor do Manual Route não
apresentou nenhuma exceção não tratada nem violação de invariante nos
lotes de confirmação finais. O único item aberto é uma decisão de negócio
(limite de `wait_days`), não um defeito de código. Do ponto de vista de
robustez de engine, o Manual Route parece pronto para ser considerado
fechado — pendente a confirmação do Bruno sobre o ponto acima e sobre as
limitações de escopo listadas.
