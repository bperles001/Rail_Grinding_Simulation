# Manual Route: plano salvo guarda a config (estação/facing/anos/2º KLD) — Design

Data: 2026-08-07

## Contexto

Ao carregar o plano salvo `"Plano - Nós (v2 segment_actions)"`, o replay falhou
com `Step 1: segment(s) ['ZTO-ZCZ', 'ZTO-ZCZ-LD'] cannot reach ZCZ from PIT` —
a estação inicial da sessão (config manual, editada à mão) estava em `PIT`,
sem relação com a estação que o plano espera (`ZTO`). Hoje um plano salvo
(`save_manual_plan`/`load_manual_plan`, `src/railroad_backend/persistence/plan_storage.py`)
guarda só a lista de passos — a config (`start_station`, `facing_station`,
`start_year`, `end_year`, `second_kld`) fica inteiramente na sessão do
Streamlit, desacoplada do plano, e nunca é salva/restaurada junto.

## Decisões confirmadas com o Bruno (2026-08-07)

1. **Só o formato novo, sem fallback pro formato antigo.** App em fase de
   construção — não vale a pena carregar complexidade de compatibilidade
   com um formato que só existe em 2 planos, ambos migrados agora.
2. **Carregar um plano salvo também aplica a config** (substitui o que
   estiver na tela, igual já acontece hoje quando você reconfigura
   manualmente e o plano é resetado).
3. **O seletor "Novo plano / Abrir plano salvo" fica no topo da página**,
   antes da seção "⚙️ Configuration" — "Novo plano" mantém o comportamento
   manual de hoje; "Abrir plano salvo" preenche a config e carrega os
   passos numa ação só.
4. **Salvar passa a gravar a config atual junto com os passos.**
5. Migração dos 2 planos hoje salvos (`"Plano - Nós"`,
   `"Plano - Nós (v2 segment_actions)"`) para o formato novo, usando a
   config real desta sessão: `start_station="ZTO"`, `facing_station="ZCZ"`,
   `start_year=2026`, `end_year=2027`, `second_kld=true`.

## Novo schema de plano salvo

```json
{
  "manual": {
    "Plano - Nós": {
      "config": {
        "start_station": "ZTO",
        "facing_station": "ZCZ",
        "start_year": 2026,
        "end_year": 2027,
        "second_kld": true
      },
      "steps": [ { "mode": "move", "...": "..." } ]
    }
  }
}
```

Cada entrada de `"manual"` deixa de ser uma lista direta e passa a ser um
dict com exatamente as chaves `"config"` e `"steps"`. `"config"` tem
exatamente as mesmas 5 chaves do dict já usado em `session_keys.config_key`
na sessão do Streamlit — nenhum campo novo é inventado, só passa a ser
persistido.

## Mudanças por camada

### 1. `src/railroad_backend/persistence/plan_storage.py`

- `save_manual_plan(saved_plans, name, plan, config)`: ganha o parâmetro
  `config: Dict[str, Any]` (obrigatório, sem default). Passa a gravar
  `{"config": dict(config), "steps": [dict(step) for step in plan]}`.
- `load_manual_plan(saved_plans, name) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]`:
  muda de retorno — hoje devolve só a lista de passos; passa a devolver
  `(config, steps)`. Lê `entry["config"]` e `entry["steps"]` direto, sem
  checar formato alternativo (decisão: só o formato novo).
- `plan_storage_snapshot`/`persist_plan_sections`: o parâmetro
  `manual_saved` já é um dict de nome → valor; o valor agora é
  `{"config": ..., "steps": [...]}` em vez de lista — a função só precisa
  parar de assumir que o valor é iterável de passos direto
  (`[dict(step) for step in steps if isinstance(step, dict)]` vira
  `{"config": dict(entry.get("config", {})), "steps": [dict(s) for s in entry.get("steps", []) if isinstance(s, dict)]}`).
