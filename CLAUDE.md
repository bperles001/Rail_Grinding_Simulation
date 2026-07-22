# CLAUDE.md — Simulador de Esmerilhamento Ferroviário

## Quem é o usuário
Especialista de Engenharia de Via Permanente em ferrovia. Alta capacidade técnica. Não precisa de simplificações — aprecia raciocínio direto, construtivo e conjunto.

## O que é este projeto
Simulador de programação do equipamento de esmerilhamento de trilhos (**Streamlit + Python**). Objetivo: determinar automaticamente a melhor rota, data e modo de operação do equipamento para atender todos os trechos da ferrovia dentro do prazo de ciclo, com o menor impacto operacional possível. Hoje o usuário faz ~10 simulações manuais entre ~120+ combinações possíveis — este sistema automatiza e supera isso.

## Como rodar

```bash
start.bat                                                          # Windows, duplo clique
.venv\Scripts\python.exe run_streamlit.py                          # terminal
.venv\Scripts\python.exe -m pytest tests/ -v                       # testes
.venv\Scripts\python.exe -m pytest tests/ --cov=src --cov-report=term-missing  # com coverage
```

App abre em **http://localhost:8501**.

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

**4 constantes por equipamento:** C1/C2 → limiares de intervenção para **curvas** (preventivo/corretivo); C3/C4 → idem para **tangentes**.

### Estrutura de ciclo por trecho
Cada trecho tem até **4 componentes independentes** de ciclo: Linha Principal (carregados, volume alto) × Linha Desviada (vazios, volume menor), cada uma com Tangente (C3/C4) × Curvas (C1/C2). Curvas e tangentes vencem em momentos diferentes dentro do mesmo trecho.

### Estado completo da simulação
```python
estado = {
    "posicao": str, "frente": str, "data_atual": date,
    "trechos": {
        "TRO-TMI": {
            "principal": {"tangente": {"dias_ac": int, "ton_ac": float, "ultimo_servico": date},
                          "curvas":   {"dias_ac": int, "ton_ac": float, "ultimo_servico": date}},
            "desviada": { ... }
        }
    }
}
```

### Saída esperada — Roteiro
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
src/railroad_frontend/  (Streamlit UI) → views, components, state. NUNCA lógica de negócio.
        │ chama
src/railroad_backend/   (Regras de negócio) → domain/, services/, persistence/. Orquestra o simulator, sem UI.
        │ chama
