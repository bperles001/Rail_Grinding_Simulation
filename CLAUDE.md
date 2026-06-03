# CLAUDE.md — Simulador de Esmerilhamento Ferroviário

## Quem é o usuário
Especialista de Engenharia de Via Permanente em ferrovia. Alta capacidade técnica. Trabalha com times de campo e suporte a decisões operacionais. Não precisa de simplificações — aprecia raciocínio direto, construtivo e conjunto.

## O que é este projeto
Simulador de programação do equipamento de esmerilhamento de trilhos. Roda em **Streamlit + Python**. O objetivo é determinar automaticamente a melhor rota, data e modo de operação do equipamento para atender todos os trechos da ferrovia dentro do prazo de ciclo, com o menor impacto operacional possível.

Hoje o usuário faz ~10 simulações manuais para encontrar a melhor estratégia entre ~120+ combinações possíveis. Este sistema deve automatizar e superar isso.

---

## Como rodar

```bash
# Duplo clique (Windows)
start.bat

# Terminal
.venv\Scripts\python.exe run_streamlit.py

# Testes
.venv\Scripts\python.exe -m pytest tests/ -v

# Com coverage
.venv\Scripts\python.exe -m pytest tests/ --cov=src --cov-report=term-missing
```

A app abre em **http://localhost:8501**.

---

## Domínio técnico — leia antes de tocar no código

### A rede ferroviária
- ~14 estações conectadas em grafo semi-linear (corredor principal + ramais)
- Cada estação tem até 3 destinos possíveis
- Cada estação tem atributo `can_turn` (booleano) — indica se é possível inverter a frente da máquina naquele ponto

### O equipamento
A máquina tem sempre uma **frente definida** — estado crítico que deve ser rastreado o tempo todo.

| Ação | Velocidade | Produz? | Condição |
|------|------------|---------|----------|
| Esmerilhar | Lenta | Sim | Apenas no sentido da frente |
| Deslocar | Rápida | Não | Qualquer sentido (frente ou ré) |
| Parado | — | Não | Estratégico |

- Marcha a ré: apenas em situação crítica. Quando de ré, só pode deslocar ou parar.
- `can_turn = True` → permite inverter a frente. `False` → frente travada.

### Ciclo de manutenção — dupla dimensão
Cada trecho tem urgência calculada por **dias** E **tonelagem acumulada** desde o último serviço:
```
urgência = max(dias / ciclo_dias, tonelagem_ac / ciclo_ton)
# urgência >= 1.0 → trecho vencido
```

**4 constantes por equipamento:**
- C1, C2 → limiares de intervenção para **curvas** (preventivo e corretivo)
- C3, C4 → limiares de intervenção para **tangentes**

### Estrutura de ciclo por trecho
Cada trecho tem até **4 componentes independentes** de ciclo:
```
TRO → TMI
  ├── Linha Principal (trens carregados — volume alto)
  │     ├── Tangente (C3/C4)
  │     └── Curvas   (C1/C2)
  └── Linha Desviada (trens vazios — volume menor)
        ├── Tangente (C3/C4)
        └── Curvas   (C1/C2)
```
Curvas e tangentes vencem em momentos diferentes dentro do mesmo trecho.

### Estado completo da simulação
```python
estado = {
    "posicao": str,            # estação atual
    "frente": str,             # direção que a máquina aponta
    "data_atual": date,
    "trechos": {
        "TRO-TMI": {
            "principal": {
                "tangente": {"dias_ac": int, "ton_ac": float, "ultimo_servico": date},
                "curvas":   {"dias_ac": int, "ton_ac": float, "ultimo_servico": date}
            },
            "desviada": { ... }
        }
    }
}
```

---

## Saída esperada — Roteiro
A saída principal é um roteiro de programação:

```
Trecho       Composição          MTBT    D.Prod  D.Cancel  Período
TRO→TMI      Tangente + Curvas     3        2        3     01/05–05/05
TMI→ZAR      Tangente + Curvas     4        —        —     05/05–10/05
Giro ZAR     —                     —        —        —     11/05
ZAR→TMI      Só Curvas          AC 80       —        —     ...
```

Campos: trecho, composição, MTBT (dias ou volume acumulado), dias produtivos, dias cancelados, período.

---

## Arquitetura — 3 camadas

