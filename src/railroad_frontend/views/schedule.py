"""Schedule explorer view components."""
from __future__ import annotations

from typing import Callable

import pandas as pd
import streamlit as st


def render_schedule_page(
    schedule_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    *,
    render_schedule_network_alert: Callable[[], None],
) -> None:
    """Render the MTBT schedule explorer table and supporting visuals."""
    st.subheader("MTBT schedule explorer")
    render_schedule_network_alert()
    st.caption("Preview the active CSV and inspect per-segment load totals.")
    st.dataframe(schedule_df, use_container_width=True)
    st.markdown("### Highest MTBT demand")
    top5 = summary_df.head(5).set_index("Segment Name")["Total MTBT"]
    st.bar_chart(top5)