src/simulator/ + src/utils/  (Motor puro) → Simulator, modelos, cálculos. Sem dependência de Streamlit/backend.
```

Fluxo de dados: `JSON (network file) → load_network() → build_network() → Simulator.__init__() → sim.init_machine() → sim.move_to()/wait/flip → prepare_timeline_rows() → TimelineGenerator (matplotlib PNG)`

## Mapa de arquivos

| Arquivo | O que faz |
|---------|-----------|
| `src/models/__init__.py` | Dataclasses compartilhadas: `Station`, `Segment`, `GrinderMachine`. Constantes `ACTION_MAINTAIN`/`ACTION_MOVE`. |
| `src/simulator/core.py` | Classe `Simulator`: `init_machine()`, `move_to()`, `wait_days()`, `flip_global_direction()`. Estado mutável. |
| `src/simulator/direction_model.py` | `DirectionModel`: classifica aresta como CARREGADO/VAZIO via `allowed_movements`. |
| `src/simulator/network_utils.py` | `build_network()`, `get_possible_moves()`, `get_turn_choices()`. |
| `src/simulator/timeline.py` | `prepare_timeline_rows()`: `sim.steps` → linhas normalizadas p/ visualização. |
| `src/utils/network_loader.py` | `load_network(path)` → `NetworkConfig`. Parseia/valida JSON. |
| `src/utils/mtbt_transform.py` | `build_daily_map()`: expande CSV mensal (colunas YYYY-MM) → mapa diário. |
| `src/utils/timeline_generator.py` | `TimelineGenerator`: linhas normalizadas → gráfico matplotlib estilo Gantt, labels interativos. |
| `src/railroad_backend/domain/simulator.py` | Re-exporta `Simulator`; define `DEFAULT_NETWORK_FILE`. |
| `src/railroad_backend/domain/schedule.py` | `build_daily_map()`: facade sobre `mtbt_transform` com validação. |
| `src/railroad_backend/domain/validation.py` | `validate_manual_plan()`: valida plano antes do replay. |
| `src/railroad_backend/domain/network_editor.py` | Parsing/serialização do estado do editor de rede (DataFrames ↔ JSON). |
| `src/railroad_backend/domain/network_layout.py` | Posicionamento automático de estações no sketch. |
| `src/railroad_backend/domain/persistence.py` | Tipos/helpers de I/O de planos salvos. |
| `src/railroad_backend/services/auto_planner.py` | `run_auto_plan(config)` → `AutoPlanResult`. Heurístico greedy: prioriza vencidos, aguarda próximo vencimento. |
| `src/railroad_backend/services/manual_planner.py` | `replay_manual_plan(config, plan)` → `ManualPlanReplay`. Executa plano manual passo-a-passo. |
| `src/railroad_backend/services/schedule_service.py` | Facade tipada sobre helpers de schedule. |
| `src/railroad_backend/persistence/plan_storage.py` | `save_manual_plan()`, `load_manual_plan()`, import/export JSON. |
| `src/railroad_frontend/views/*.py` | Uma página por arquivo: `network_editor`, `mtbt_editor`, `auto_simulation`, `manual`, `comparison`, `overview`, `schedule`. |
| `src/railroad_frontend/components/ui_components.py` | 40+ funções de UI reutilizáveis (cards, métricas, banners, formulários, CSS marca RUMO). |
| `src/railroad_frontend/components/timeline.py` | `render_timeline()`: wrapper Streamlit do `TimelineGenerator`, botões download PNG/CSV. |
| `src/railroad_frontend/state/session.py` | Constantes de chave de sessão, `ensure_*` loaders, `persist_plan_storage()`. |
| `streamlit_app.py` | Entrypoint: sidebar, navegação, fábrica de callbacks, gerenciamento de arquivos de rede. |
| `run_streamlit.py` | Launcher leve (`streamlit run streamlit_app.py`). |

## Padrão de state management (Streamlit)

Cada view recebe dois frozen dataclasses: `SessionKeys` (só strings — chaves do `session_state`) e `Callbacks` (callables que fazem a ponte para `streamlit_app.py`). A view **nunca** acessa `st.session_state` pelo nome direto, só pelas chaves recebidas — mantém as views testáveis sem depender do entrypoint.

## Limitações conhecidas (não alterar sem discussão)

| # | Limitação | Impacto |
|---|-----------|---------|
| 1 | Cada `Segment` tem **um único `load`** | Domínio exige 4 componentes (principal/tangente, principal/curva, desviada/tangente, desviada/curva). Workaround: segmentos separados no JSON por componente. |
| 2 | Algoritmo automático é **heurístico greedy** | Ótimo local; pode não achar o melhor roteiro global. Candidatos futuros: PLI, GRASP, metaheurísticas. |
| 3 | MTBT no CSV é **por segmento/mês** (scalar) | Não diferencia Tangente/Curva dentro do mesmo segmento na planilha. |
| 4 | Sem CI/CD | Rodar `pytest` manualmente antes de qualquer merge. |
| 5 | `streamlit_app.py` grande (~1200 linhas) | Refatoração planejada: extrair `network_manager.py`, `sidebar.py`, `callbacks.py`. |

---

## Git — regras específicas deste projeto

Repositório: https://github.com/bperles001/Rail_Grinding_Simulation · Branch principal: `master` · Versão em `pyproject.toml`.

Prefixos de commit: `feat:` `fix:` `refactor:` `docs:` `test:` `chore:`. Ao terminar uma fase, atualizar `CHANGELOG.md` (`[Unreleased]`) antes de commitar. Release = renomear `[Unreleased]`→versão no CHANGELOG + bump `pyproject.toml` + `git tag vX.Y.Z` + push com `--tags`.

**Nunca fazer:** criar `*_SUMMARY.md` (usar CHANGELOG.md) · commitar `*.png`/`*.log` (já no `.gitignore`) · `git add .` sem checar `git status` antes · `git push --force` no `master`.

## Como trabalhar neste projeto

- Sempre explicar o raciocínio antes de propor mudanças
- Nunca alterar lógica de domínio sem confirmar entendimento primeiro — o domínio ferroviário tem nuances específicas
- Ao identificar um problema conceitual: apresentar o problema + a modelagem correta + o impacto prático
- Registrar decisões importantes neste documento
- Perguntar sobre conceitos do domínio quando houver dúvida — o usuário é o especialista
- Priorizar código limpo, modular, boas práticas Python (type hints, docstrings, separação de camadas)

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
| Ré | Marcha a ré — só permite deslocamento, sem produção |
| AC | Acumulado — ciclo medido em tonelagem acumulada |

## Histórico de versões

> Detalhes completos: **`CHANGELOG.md`**.

| Versão | Data | Marco |
|--------|------|-------|
| v0.5.0 | Jun/2026 | Versão funcional: editor de rede, MTBT editor, simulação automática/manual, comparação, timeline configurável. |
| v1.0 | (planejado) | Algoritmo de otimização avançado, suporte a 4 componentes por segmento. |