```
┌─────────────────────────────────────────────────────────┐
│  src/railroad_frontend/   (Streamlit UI)                │
│  → views, components, state                             │
│  → NUNCA contém lógica de negócio                       │
└───────────────────────┬─────────────────────────────────┘
                        │ chama
┌───────────────────────▼─────────────────────────────────┐
│  src/railroad_backend/    (Regras de negócio)           │
│  → domain/, services/, persistence/                     │
│  → Orquestra o simulator, não contém UI                 │
└───────────────────────┬─────────────────────────────────┘
                        │ chama
┌───────────────────────▼─────────────────────────────────┐
│  src/simulator/  +  src/utils/   (Motor puro)           │
│  → Simulator, modelos, cálculos                         │
│  → Sem dependência de Streamlit ou do backend           │
└─────────────────────────────────────────────────────────┘
```

### Fluxo de dados principal
```
JSON (network file)
  → load_network()           → NetworkConfig dataclass
  → build_network()          → stations dict + segments list
  → Simulator.__init__()     → grafo em memória
  → sim.init_machine()       → GrinderMachine posicionada
  → sim.move_to() / wait / flip  → sim.steps list
  → prepare_timeline_rows()  → linhas normalizadas
  → TimelineGenerator        → matplotlib Figure (PNG)
```

---

## Mapa de arquivos

### `src/models/__init__.py`
Dataclasses compartilhadas: `Station`, `Segment`, `GrinderMachine`. Constantes de ação: `ACTION_MAINTAIN = "maintain"`, `ACTION_MOVE = "move"`.

### `src/simulator/`
Motor puro de simulação — sem dependência de Streamlit.

| Arquivo | O que faz |
|---------|-----------|
| `core.py` | Classe `Simulator`: `init_machine()`, `move_to()`, `wait_days()`, `flip_global_direction()`. Estado mutável. |
| `direction_model.py` | `DirectionModel`: classifica cada aresta como CARREGADO ou VAZIO usando os `allowed_movements` do segmento. |
| `network_utils.py` | `build_network()`, `get_possible_moves()`, `get_turn_choices()`. Constrói o grafo a partir de `NetworkConfig`. |
| `timeline.py` | `prepare_timeline_rows()`: converte `sim.steps` em linhas normalizadas para visualização. Recebe `timeline_order` opcional. |

### `src/utils/`

| Arquivo | O que faz |
|---------|-----------|
| `network_loader.py` | `load_network(path)` → `NetworkConfig`. Parseia JSON, valida estrutura, constrói dataclasses. |
| `mtbt_transform.py` | `build_daily_map()`: expande CSV mensal (YYYY-MM colunas) para mapa diário `{seg_name: {date_str: valor}}`. |
| `timeline_generator.py` | `TimelineGenerator`: recebe linhas normalizadas e produz gráfico matplotlib estilo Gantt. Suporta labels interativos. |

### `src/railroad_backend/domain/`

| Arquivo | O que faz |
|---------|-----------|
| `simulator.py` | Re-exporta `Simulator` e define `DEFAULT_NETWORK_FILE`. |
| `schedule.py` | `build_daily_map()`: facade sobre `mtbt_transform` com validação. |
| `validation.py` | `validate_manual_plan()`: valida estrutura de plano antes do replay. |
| `network_editor.py` | Parsing e serialização do estado do editor de rede (DataFrames ↔ JSON). |
| `network_layout.py` | Algoritmos de posicionamento automático de estações no sketch. |
| `persistence.py` | Tipos e helpers de I/O de planos salvos. |

### `src/railroad_backend/services/`

| Arquivo | O que faz |
|---------|-----------|
| `auto_planner.py` | `run_auto_plan(config)` → `AutoPlanResult`. Algoritmo heurístico greedy: prioriza segmentos vencidos, aguarda próximo vencimento se nada estiver urgente. |
| `manual_planner.py` | `replay_manual_plan(config, plan)` → `ManualPlanReplay`. Executa passo-a-passo o plano manual no simulador. |
| `network_editor.py` | Helpers puros para o estado do editor: diff, validação, defaults, serialização. |
| `schedule_service.py` | Facade tipada sobre helpers de schedule. |

### `src/railroad_backend/persistence/`

| Arquivo | O que faz |
|---------|-----------|
| `plan_storage.py` | `save_manual_plan()`, `load_manual_plan()`, import/export de snapshots JSON. |

### `src/railroad_frontend/views/`
Cada arquivo = uma página do dashboard.

| Arquivo | Página |
|---------|--------|
| `network_editor.py` | Editor de estações, segmentos, ordem do timeline. |
| `mtbt_editor.py` | Editor da planilha MTBT por segmento/mês. |
| `auto_simulation.py` | Executar planejamento automático, salvar/carregar runs. |
| `manual.py` | Construir plano manual passo-a-passo. |
| `comparison.py` | Comparar resultado automático vs manual lado a lado. |
| `overview.py` | Dashboard resumo com métricas da rede. |
| `schedule.py` | Visualizar planilha MTBT. |

### `src/railroad_frontend/components/`

