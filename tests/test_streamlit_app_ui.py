"""UI-level regression tests driven through streamlit.testing.v1.AppTest.

These exercise the real Streamlit script end-to-end (widget state, reruns,
session_state) rather than the pure backend helpers, since some bugs only
exist in how the script wires widgets together.
"""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from railroad_frontend.views.manual import _manual_plan_dataframe
from src.models import Segment, Station

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_network(path: Path) -> None:
    payload = {
        "name": "UI Test Network",
        "stations": [
            {"name": "A", "can_turn": True},
            {"name": "B", "can_turn": False},
            {"name": "C", "can_turn": False},
        ],
        "segments": [
            {
                "name": "A-B",
                "start": "A",
                "end": "B",
                "length_km": 1.0,
                "mtbt_threshold_curva": 5.0,
                "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1,
                "maintenance_time_days": 1,
            },
            {
                "name": "B-C",
                "start": "B",
                "end": "C",
                "length_km": 1.0,
                "mtbt_threshold_curva": 5.0,
                "mtbt_threshold_tangente": 20.0,
                "move_time_days": 1,
                "maintenance_time_days": 1,
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _open_network_editor(tmp_path: Path) -> AppTest:
    network_path = tmp_path / "network.json"
    _write_network(network_path)

    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    at.session_state["active_network_path"] = str(network_path)
    at.session_state["navigation_page"] = "Network Editor"
    at.run()
    assert not at.exception
    return at


def _open_manual_route(tmp_path: Path) -> AppTest:
    network_path = tmp_path / "network.json"
    _write_network(network_path)

    at = AppTest.from_file(str(REPO_ROOT / "streamlit_app.py"), default_timeout=60)
    at.run()
    at.session_state["active_network_path"] = str(network_path)
    at.session_state["navigation_page"] = "Manual Route"
    at.run()
    assert not at.exception
    return at


def test_layout_table_accumulates_two_edits_before_submit(tmp_path: Path) -> None:
    """Regression test: editing a second cell used to wipe out the first
    (and the second) because the data_editor was fed a `data=` argument
    rebuilt from state the widget itself had just written to, on every
    keystroke rerun. Wrapping it in a form (matching the Stations/Segments
    editors elsewhere in this file) fixes it - edits must not be lost or
    silently dropped while the user is still editing, before Apply is
    clicked."""
    at = _open_network_editor(tmp_path)

    # First cell edit.
    at.session_state["network_layout_editor"] = {
        "edited_rows": {0: {"X": 99.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    # Second cell edit; the browser's data_editor buffer accumulates both
    # edits locally (nothing is sent to the backend yet - it's inside a form).
    at.session_state["network_layout_editor"] = {
        "edited_rows": {0: {"X": 99.0}, 1: {"Y": 77.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    widget_state = at.session_state["network_layout_editor"]
    assert widget_state["edited_rows"] == {0: {"X": 99.0}, 1: {"Y": 77.0}}, (
        "Both pending edits must still be present before Apply is clicked"
    )
    # Nothing should be committed to the network's table_overrides yet - only
    # Apply commits (unrelated: `dirty` can already be true on a fresh load
    # for other reasons, so it isn't asserted here).
    state = at.session_state["network_editor_state"]
    assert state["layout_settings"]["table_overrides"] == {}


def test_layout_table_apply_commits_all_pending_edits(tmp_path: Path) -> None:
    at = _open_network_editor(tmp_path)

    # Real form semantics: the browser sends the full accumulated grid edits
    # together with the submit click in a single round trip.
    at.session_state["network_layout_editor"] = {
        "edited_rows": {0: {"X": 99.0}, 1: {"Y": 77.0}},
        "added_rows": [],
        "deleted_rows": [],
    }
    submit_buttons = [b for b in at.button if b.label == "Apply layout changes"]
    assert len(submit_buttons) == 1
    submit_buttons[0].click().run()
    assert not at.exception

    state = at.session_state["network_editor_state"]
    overrides = state["layout_settings"]["table_overrides"]
    assert overrides["A"]["x"] == 99.0
    assert overrides["B"]["y"] == 77.0
    assert state["dirty"] is True


def test_gps_import_computes_schematic_positions_and_leaves_other_stations_untouched(
    tmp_path: Path,
) -> None:
    at = _open_network_editor(tmp_path)

    # C already has a manual override before the import - it must survive
    # untouched, since the pasted list below only covers A and B.
    state = at.session_state["network_editor_state"]
    state["layout_settings"]["table_overrides"]["C"] = {"x": 42.0, "y": 42.0}

    at.session_state["network_layout_gps_text"] = (
        "A, 0.0, 0.0\n"
        "B, 0.0, 1.0\n"  # B due east of A (longitude increases east)
    )
    import_buttons = [b for b in at.button if b.label == "Aplicar e normalizar posições"]
    assert len(import_buttons) == 1
    import_buttons[0].click().run()
    assert not at.exception

    state = at.session_state["network_editor_state"]
    overrides = state["layout_settings"]["table_overrides"]
    assert set(overrides) == {"A", "B", "C"}
    assert state["dirty"] is True

    ax, ay = overrides["A"]["x"], overrides["A"]["y"]
    bx, by = overrides["B"]["x"], overrides["B"]["y"]
    assert bx > ax  # B stays east of A
    assert overrides["C"] == {"x": 42.0, "y": 42.0}  # untouched - not in the pasted text


def test_gps_import_reports_unknown_station(tmp_path: Path) -> None:
    at = _open_network_editor(tmp_path)

    at.session_state["network_layout_gps_text"] = "NOPE, 0.0, 0.0"
    import_buttons = [b for b in at.button if b.label == "Aplicar e normalizar posições"]
    import_buttons[0].click().run()
    assert not at.exception

    warnings = [w.value for w in at.warning]
    assert any("NOPE" in w for w in warnings)
    state = at.session_state["network_editor_state"]
    assert state["layout_settings"]["table_overrides"] == {}


def test_manual_plan_dataframe_shows_segment_base_days_for_traverse() -> None:
    a = Station("A")
    b = Station("B")
    seg = Segment(name="A-B", start_station=a, end_station=b, length=1.0, move_time_days=3, maintenance_time_days=6)

    plan = [{"mode": "move", "segment": "A-B", "destination": "B", "segment_actions": {"A-B": "none"}}]
    df = _manual_plan_dataframe(plan, {}, [seg])
    assert df.loc[0, "Days"] == 3

    plan_maint = [{"mode": "move", "segment": "A-B", "destination": "B", "segment_actions": {"A-B": "completa"}}]
    df_maint = _manual_plan_dataframe(plan_maint, {}, [seg])
    assert df_maint.loc[0, "Days"] == 6
    assert df_maint.loc[0, "Action"] == "Singela: Completa"

    plan_override = [{"mode": "move", "segment": "A-B", "destination": "B", "segment_actions": {"A-B": "none"}, "days_override": 9}]
    df_override = _manual_plan_dataframe(plan_override, {}, [seg])
    assert df_override.loc[0, "Days"] == 9


def test_manual_plan_dataframe_shows_joined_segment_names_for_corridor_step() -> None:
    a = Station("A")
    b = Station("B")
    singela = Segment(name="A-B", start_station=a, end_station=b, length=10.0, move_time_days=2, maintenance_time_days=3)
    directional = Segment(name="A-B-LD", start_station=a, end_station=b, length=1.0, move_time_days=1, maintenance_time_days=1)

    plan = [{
        "mode": "move", "segments": ["A-B", "A-B-LD"], "destination": "B",
        "segment_actions": {"A-B": "curva", "A-B-LD": "completa"},
    }]
    df = _manual_plan_dataframe(plan, {}, [singela, directional])
    assert df.loc[0, "Segment"] == "A-B + A-B-LD"
    assert df.loc[0, "Days"] == 4  # maintenance_time_days dos dois: 3 (Singela) + 1 (Patio Vazio)
    assert df.loc[0, "Action"] == "Singela: Curva · Pátio Vazio (LD): Completa"


def test_segment_role_label_classifies_by_suffix() -> None:
    from railroad_frontend.views.manual import _segment_role_label

    assert _segment_role_label("A-B") == "Singela"
    assert _segment_role_label("A-B-LP") == "Pátio Carregado (LP)"
    assert _segment_role_label("A-B-C") == "Pátio Carregado (LP)"
    assert _segment_role_label("A-B-LD") == "Pátio Vazio (LD)"
    assert _segment_role_label("A-B-V") == "Pátio Vazio (LD)"


def test_manual_route_add_move_form_has_one_radio_per_segment(tmp_path: Path) -> None:
    at = _open_manual_route(tmp_path)

    radios = [r for r in at.radio if r.label.startswith(("Singela", "Pátio"))]
    assert len(radios) >= 1  # ao menos 1 segmento na primeira opcao de movimento disponivel
    for r in radios:
        assert set(r.options) == {"Nada", "Só curva", "Completa"}


def test_manual_route_segment_radio_keys_are_positional_not_segment_name(tmp_path: Path) -> None:
    """Regressao: dentro de um st.form, o selectbox de destino nao rerenderiza
    ate o submit -- se a chave do radio dependesse do NOME do segmento (que
    muda conforme o destino escolhido), trocar o destino sem antes recarregar
    o formulario faria o Streamlit tratar o radio como nunca visto (chave
    nova) e voltar pro default "Nada" no submit, perdendo a escolha do
    usuario em silencio (reportado pelo Bruno: plano gerado "so com
    movimento"). Chave por posicao (0, 1, ...) e estavel entre destinos."""
    at = _open_manual_route(tmp_path)

    radios = [r for r in at.radio if r.label.startswith(("Singela", "Pátio"))]
    assert radios, "esperava pelo menos 1 radio de segmento"
    for idx, r in enumerate(radios):
        assert r.key == f"manual_move_action_{idx}"


def test_kld_reading_label_summarizes_step() -> None:
    from railroad_frontend.views.manual import _kld_reading_label

    assert _kld_reading_label({"kld_reading": {}}) == "—"
    assert _kld_reading_label({"kld_reading": {"A-B": True}}) == "OK"
    assert _kld_reading_label({"kld_reading": {"A-B": True, "A-B-LD": False}}) == "⚠ sem leitura"
    assert _kld_reading_label({"kld_reading": {"A-B": False}}) == "⚠ sem leitura"


def test_manual_route_new_plan_is_default_mode(tmp_path: Path) -> None:
    at = _open_manual_route(tmp_path)
    radios = [r for r in at.radio if r.label == "Plano"]
    assert radios, "esperava um radio 'Plano' no topo da pagina"
    assert radios[0].value == "Novo plano"


def test_manual_route_open_saved_plan_shows_empty_state_message(tmp_path: Path) -> None:
    from railroad_frontend.state.session import MANUAL_SAVED_PLANS_KEY

    at = _open_manual_route(tmp_path)
    # o app carrega data/saved_plans.json real na sessao -- zera explicitamente
    # pra testar o estado "sem plano salvo" independente do que existe em disco.
    at.session_state[MANUAL_SAVED_PLANS_KEY] = {}
    at.run()
    plano_radio = [r for r in at.radio if r.label == "Plano"][0]
    plano_radio.set_value("Abrir plano salvo").run()
    captions = [c.value for c in at.caption]
    assert any("Nenhum plano salvo ainda" in c for c in captions)


def test_manual_route_load_saved_plan_applies_config_and_steps(tmp_path: Path) -> None:
    from railroad_frontend.state.session import MANUAL_CONFIG_KEY, MANUAL_PLAN_KEY, MANUAL_SAVED_PLANS_KEY

    at = _open_manual_route(tmp_path)
    loaded_config = {
        "start_station": "B", "facing_station": "C",
        "start_year": 2030, "end_year": 2031, "second_kld": True,
    }
    at.session_state[MANUAL_SAVED_PLANS_KEY] = {
        "Meu Plano": {"config": loaded_config, "steps": [{"mode": "turn"}]}
    }
    at.run()

    plano_radio = [r for r in at.radio if r.label == "Plano"][0]
    plano_radio.set_value("Abrir plano salvo").run()

    select = [s for s in at.selectbox if s.label == "Plano salvo"][0]
    select.set_value("Meu Plano").run()

    load_btn = [b for b in at.button if b.label == "📂 Carregar"][0]
    load_btn.click().run()

    assert not at.exception
    assert at.session_state[MANUAL_CONFIG_KEY] == loaded_config
    assert at.session_state[MANUAL_PLAN_KEY] == [{"mode": "turn"}]