- `import_manual_plan_payload`: mesma mudança de shape — cada entrada
  importada precisa ter `"config"` e `"steps"` (dict com steps ausente ou
  não-lista é ignorada, mesmo padrão de robustez que já existe pra
  entradas malformadas).

### 2. UI — `src/railroad_frontend/views/manual.py`

**Novo bloco no topo de `render_manual_route_page`**, antes de
`render_section_header("⚙️ Configuration")` (linha 136):

```python
render_section_header("📂 Plano")
saved_plans = state.get(session_keys.saved_plans_key, {})
plan_mode = st.radio("", ("Novo plano", "Abrir plano salvo"), horizontal=True, label_visibility="collapsed")
if plan_mode == "Abrir plano salvo" and saved_plans:
    saved_names = sorted(saved_plans.keys())
    selected_name = st.selectbox("Plano salvo", saved_names, key="manual_open_plan_select")
    if st.button("📂 Carregar", type="primary"):
        loaded_config, loaded_steps = load_manual_plan(saved_plans, selected_name)
        state[session_keys.config_key] = loaded_config
        callbacks.update_manual_plan(loaded_steps)
        st.toast(f"✓ Plano '{selected_name}' carregado (config + passos)", icon="📂")
        callbacks.force_rerun()
elif plan_mode == "Abrir plano salvo":
    st.caption("Nenhum plano salvo ainda.")
```

A seção "⚙️ Configuration" logo abaixo continua exatamente como hoje —
como `config = state.get(session_keys.config_key, {})` já é lido no topo
da função (linha 133), carregar um plano só precisa colocar o dict certo
nessa chave de sessão antes do form ler os valores default de cada campo;
nenhuma mudança adicional necessária ali.

**Seção "💾 Plan Presets"** (linhas 326-367 hoje): remove a metade de
carregar (`selected_plan`/`col_load`/botão "📂 Load plan"), mantém Salvar
e Deletar. O botão "💾 Save plan" passa a chamar
`save_manual_plan(saved_plans, name, plan, config)` (config já disponível
no escopo da função, mesma variável lida no topo).

**Import/export** (linhas 369-397): o payload exportado/importado já é o
dict `manual_snapshot` inteiro (`{"manual": manual_snapshot}`) — não muda
de estrutura no `manual.py`, só o conteúdo de cada entrada muda de forma
(config+steps em vez de lista), o que já é tratado por
`import_manual_plan_payload` (mudança de camada 1).

## Migração dos 2 planos existentes

Script one-off (mesmo padrão do `scripts/migrate_plano_nos_segment_actions.py`):
para `"Plano - Nós"` e `"Plano - Nós (v2 segment_actions)"`, envolve a
lista de passos atual em
`{"config": {"start_station": "ZTO", "facing_station": "ZCZ", "start_year": 2026, "end_year": 2027, "second_kld": true}, "steps": <lista atual>}`.

## Fora de escopo

- Qualquer plano salvo além desses 2 (não existem outros hoje).
- Mudança de schema da seção `"auto"` do storage — só `"manual"` muda.
- Suporte a formato antigo (lista direta) — decisão explícita do Bruno.

## Testes

- `save_manual_plan`/`load_manual_plan`: roundtrip config+steps.
- `plan_storage_snapshot`/`persist_plan_sections`: shape novo persistido e
  recarregado do disco corretamente.
- `import_manual_plan_payload`: aceita payload no formato novo; ignora
  entrada sem `"steps"` lista.
- UI via `AppTest`: selecionar "Abrir plano salvo" + Carregar preenche os
  campos da Configuration (station/facing/anos/KLD) com os valores do
  plano; "Novo plano" não mexe na config atual.
- Migração: os 2 planos reais viram o formato novo com a config correta;
  `replay_manual_plan` usando a config recém-carregada continua sem erros
  (regressão do bug relatado: `PIT`→`cannot reach ZCZ`).