| Arquivo | O que faz |
|---------|-----------|
| `ui_components.py` | 40+ funções de UI reutilizáveis: cards, métricas, banners, formulários. Inclui CSS da marca RUMO. |
| `timeline.py` | `render_timeline()`: wrapper Streamlit para o `TimelineGenerator`. Fornece botões de download PNG/CSV. |

### `src/railroad_frontend/state/`

| Arquivo | O que faz |
|---------|-----------|
| `session.py` | Constantes de chave de sessão, `ensure_*` loaders, `persist_plan_storage()`. |

### Raiz

| Arquivo | O que faz |
|---------|-----------|
| `streamlit_app.py` | Entrypoint principal. Sidebar, navegação entre páginas, fábrica de callbacks, gerenciamento de arquivos de rede. |
| `run_streamlit.py` | Launcher leve que chama `streamlit run streamlit_app.py`. |
| `start.bat` | Duplo clique para iniciar no Windows. |

---

## Padrão de state management (Streamlit)

Cada view recebe dois objetos frozen dataclass:

```python
@dataclass(frozen=True)
class SomePageSessionKeys:
    config_key: str      # chave para st.session_state[config_key]
    result_key: str      # chave para st.session_state[result_key]

@dataclass(frozen=True)
class SomePageCallbacks:
    on_save: Callable[[], None]
    data_provider: Callable[[], List[Something]]
    # ... outros callbacks
```

- `SessionKeys` contém **apenas strings** (chaves do session_state).
- `Callbacks` contém **callables** que fazem a ponte para o `streamlit_app.py`.
- A view nunca acessa `st.session_state` pelo nome direto — só pelas chaves que recebeu.
- Isso mantém as views testáveis sem dependência do entrypoint.

---

## Limitações conhecidas (não alterar sem discussão)

| # | Limitação | Impacto |
|---|-----------|---------|
| 1 | Cada `Segment` tem **um único `load`** | O domínio exige 4 componentes (principal/tangente, principal/curva, desviada/tangente, desviada/curva). Workaround atual: criar segmentos separados no JSON por componente. |
| 2 | Algoritmo automático é **heurístico greedy** | Ótimo local; pode não encontrar o melhor roteiro global. Candidatos futuros: PLI, GRASP, metaheurísticas. |
| 3 | MTBT no CSV é **por segmento/mês** (scalar) | Não há como diferenciar Tangente/Curva dentro do mesmo segmento na planilha. |
| 4 | Sem CI/CD | Não há pipeline automatizado. Rodar `pytest` manualmente antes de qualquer merge. |
| 5 | `streamlit_app.py` é grande (~1200 linhas) | Refatoração planejada: extrair `network_manager.py`, `sidebar.py`, `callbacks.py`. |

---

## Fluxo de versões e commits (Git + GitHub)

O projeto usa **Git** (controle de versão local) + **GitHub** (cópia na nuvem) + **CHANGELOG.md** (registro humano do que mudou).

- Repositório: https://github.com/bperles001/Rail_Grinding_Simulation
- Branch principal: `master`
- Versão atual: ver `pyproject.toml` → campo `version`

---

### Referência rápida — cartão de bolso

```
DURANTE O TRABALHO          git add <arquivo>  →  git commit -m "..."
SALVAR NA NUVEM             git push
VER O QUE MUDOU             git status  /  git log --oneline
AO TERMINAR UMA FASE        atualizar CHANGELOG.md  →  commit  →  push
AO LANÇAR VERSÃO            CHANGELOG + pyproject.toml  →  commit  →  tag  →  push tag
```

---

### Situação 1 — Trabalho do dia a dia

A cada mudança significativa (não precisa ser perfeita — só coerente):

```bash
# 1. Ver o que mudou
git status

# 2. Escolher os arquivos a incluir
git add src/simulator/core.py
git add src/railroad_backend/services/auto_planner.py
# (nunca "git add ." sem checar git status antes)

# 3. Salvar o snapshot local
git commit -m "fix: corrige cálculo de urgência quando threshold é zero"

# 4. Enviar para o GitHub
git push
```

**Prefixos de commit:**

| Prefixo | Quando usar |
|---------|-------------|
| `feat:` | Nova funcionalidade |
| `fix:` | Correção de bug |
| `refactor:` | Reorganização de código (sem mudar comportamento) |
| `docs:` | CLAUDE.md, CHANGELOG.md, comentários |
| `test:` | Adicionar ou corrigir testes |
| `chore:` | Atualizar dependências, configs |

---

### Situação 2 — Ao terminar uma feature ou fase de trabalho

