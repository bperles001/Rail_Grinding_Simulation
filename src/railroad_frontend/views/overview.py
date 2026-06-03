"""Overview page rendering for the Streamlit dashboard."""
from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

from railroad_frontend.components.ui_components import (
    render_metric_card,
    render_status_banner,
)


def render_overview_page(
    schedule_summary: pd.DataFrame,
    *,
    render_schedule_network_alert: Callable[[], None],
    network_figure_factory: Callable[[], Any],
    render_matplotlib_image: Callable[..., Optional[bytes]],
) -> None:
    """Render the overview tab combining schedule stats and the network sketch."""
    st.markdown('<div class="page-header"><h2>📊 System Overview</h2></div>', unsafe_allow_html=True)
    render_schedule_network_alert()
    
    # Status banner
    render_status_banner(
        "✓ All systems operational. Ready for maintenance planning.",
        status="success",
        icon="✓"
    )
    
    st.markdown(
        """
        This dashboard bundles the MTBT schedule explorer, an automated simulation pass, and
        quick visualizations so planners can switch tools without leaving the browser.
        """
    )
    
    # Calculate metrics
    total_segments = len(schedule_summary)
    total_mtbt = schedule_summary["Total MTBT"].sum()
    total_initial = schedule_summary["Initial Load"].sum()
    
    # Top 5 segments for trend analysis
    top_segments = schedule_summary.nlargest(5, "Total MTBT")
    avg_mtbt_per_segment = total_mtbt / total_segments if total_segments > 0 else 0
    
    st.markdown("### 📈 Key Metrics")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        render_metric_card(
            "Segments Tracked",
            f"{total_segments}",
            help_text="Total railroad segments in the network"
        )
    
    with col2:
        render_metric_card(
            "Total Yearly MTBT",
            f"{total_mtbt:,.0f}",
            delta=f"Avg: {avg_mtbt_per_segment:,.0f} per segment",
            delta_type="neutral",
            help_text="Cumulative maintenance burden across all segments"
        )
    
    with col3:
        render_metric_card(
            "Initial Load Sum",
            f"{total_initial:,.0f}",
            help_text="Starting wear condition for all segments"
        )
    
    st.markdown("### 🗺️ Network Visualization")
    render_matplotlib_image(network_figure_factory(), alt_text="Network sketch")