```bash
# 1. Rodar os testes — todos devem passar
.venv\Scripts\python.exe -m pytest tests/ -q

# 2. Abrir CHANGELOG.md e adicionar entrada em [Unreleased]
#    Exemplo:
#    ## [Unreleased]
#    ### Added
#    - Novo algoritmo de priorização por tonelagem acumulada

# 3. Commitar e enviar
git add CHANGELOG.md
git commit -m "docs: update changelog — priorização por tonelagem"
git push
```

---

### Situação 3 — Ao lançar uma versão nova (release)

Fazer isso quando um conjunto de features está completo e estável.

```bash
# 1. Em CHANGELOG.md:
#    - Renomear [Unreleased] → [0.6.0] — 2026-MM-DD
#    - Adicionar novo [Unreleased] vazio no topo

# 2. Em pyproject.toml:
#    version = "0.6.0"

# 3. Commitar as mudanças de release
git add CHANGELOG.md pyproject.toml
git commit -m "chore: release v0.6.0"

# 4. Criar a tag local
git tag v0.6.0

# 5. Enviar commit e tag para o GitHub
git push
git push origin v0.6.0
```

A tag aparece em: https://github.com/bperles001/Rail_Grinding_Simulation/tags

---

### Situação 4 — Trabalhar em algo experimental (branch)

Quando a mudança é grande ou incerta, isole em um branch para não afetar o `master`.

```bash
# Criar e entrar no branch
git checkout -b feature/otimizador-v2

# Trabalhar normalmente (add + commit)
git add src/railroad_backend/services/optimizer.py
git commit -m "feat: otimizador com busca em largura"

# Enviar o branch para o GitHub (para backup)
git push -u origin feature/otimizador-v2

# Quando estiver pronto: voltar ao master e juntar
git checkout master
git merge feature/otimizador-v2

# Apagar o branch (o trabalho já está no master)
git branch -d feature/otimizador-v2
git push origin --delete feature/otimizador-v2
```

---

### Guia de versão (SemVer: MAJOR.MINOR.PATCH)

| Tipo de mudança | Bump | Exemplo |
|-----------------|------|---------|
| Correção de bug, melhoria pequena | PATCH (0.5.**x**) | Fix display → 0.5.1 |
| Nova feature, sem quebra | MINOR (0.**x**.0) | Otimizador → 0.6.0 |
| Marco v1 (modelo 4 componentes) | MAJOR (**x**.0.0) | v1.0.0 |

---

### Regras — o que nunca fazer

- Não criar arquivos `PHASE_X_SUMMARY.md` ou `*_SUMMARY.md` → usar CHANGELOG.md
- Não commitar `*.png` (imagens de timeline) → já excluído no `.gitignore`
- Não commitar `*.log` → já excluído no `.gitignore`
- Não usar `git add .` sem antes checar `git status`
- Não fazer `git push --force` no branch `master`

---

## Como trabalhar neste projeto

- Sempre explicar o raciocínio antes de propor mudanças
- Nunca alterar lógica de domínio sem confirmar entendimento primeiro — o domínio ferroviário tem nuances específicas
- Ao identificar um problema conceitual, apresentar o problema + a modelagem correta + o impacto prático
- Registrar decisões importantes para atualizar o documento de contexto
- Perguntar sobre conceitos do domínio quando houver dúvida — o usuário é o especialista
- Priorizar código limpo, modular e com boas práticas Python (type hints, docstrings, separação de camadas)

---

## Glossário rápido

| Termo | Significado |
|-------|-------------|
| Esmerilhamento | Correção do perfil do trilho por abrasão |
| Girador / can_turn | Ponto onde a máquina pode inverter sua frente |
| MTBT | Mean Time Between Treatments — ciclo de manutenção |
| Frente | Direção de trabalho da máquina (só esmerilha para a frente) |
| Tangente | Trecho reto da via |
| Curva | Trecho curvo — degrada mais rápido que a tangente |
| Linha principal | Usada por trens carregados — maior volume, ciclo mais curto |
| Linha desviada | Usada por trens vazios — menor volume, ciclo mais longo |
| Ramal | Trecho secundário conectado ao corredor principal |
| Re | Marcha a ré — só permite deslocamento, sem produção |
| AC | Acumulado — ciclo medido em tonelagem acumulada |

---

## Histórico de versões

> Detalhes completos de cada versão: veja **`CHANGELOG.md`**.

| Versão | Data | Marco |
|--------|------|-------|
| v0.5.0 | Jun/2026 | Versão funcional: editor de rede, MTBT editor, simulação automática, simulação manual, comparação, timeline configurável. |
| v1.0 | (planejado) | Algoritmo de otimização avançado, suporte a 4 componentes por segmento. |

*Para discussões conceituais e atualizações deste documento, usar Claude.ai (claude.ai) em paralelo.*
