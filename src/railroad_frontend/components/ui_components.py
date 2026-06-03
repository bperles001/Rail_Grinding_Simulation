"""Enhanced UI components for the Railroad Maintenance Simulator dashboard.

RUMO Brand Colors (from brandbook.rumolog.com):
- Primary Blue: #003865 (Azul)
- Light Blue: #32A6E6 (Azul-claro)
- Green: #1E9F7F (Verde)
- Light Green: #7FE06C (Verde-claro)
- Yellow: #FBD300 (Amarelo - secondary, warm accent)
- Orange: #F78344 (Laranja - secondary)
- Purple: #9F4BB9 (Roxo - use sparingly)
- Gray: #BDCCD4 (Cinza)
- Gray Scale: #F2F5F6, #E5EBEE, #D7E0E5, #CAD6DD

Typography: Cera Pro (fallback: Verdana, sans-serif)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# RUMO Brand Color Constants
RUMO_BLUE = "#003865"
RUMO_BLUE_LIGHT = "#32A6E6"
RUMO_GREEN = "#1E9F7F"
RUMO_GREEN_LIGHT = "#7FE06C"
RUMO_YELLOW = "#FBD300"
RUMO_ORANGE = "#F78344"
RUMO_PURPLE = "#9F4BB9"
RUMO_GRAY = "#BDCCD4"
RUMO_GRAY_LIGHT = "#F2F5F6"
RUMO_GRAY_MEDIUM = "#E5EBEE"
RUMO_GRAY_DARK = "#CAD6DD"


def inject_custom_css() -> None:
    """Inject custom CSS for enhanced visual styling with RUMO branding."""
    st.markdown(
        """
        <style>
        /* ============================================
           RUMO BRAND COLORS & VARIABLES
           ============================================ */
        :root {
            --rumo-blue: #003865;
            --rumo-blue-light: #32A6E6;
            --rumo-green: #1E9F7F;
            --rumo-green-light: #7FE06C;
            --rumo-yellow: #FBD300;
            --rumo-orange: #F78344;
            --rumo-purple: #9F4BB9;
            --rumo-gray: #BDCCD4;
            --rumo-gray-light: #F2F5F6;
            --rumo-gray-medium: #E5EBEE;
            --rumo-gray-dark: #CAD6DD;
            --rumo-white: #FFFFFF;
        }
        
        /* ============================================
           APP-LEVEL LAYOUT STRUCTURE
           ============================================ */
        /* Main content container */
        .main .block-container {
            max-width: 1200px;
            padding: 2rem 3rem;
        }
        
        /* App header bar */
        .app-header {
            background: linear-gradient(135deg, var(--rumo-blue) 0%, #00507a 100%);
            color: white;
            padding: 1rem 2rem;
            margin: -2rem -3rem 2rem -3rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .app-header-title {
            font-size: 1.5rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .app-header-stats {
            display: flex;
            gap: 2rem;
        }
        
        .app-header-stat {
            text-align: center;
        }
        
        .app-header-stat-value {
            font-size: 1.25rem;
            font-weight: 700;
        }
        
        .app-header-stat-label {
            font-size: 0.75rem;
            opacity: 0.8;
            text-transform: uppercase;
        }
        
        /* ============================================
           CARD STYLES WITH RUMO BRANDING
           ============================================ */
        .metric-card {
            background: linear-gradient(135deg, var(--rumo-blue) 0%, var(--rumo-green) 100%);
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0, 56, 101, 0.2);
            color: white;
            margin-bottom: 1rem;
        }
        
        .info-card {
            background: white;
            padding: 1.5rem;
            border-radius: 12px;
            border-left: 4px solid var(--rumo-blue-light);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            margin-bottom: 1rem;
        }
        
        .success-card {
            background: #e6f7f3;
            padding: 1.5rem;
            border-radius: 12px;
            border-left: 4px solid var(--rumo-green);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            margin-bottom: 1rem;
        }
        
        .warning-card {
            background: #fef8e6;
            padding: 1.5rem;
            border-radius: 12px;
            border-left: 4px solid var(--rumo-yellow);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            margin-bottom: 1rem;
        }
        
        .danger-card {
            background: #fef0eb;
            padding: 1.5rem;
            border-radius: 12px;
            border-left: 4px solid var(--rumo-orange);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            margin-bottom: 1rem;
        }
        
        /* Status banner - RUMO styled */
        .status-banner {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .status-banner-success {
            background: #e6f7f3;
            color: var(--rumo-blue);
            border: 1px solid var(--rumo-green);
        }
        
        .status-banner-info {
            background: #e6f2fa;
            color: var(--rumo-blue);
            border: 1px solid var(--rumo-blue-light);
        }
        
        .status-banner-warning {
            background: #fef8e6;
            color: #92400e;
            border: 1px solid var(--rumo-yellow);
        }
        
        .status-banner-danger {
            background: #fef0eb;
            color: #991b1b;
            border: 1px solid var(--rumo-orange);
        }
        
        /* Enhanced metrics - RUMO styled */
        .enhanced-metric {
            background: white;
            padding: 1.25rem;
            border-radius: 10px;
            box-shadow: 0 1px 3px rgba(0, 56, 101, 0.1);
            border-top: 3px solid var(--rumo-blue);
        }
        
        .metric-value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--rumo-blue);
            line-height: 1;
            margin: 0.5rem 0;
        }
        
        .metric-label {
            font-size: 0.875rem;
            color: #6b7280;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .metric-delta {
            font-size: 0.875rem;
            font-weight: 600;
            margin-top: 0.5rem;
        }
        
        .metric-delta-positive {
            color: var(--rumo-green);
        }
        
        .metric-delta-negative {
            color: var(--rumo-orange);
        }
        
        .metric-delta-neutral {
            color: var(--rumo-gray);
        }
        
        /* Workflow stepper - RUMO styled */
        .workflow-stepper {
            display: flex;
            justify-content: space-between;
            margin: 1.5rem 0 2rem 0;
            position: relative;
            background: var(--rumo-gray-light);
            padding: 1.5rem 2rem;
            border-radius: 12px;
        }
        
        .workflow-stepper::before {
            content: '';
            position: absolute;
            top: calc(50% - 1px);
            left: 3rem;
            right: 3rem;
            height: 2px;
            background: var(--rumo-gray-dark);
            z-index: 0;
        }
        
        .workflow-step {
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
            z-index: 1;
            flex: 1;
        }
        
        .workflow-step-circle {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            margin-bottom: 0.5rem;
            background: white;
            border: 2px solid var(--rumo-gray-dark);
            color: var(--rumo-gray);
        }
        
        .workflow-step-active .workflow-step-circle {
            background: var(--rumo-blue);
            border-color: var(--rumo-blue);
            color: white;
        }
        
        .workflow-step-completed .workflow-step-circle {
            background: var(--rumo-green);
            border-color: var(--rumo-green);
            color: white;
        }
        
        .workflow-step-label {
            font-size: 0.75rem;
            color: #6b7280;
            text-align: center;
            max-width: 100px;
        }
        
        .workflow-step-active .workflow-step-label {
            color: var(--rumo-blue);
            font-weight: 600;
        }
        
        /* Improved buttons - RUMO styled */
        .stButton > button {
            border-radius: 8px;
            font-weight: 500;
            transition: all 0.2s;
            font-family: 'Verdana', sans-serif;
        }
        
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(0, 56, 101, 0.15);
        }
        
        /* Button hierarchy - RUMO colors */
        div[data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(135deg, var(--rumo-blue) 0%, #00507a 100%);
            color: white;
            border: none;
            font-weight: 600;
            padding: 0.625rem 1.5rem;
            box-shadow: 0 2px 4px rgba(0, 56, 101, 0.3);
        }
        
        div[data-testid="stButton"] button[kind="primary"]:hover {
            background: linear-gradient(135deg, #00507a 0%, var(--rumo-blue) 100%);
            box-shadow: 0 4px 8px rgba(0, 56, 101, 0.4);
        }
        
        div[data-testid="stButton"] button[kind="secondary"] {
            background: white;
            color: var(--rumo-blue);
            border: 2px solid var(--rumo-blue);
            font-weight: 600;
        }
        
        div[data-testid="stButton"] button[kind="secondary"]:hover {
            background: #e6f2fa;
            border-color: #00507a;
        }
        
        /* Danger/destructive buttons */
        .button-danger button {
            background: white !important;
            color: var(--rumo-orange) !important;
            border: 2px solid var(--rumo-orange) !important;
        }
        
        .button-danger button:hover {
            background: #fef0eb !important;
            border-color: #b91c1c !important;
            color: #b91c1c !important;
        }
        
        /* Button groups */
        .button-group {
            display: flex;
            gap: 0.75rem;
            margin: 1rem 0;
            flex-wrap: wrap;
        }
        
        .button-group-center {
            justify-content: center;
        }
        
        .button-group-right {
            justify-content: flex-end;
        }
        
        /* Data tables - RUMO styled */
        .dataframe {
            border-radius: 8px;
            overflow: hidden;
        }
        
        /* Expander styling - RUMO styled */
        .streamlit-expanderHeader {
            background-color: var(--rumo-gray-light);
            border-radius: 8px;
            font-weight: 600;
            color: var(--rumo-blue);
        }
        
        /* Page header - RUMO styled */
        .page-header {
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid var(--rumo-gray-medium);
        }
        
        /* Empty states - RUMO styled */
        .empty-state {
            text-align: center;
            padding: 3rem 2rem;
            background: var(--rumo-gray-light);
            border-radius: 12px;
            border: 2px dashed var(--rumo-gray-dark);
            margin: 2rem 0;
        }
        
        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            opacity: 0.6;
        }
        
        .empty-state-title {
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--rumo-blue);
            margin-bottom: 0.5rem;
        }
        
        .empty-state-description {
            font-size: 0.95rem;
            color: #6b7280;
            margin-bottom: 1.5rem;
            line-height: 1.6;
        }
        
        /* Help tooltip - RUMO styled */
        .help-tooltip {
            display: inline-block;
            background: var(--rumo-gray-light);
            padding: 0.75rem 1rem;
            border-radius: 8px;
            border-left: 3px solid var(--rumo-blue-light);
            margin: 0.75rem 0;
            font-size: 0.875rem;
            color: var(--rumo-blue);
        }
        
        .help-tooltip-success {
            border-left-color: var(--rumo-green);
            background: #e6f7f3;
        }
        
        /* Getting started box - RUMO styled */
        .getting-started {
            background: linear-gradient(135deg, #e6f2fa 0%, #cce5f7 100%);
            border: 1px solid var(--rumo-blue-light);
            border-radius: 12px;
            padding: 1.5rem;
            margin: 1.5rem 0;
        }
        
        .getting-started-title {
            font-size: 1.125rem;
            font-weight: 600;
            color: var(--rumo-blue);
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .getting-started-steps {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        
        .getting-started-steps li {
            padding: 0.5rem 0;
            color: var(--rumo-blue);
            font-size: 0.95rem;
        }
        
        .getting-started-steps li:before {
            content: "✓ ";
            font-weight: bold;
            margin-right: 0.5rem;
            color: var(--rumo-green);
        }
        
        /* Form sections - RUMO styled */
        .form-section {
            background: white;
            border: 1px solid var(--rumo-gray-dark);
            border-radius: 12px;
            padding: 1.5rem;
            margin: 1.5rem 0;
            box-shadow: 0 1px 3px rgba(0, 56, 101, 0.05);
        }
        
        .form-section-title {
            font-size: 1.125rem;
            font-weight: 600;
            color: var(--rumo-blue);
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 2px solid var(--rumo-gray-light);
        }
        
        .form-group {
            margin-bottom: 1.25rem;
        }
        
        .form-group:last-child {
            margin-bottom: 0;
        }
        
        .form-label {
            display: block;
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--rumo-blue);
            margin-bottom: 0.5rem;
        }
        
        .form-help-text {
            font-size: 0.8125rem;
            color: #6b7280;
            margin-top: 0.375rem;
            line-height: 1.5;
        }
        
        .form-divider {
            height: 1px;
            background: var(--rumo-gray-medium);
            margin: 1.5rem 0;
        }
        
        /* Section headers - RUMO styled */
        .section-header {
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--rumo-blue);
            margin: 2rem 0 1rem 0;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--rumo-gray-medium);
        }
        
        .section-subheader {
            font-size: 1rem;
            font-weight: 600;
            color: var(--rumo-blue);
            margin: 1.5rem 0 0.75rem 0;
        }
        
        /* Sparkline container */
        .sparkline {
            height: 30px;
            margin-top: 0.5rem;
        }
        
        /* ============================================
           VALIDATION & FEEDBACK STYLES
           ============================================ */
        /* Inline validation messages */
        .validation-error {
            background: #fef0eb;
            border-left: 4px solid var(--rumo-orange);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            margin: 0.5rem 0;
            font-size: 0.875rem;
            color: #991b1b;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .validation-warning {
            background: #fef8e6;
            border-left: 4px solid var(--rumo-yellow);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            margin: 0.5rem 0;
            font-size: 0.875rem;
            color: #92400e;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .validation-success {
            background: #e6f7f3;
            border-left: 4px solid var(--rumo-green);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            margin: 0.5rem 0;
            font-size: 0.875rem;
            color: var(--rumo-blue);
            display: flex;
            align-items: center;
            gap: 0.5rem;
            animation: slideInFromLeft 0.3s ease-out;
        }
        
        .validation-info {
            background: #e6f2fa;
            border-left: 4px solid var(--rumo-blue-light);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            margin: 0.5rem 0;
            font-size: 0.875rem;
            color: var(--rumo-blue);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        /* Success animation */
        @keyframes slideInFromLeft {
            from {
                opacity: 0;
                transform: translateX(-10px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
            }
            to {
                opacity: 1;
            }
        }
        
        @keyframes checkmark {
            0% {
                transform: scale(0);
            }
            50% {
                transform: scale(1.2);
            }
            100% {
                transform: scale(1);
            }
        }
        
        /* Field validation states */
        .field-valid {
            border-color: var(--rumo-green) !important;
            background: #f0fdf4 !important;
        }
        
        .field-invalid {
            border-color: var(--rumo-orange) !important;
            background: #fef0eb !important;
        }
        
        /* Success toast with animation */
        .success-toast {
            background: linear-gradient(135deg, var(--rumo-green) 0%, var(--rumo-green-light) 100%);
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(30, 159, 127, 0.3);
            margin: 1rem 0;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-weight: 500;
            animation: slideInFromLeft 0.4s ease-out;
        }
        
        .success-toast-icon {
            font-size: 1.5rem;
            animation: checkmark 0.6s ease-out;
        }
        
        /* Progress tracker */
        .progress-tracker {
            background: white;
            border: 1px solid var(--rumo-gray-dark);
            border-radius: 8px;
            padding: 1rem;
            margin: 1rem 0;
        }
        
        .progress-step {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.5rem 0;
            color: #6b7280;
        }
        
        .progress-step-complete {
            color: var(--rumo-green);
            font-weight: 600;
        }
        
        .progress-step-active {
            color: var(--rumo-blue);
            font-weight: 600;
        }
        
        .progress-step-icon {
            font-size: 1.25rem;
            min-width: 24px;
        }
        
        /* Inline field hint */
        .field-hint {
            font-size: 0.8125rem;
            color: #6b7280;
            margin-top: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }
        
        .field-hint-icon {
            font-size: 0.875rem;
        }
        
        /* ============================================
           LOADING STATES & SKELETON SCREENS
           ============================================ */
        /* Skeleton loading animation */
        @keyframes skeleton-loading {
            0% {
                background-position: -200px 0;
            }
            100% {
                background-position: calc(200px + 100%) 0;
            }
        }
        
        .skeleton {
            background: linear-gradient(
                90deg,
                var(--rumo-gray-light) 0%,
                var(--rumo-gray-medium) 20%,
                var(--rumo-gray-light) 40%,
                var(--rumo-gray-light) 100%
            );
            background-size: 200px 100%;
            animation: skeleton-loading 1.5s ease-in-out infinite;
            border-radius: 4px;
        }
        
        .skeleton-text {
            height: 16px;
            margin: 8px 0;
            border-radius: 4px;
        }
        
        .skeleton-text-large {
            height: 24px;
            margin: 12px 0;
            border-radius: 4px;
        }
        
        .skeleton-card {
            height: 120px;
            border-radius: 12px;
            margin: 1rem 0;
        }
        
        .skeleton-metric {
            height: 80px;
            border-radius: 8px;
        }
        
        /* Loading spinner */
        .loading-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 3rem 2rem;
            gap: 1rem;
        }
        
        .loading-spinner {
            width: 48px;
            height: 48px;
            border: 4px solid var(--rumo-gray-light);
            border-top-color: var(--rumo-blue);
            border-radius: 50%;
            animation: spinner-rotation 0.8s linear infinite;
        }
        
        @keyframes spinner-rotation {
            from {
                transform: rotate(0deg);
            }
            to {
                transform: rotate(360deg);
            }
        }
        
        .loading-text {
            color: var(--rumo-blue);
            font-size: 1rem;
            font-weight: 500;
        }
        
        .loading-subtext {
            color: #6b7280;
            font-size: 0.875rem;
        }
        
        /* Progress bar */
        .progress-bar-container {
            width: 100%;
            background: var(--rumo-gray-light);
            border-radius: 8px;
            height: 24px;
            overflow: hidden;
            position: relative;
            margin: 1rem 0;
            box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1);
        }
        
        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(135deg, var(--rumo-blue) 0%, var(--rumo-blue-light) 100%);
            transition: width 0.3s ease-out;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 0.5rem;
            color: white;
            font-size: 0.75rem;
            font-weight: 600;
        }
        
        .progress-bar-animated {
            animation: progress-pulse 2s ease-in-out infinite;
        }
        
        @keyframes progress-pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.8;
            }
        }
        
        /* Step progress bar */
        .step-progress {
            background: white;
            border: 1px solid var(--rumo-gray-dark);
            border-radius: 8px;
            padding: 1.5rem;
            margin: 1rem 0;
        }
        
        .step-progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        
        .step-progress-title {
            font-size: 1rem;
            font-weight: 600;
            color: var(--rumo-blue);
        }
        
        .step-progress-eta {
            font-size: 0.875rem;
            color: #6b7280;
        }
        
        .step-progress-bar {
            width: 100%;
            height: 8px;
            background: var(--rumo-gray-light);
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 0.5rem;
        }
        
        .step-progress-bar-fill {
            height: 100%;
            background: linear-gradient(135deg, var(--rumo-green) 0%, var(--rumo-green-light) 100%);
            transition: width 0.5s ease-out;
        }
        
        .step-progress-text {
            font-size: 0.875rem;
            color: #6b7280;
            text-align: center;
        }
        
        /* Pulsing indicator */
        .pulse-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            background: var(--rumo-green);
            border-radius: 50%;
            animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }
        
        @keyframes pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.5;
            }
        }
        
        /* ============================================
           RESULT SUMMARY CARDS & KPI DISPLAYS
           ============================================ */
        /* KPI Card */
        .kpi-card {
            background: white;
            border: 1px solid var(--rumo-gray-dark);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0, 56, 101, 0.08);
            transition: transform 0.2s, box-shadow 0.2s;
            margin-bottom: 1rem;
        }
        
        .kpi-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 56, 101, 0.15);
        }
        
        .kpi-card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1rem;
        }
        
        .kpi-card-title {
            font-size: 0.875rem;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .kpi-card-badge {
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.25rem 0.625rem;
            border-radius: 12px;
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }
        
        .kpi-badge-better {
            background: #e6f7f3;
            color: var(--rumo-green);
            border: 1px solid var(--rumo-green);
        }
        
        .kpi-badge-worse {
            background: #fef0eb;
            color: var(--rumo-orange);
            border: 1px solid var(--rumo-orange);
        }
        
        .kpi-badge-neutral {
            background: var(--rumo-gray-light);
            color: #6b7280;
            border: 1px solid var(--rumo-gray-dark);
        }
        
        .kpi-card-value {
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--rumo-blue);
            line-height: 1;
            margin-bottom: 0.5rem;
        }
        
        .kpi-card-change {
            font-size: 0.875rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }
        
        .kpi-change-positive {
            color: var(--rumo-green);
        }
        
        .kpi-change-negative {
            color: var(--rumo-orange);
        }
        
        .kpi-change-neutral {
            color: #6b7280;
        }
        
        .kpi-card-subtitle {
            font-size: 0.875rem;
            color: #6b7280;
            margin-top: 0.5rem;
        }
        
        /* Result Summary Container */
        .result-summary {
            background: linear-gradient(135deg, var(--rumo-blue) 0%, #00507a 100%);
            color: white;
            border-radius: 12px;
            padding: 2rem;
            margin: 1.5rem 0;
            box-shadow: 0 4px 12px rgba(0, 56, 101, 0.3);
        }
        
        .result-summary-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .result-summary-title {
            font-size: 1.5rem;
            font-weight: 700;
        }
        
        .result-summary-actions {
            display: flex;
            gap: 0.5rem;
        }
        
        .result-summary-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 1rem;
        }
        
        .result-metric {
            text-align: center;
            padding: 1rem;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            backdrop-filter: blur(10px);
        }
        
        .result-metric-value {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 0.5rem;
        }
        
        .result-metric-label {
            font-size: 0.875rem;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        /* Comparison Badge */
        .comparison-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.375rem;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.875rem;
            font-weight: 600;
            margin: 0.25rem;
        }
        
        .comparison-better {
            background: linear-gradient(135deg, var(--rumo-green) 0%, var(--rumo-green-light) 100%);
            color: white;
            box-shadow: 0 2px 6px rgba(30, 159, 127, 0.3);
        }
        
        .comparison-worse {
            background: linear-gradient(135deg, var(--rumo-orange) 0%, #ff9f6e 100%);
            color: white;
            box-shadow: 0 2px 6px rgba(247, 131, 68, 0.3);
        }
        
        .comparison-equal {
            background: var(--rumo-gray-medium);
            color: var(--rumo-blue);
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        }
        
        .comparison-icon {
            font-size: 1rem;
        }
        
        /* Collapsible details */
        .details-toggle {
            cursor: pointer;
            padding: 0.75rem 1rem;
            background: var(--rumo-gray-light);
            border: 1px solid var(--rumo-gray-dark);
            border-radius: 8px;
            margin: 1rem 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s;
        }
        
        .details-toggle:hover {
            background: var(--rumo-gray-medium);
        }
        
        .details-toggle-text {
            font-weight: 600;
            color: var(--rumo-blue);
        }
        
        .details-content {
            padding: 1rem;
            background: white;
            border: 1px solid var(--rumo-gray-dark);
            border-top: none;
            border-radius: 0 0 8px 8px;
        }
        
        /* ============================================
           ACCESSIBILITY & KEYBOARD NAVIGATION
           ============================================ */
        /* Focus styles for keyboard navigation */
        button:focus-visible,
        a:focus-visible,
        input:focus-visible,
        select:focus-visible,
        textarea:focus-visible,
        [tabindex]:focus-visible {
            outline: 3px solid var(--rumo-blue-light) !important;
            outline-offset: 2px !important;
            box-shadow: 0 0 0 4px rgba(50, 166, 230, 0.2) !important;
        }
        
        /* Skip to main content link */
        .skip-to-main {
            position: absolute;
            left: -9999px;
            z-index: 999;
            padding: 1rem 2rem;
            background: var(--rumo-blue);
            color: white;
            text-decoration: none;
            font-weight: 600;
            border-radius: 0 0 8px 0;
        }
        
        .skip-to-main:focus {
            left: 0;
            top: 0;
        }
        
        /* Keyboard shortcut hints */
        .keyboard-hint {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.125rem 0.375rem;
            background: var(--rumo-gray-light);
            border: 1px solid var(--rumo-gray-dark);
            border-radius: 4px;
            font-family: monospace;
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--rumo-blue);
        }
        
        /* ARIA live regions for screen readers */
        .sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            white-space: nowrap;
            border: 0;
        }
        
        /* High contrast mode support */
        @media (prefers-contrast: high) {
            .metric-card,
            .kpi-card,
            .result-summary {
                border-width: 2px !important;
            }
            
            button,
            .stButton > button {
                border: 2px solid currentColor !important;
            }
        }
        
        /* Reduced motion support */
        @media (prefers-reduced-motion: reduce) {
            *,
            *::before,
            *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }
        
        /* Dark mode improvements (if enabled) */
        @media (prefers-color-scheme: dark) {
            :root {
                --rumo-gray-light: #1a1a1a;
                --rumo-gray-medium: #2a2a2a;
                --rumo-gray-dark: #3a3a3a;
            }
        }
        
        /* ============================================
           ACCESSIBLE COMPONENTS STYLES
           ============================================ */
        /* Alert banners */
        .alert-banner {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 1rem;
            border-radius: 8px;
            margin: 1rem 0;
            border-left: 4px solid;
        }
        
        .alert-info {
            background: #E3F2FD;
            border-color: var(--rumo-blue-light);
            color: var(--rumo-blue);
        }
        
        .alert-success {
            background: #E8F5E9;
            border-color: var(--rumo-green);
            color: #1B5E20;
        }
        
        .alert-warning {
            background: #FFF3E0;
            border-color: var(--rumo-orange);
            color: #E65100;
        }
        
        .alert-error {
            background: #FFEBEE;
            border-color: #C62828;
            color: #B71C1C;
        }
        
        .alert-icon {
            font-size: 1.5rem;
            flex-shrink: 0;
        }
        
        .alert-message {
            flex: 1;
            font-weight: 500;
        }
        
        .alert-dismiss {
            background: transparent;
            border: none;
            font-size: 1.5rem;
            cursor: pointer;
            color: inherit;
            opacity: 0.6;
            transition: opacity 0.2s;
        }
        
        .alert-dismiss:hover {
            opacity: 1;
        }
        
        /* Accessible form fields */
        .form-field {
            margin-bottom: 1.5rem;
        }
        
        .form-field.has-error .field-input {
            border-color: #C62828;
            background: #FFEBEE;
        }
        
        .field-label {
            display: block;
            font-weight: 600;
            margin-bottom: 0.5rem;
            color: var(--rumo-blue);
        }
        
        .required-indicator {
            color: #C62828;
            margin-left: 0.25rem;
        }
        
        .field-input {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid var(--rumo-gray-dark);
            border-radius: 6px;
            font-size: 1rem;
            transition: all 0.2s;
        }
        
        .field-input:focus {
            outline: none;
            border-color: var(--rumo-blue-light);
            box-shadow: 0 0 0 3px rgba(50, 166, 230, 0.2);
        }
        
        .field-help {
            margin-top: 0.5rem;
            font-size: 0.875rem;
            color: #666;
        }
        
        .field-error {
            margin-top: 0.5rem;
            font-size: 0.875rem;
            color: #C62828;
            font-weight: 500;
        }
        
        /* Accessible buttons */
        .accessible-button {
            padding: 0.75rem 1.5rem;
            background: var(--rumo-blue);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .accessible-button:hover:not(:disabled) {
            background: var(--rumo-blue-light);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        }
        
        .accessible-button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        /* Tab panels */
        .tabs-container {
            margin: 1rem 0;
        }
        
        .tab-list {
            display: flex;
            gap: 0.5rem;
            border-bottom: 2px solid var(--rumo-gray-dark);
            margin-bottom: 1rem;
        }
        
        .tab-button {
            padding: 0.75rem 1.5rem;
            background: transparent;
            border: none;
            border-bottom: 3px solid transparent;
            font-size: 1rem;
            font-weight: 600;
            color: #666;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .tab-button:hover {
            color: var(--rumo-blue);
            background: var(--rumo-gray-light);
        }
        
        .tab-button.tab-active {
            color: var(--rumo-blue);
            border-bottom-color: var(--rumo-blue);
        }
        
        .tab-panel {
            padding: 1rem;
            animation: fadeIn 0.3s;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        /* Progress with ARIA */
        .progress-bar-container {
            position: relative;
            width: 100%;
            height: 2rem;
            background: var(--rumo-gray-light);
            border-radius: 8px;
            overflow: hidden;
            margin: 1rem 0;
        }
        
        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--rumo-blue) 0%, var(--rumo-blue-light) 100%);
            transition: width 0.3s ease;
        }
        
        .progress-bar-text {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-weight: 700;
            color: var(--rumo-blue);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_status_banner(
    message: str,
    status: str = "info",
    icon: str = "",
) -> None:
    """Render a status banner at the top of the page.
    
    Args:
        message: The message to display in the banner.
        status: One of 'success', 'info', 'warning', 'danger'.
        icon: Optional emoji or icon to display.
    """
    status_class = f"status-banner status-banner-{status}"
    icon_html = f"<span style='font-size: 1.25rem;'>{icon}</span>" if icon else ""
    
    st.markdown(
        f"""
        <div class="{status_class}">
            {icon_html}
            <span>{message}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(
    label: str,
    value: str,
    delta: Optional[str] = None,
    delta_type: str = "neutral",
    help_text: Optional[str] = None,
) -> None:
    """Render an enhanced metric card with optional delta indicator.
    
    Args:
        label: The metric label.
        value: The metric value to display.
        delta: Optional change indicator (e.g., "+15%", "-3 days").
        delta_type: One of 'positive', 'negative', 'neutral'.
        help_text: Optional tooltip text.
    """
    delta_class = f"metric-delta metric-delta-{delta_type}"
    delta_html = f'<div class="{delta_class}">{delta}</div>' if delta else ""
    help_html = f'<div style="font-size: 0.75rem; color: #9ca3af; margin-top: 0.25rem;">{help_text}</div>' if help_text else ""
    
    st.markdown(
        f"""
        <div class="enhanced-metric">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            {delta_html}
            {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_workflow_stepper(
    steps: List[Tuple[str, str]],
    current_step: int,
) -> None:
    """Render a visual workflow stepper showing progress through the application.
    
    Args:
        steps: List of (step_name, step_label) tuples.
        current_step: Zero-based index of the current step (0 = first step).
    """
    step_html = []
    for idx, (name, label) in enumerate(steps):
        if idx < current_step:
            step_class = "workflow-step workflow-step-completed"
            icon = "✓"
        elif idx == current_step:
            step_class = "workflow-step workflow-step-active"
            icon = str(idx + 1)
        else:
            step_class = "workflow-step"
            icon = str(idx + 1)
        
        step_html.append(
            f'<div class="{step_class}">'
            f'<div class="workflow-step-circle">{icon}</div>'
            f'<div class="workflow-step-label">{label}</div>'
            f'</div>'
        )
    
    html_content = f'<div class="workflow-stepper">{"".join(step_html)}</div>'
    st.markdown(html_content, unsafe_allow_html=True)


def render_card(
    content: str,
    card_type: str = "info",
    title: Optional[str] = None,
) -> None:
    """Render a styled card container.
    
    Args:
        content: HTML or text content to display in the card.
        card_type: One of 'info', 'success', 'warning', 'danger', 'metric'.
        title: Optional title for the card.
    """
    title_html = f"<h4 style='margin: 0 0 0.75rem 0;'>{title}</h4>" if title else ""
    
    st.markdown(
        f"""
        <div class="{card_type}-card">
            {title_html}
            <div>{content}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_form_section_start(title: str) -> None:
    """Render the start of a form section container.
    
    Args:
        title: Section title.
    """
    st.markdown(
        f"""
        <div class="form-section">
            <div class="form-section-title">{title}</div>
        """,
        unsafe_allow_html=True,
    )


def render_form_section_end() -> None:
    """Close a form section container."""
    st.markdown('</div>', unsafe_allow_html=True)


def render_section_header(title: str, subtitle: bool = False) -> None:
    """Render a section header.
    
    Args:
        title: Section title text.
        subtitle: If True, render as subheader with less emphasis.
    """
    css_class = "section-subheader" if subtitle else "section-header"
    st.markdown(f'<div class="{css_class}">{title}</div>', unsafe_allow_html=True)


def render_form_divider() -> None:
    """Render a horizontal divider between form groups."""
    st.markdown('<div class="form-divider"></div>', unsafe_allow_html=True)


def render_empty_state(
    icon: str,
    title: str,
    description: str,
    action_text: str = "",
) -> None:
    """Render an empty state with icon, title, and description.
    
    Args:
        icon: Emoji or icon to display.
        title: Main empty state title.
        description: Helpful description text.
        action_text: Optional action guidance text.
    """
    action_html = f'<div style="margin-top: 1rem; font-size: 0.875rem; color: #9ca3af;">{action_text}</div>' if action_text else ""
    
    st.markdown(
        f"""
        <div class="empty-state">
            <div class="empty-state-icon">{icon}</div>
            <div class="empty-state-title">{title}</div>
            <div class="empty-state-description">{description}</div>
            {action_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_help_tooltip(message: str, type: str = "info") -> None:
    """Render an inline help tooltip.
    
    Args:
        message: Help message to display.
        type: One of 'info' or 'success'.
    """
    css_class = f"help-tooltip help-tooltip-{type}" if type == "success" else "help-tooltip"
    st.markdown(
        f'<div class="{css_class}">💡 {message}</div>',
        unsafe_allow_html=True,
    )


def render_getting_started(title: str, steps: List[str]) -> None:
    """Render a getting started guide box.
    
    Args:
        title: Title for the getting started section.
        steps: List of step descriptions.
    """
    steps_html = "".join([f"<li>{step}</li>" for step in steps])
    
    st.markdown(
        f"""
        <div class="getting-started">
            <div class="getting-started-title">
                🚀 {title}
            </div>
            <ul class="getting-started-steps">
                {steps_html}
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def create_sparkline_data(values: List[float]) -> str:
    """Create a simple SVG sparkline from a list of values.
    
    Args:
        values: List of numeric values to plot.
    
    Returns:
        SVG string representing the sparkline.
    """
    if not values or len(values) < 2:
        return ""
    
    min_val = min(values)
    max_val = max(values)
    value_range = max_val - min_val if max_val != min_val else 1
    
    width = 100
    height = 30
    points = []
    
    for idx, val in enumerate(values):
        x = (idx / (len(values) - 1)) * width
        y = height - ((val - min_val) / value_range) * height
        points.append(f"{x},{y}")
    
    polyline = " ".join(points)
    
    return f"""
    <svg width="{width}" height="{height}" class="sparkline">
        <polyline
            fill="none"
            stroke="{RUMO_BLUE_LIGHT}"
            stroke-width="2"
            points="{polyline}"
        />
    </svg>
    """


def render_page_header(
    title: str,
    icon: str = "",
    description: str = "",
    workflow_step: str = "",
) -> None:
    """Render a consistent professional page header with RUMO branding.
    
    Args:
        title: Main page title.
        icon: Emoji or icon to display before title.
        description: Brief description of the page's purpose.
        workflow_step: Current workflow step (e.g., "Step 1 of 4: Configure Network").
    """
    icon_html = f'<span style="font-size: 2rem; margin-right: 0.75rem;">{icon}</span>' if icon else ""
    workflow_html = ""
    if workflow_step:
        workflow_html = f'<div style="font-size: 0.875rem; color: {RUMO_GRAY}; font-weight: 500; margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 0.05em;">{workflow_step}</div>'
    
    description_html = ""
    if description:
        description_html = f'<p style="font-size: 1rem; color: #6b7280; margin-top: 0.5rem; margin-bottom: 0;">{description}</p>'
    
    st.markdown(
        f"""
        <div class="page-header">
            {workflow_html}
            <div style="display: flex; align-items: center;">
                {icon_html}
                <h1 style="margin: 0; font-size: 2rem; font-weight: 700; color: {RUMO_BLUE};">{title}</h1>
            </div>
            {description_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_validation_message(
    message: str,
    type: str = "error",
    icon: str = "",
) -> None:
    """Render an inline validation message near a form field.
    
    Args:
        message: Validation message to display.
        type: One of 'error', 'warning', 'success', 'info'.
        icon: Optional emoji or icon to display.
    """
    default_icons = {
        "error": "❌",
        "warning": "⚠️",
        "success": "✅",
        "info": "ℹ️",
    }
    display_icon = icon or default_icons.get(type, "")
    css_class = f"validation-{type}"
    
    st.markdown(
        f"""
        <div class="{css_class}">
            <span style="font-size: 1rem;">{display_icon}</span>
            <span>{message}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_success_toast(
    message: str,
    icon: str = "✅",
    duration: Optional[int] = None,
) -> None:
    """Render an animated success toast notification.
    
    Args:
        message: Success message to display.
        icon: Icon to display (default: checkmark).
        duration: Optional duration hint (not implemented, for future use).
    """
    st.markdown(
        f"""
        <div class="success-toast">
            <span class="success-toast-icon">{icon}</span>
            <span>{message}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_field_hint(message: str, icon: str = "💡") -> None:
    """Render a helpful hint below a form field.
    
    Args:
        message: Hint message to display.
        icon: Icon to display.
    """
    st.markdown(
        f"""
        <div class="field-hint">
            <span class="field-hint-icon">{icon}</span>
            <span>{message}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_progress_tracker(
    steps: List[Tuple[str, str]],
    current_step: int,
) -> None:
    """Render a progress tracker for multi-step operations.
    
    Args:
        steps: List of (step_name, step_description) tuples.
        current_step: Zero-based index of current step (0 = first step).
    """
    steps_html = []
    for idx, (name, description) in enumerate(steps):
        if idx < current_step:
            icon = "✅"
            css_class = "progress-step progress-step-complete"
        elif idx == current_step:
            icon = "⏳"
            css_class = "progress-step progress-step-active"
        else:
            icon = "⭕"
            css_class = "progress-step"
        
        steps_html.append(
            f"""
            <div class="{css_class}">
                <span class="progress-step-icon">{icon}</span>
                <span><strong>{name}:</strong> {description}</span>
            </div>
            """
        )
    
    st.markdown(
        f"""
        <div class="progress-tracker">
            {''.join(steps_html)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def validate_required_field(value: Any, field_name: str) -> Optional[str]:
    """Validate that a required field has a value.
    
    Args:
        value: Field value to validate.
        field_name: Name of the field for error messages.
    
    Returns:
        Error message if invalid, None if valid.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"{field_name} is required"
    return None


def validate_numeric_range(
    value: Any,
    field_name: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> Optional[str]:
    """Validate that a numeric field is within a specified range.
    
    Args:
        value: Field value to validate.
        field_name: Name of the field for error messages.
        min_value: Minimum allowed value (inclusive).
        max_value: Maximum allowed value (inclusive).
    
    Returns:
        Error message if invalid, None if valid.
    """
    try:
        num_value = float(value)
    except (TypeError, ValueError):
        return f"{field_name} must be a valid number"
    
    if min_value is not None and num_value < min_value:
        return f"{field_name} must be at least {min_value}"
    
    if max_value is not None and num_value > max_value:
        return f"{field_name} must be at most {max_value}"
    
    return None


def validate_unique_in_list(
    value: str,
    existing_values: List[str],
    field_name: str,
) -> Optional[str]:
    """Validate that a value is unique in a list.
    
    Args:
        value: Value to check for uniqueness.
        existing_values: List of existing values.
        field_name: Name of the field for error messages.
    
    Returns:
        Error message if not unique, None if valid.
    """
    if value in existing_values:
        return f"{field_name} '{value}' already exists"
    return None


def render_skeleton_card() -> None:
    """Render a skeleton loading placeholder for a card."""
    st.markdown(
        '<div class="skeleton skeleton-card"></div>',
        unsafe_allow_html=True,
    )


def render_skeleton_metric() -> None:
    """Render a skeleton loading placeholder for a metric."""
    st.markdown(
        '<div class="skeleton skeleton-metric"></div>',
        unsafe_allow_html=True,
    )


def render_skeleton_text(lines: int = 3, large: bool = False) -> None:
    """Render skeleton loading placeholders for text lines.
    
    Args:
        lines: Number of skeleton lines to render.
        large: If True, render larger skeleton lines.
    """
    css_class = "skeleton skeleton-text-large" if large else "skeleton skeleton-text"
    skeleton_html = "".join([f'<div class="{css_class}"></div>' for _ in range(lines)])
    st.markdown(skeleton_html, unsafe_allow_html=True)


def render_loading_spinner(
    message: str = "Loading...",
    subtext: Optional[str] = None,
) -> None:
    """Render a loading spinner with message.
    
    Args:
        message: Main loading message.
        subtext: Optional secondary message.
    """
    subtext_html = f'<div class="loading-subtext">{subtext}</div>' if subtext else ""
    
    st.markdown(
        f"""
        <div class="loading-container">
            <div class="loading-spinner"></div>
            <div class="loading-text">{message}</div>
            {subtext_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_progress_bar(
    progress: float,
    message: Optional[str] = None,
    animated: bool = False,
) -> None:
    """Render a progress bar.
    
    Args:
        progress: Progress value between 0 and 100.
        message: Optional message to display in the progress bar.
        animated: If True, add pulsing animation.
    """
    progress = max(0, min(100, progress))
    animated_class = "progress-bar-animated" if animated else ""
    message_html = f"{int(progress)}%" if not message else message
    
    st.markdown(
        f"""
        <div class="progress-bar-container">
            <div class="progress-bar-fill {animated_class}" style="width: {progress}%;">
                {message_html if progress > 10 else ""}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_step_progress(
    current_step: int,
    total_steps: int,
    step_name: str,
    eta_seconds: Optional[int] = None,
) -> None:
    """Render a step-by-step progress indicator with ETA.
    
    Args:
        current_step: Current step number (1-based).
        total_steps: Total number of steps.
        step_name: Name of the current step.
        eta_seconds: Estimated time remaining in seconds.
    """
    progress = (current_step / total_steps) * 100 if total_steps > 0 else 0
    
    eta_html = ""
    if eta_seconds is not None:
        if eta_seconds < 60:
            eta_text = f"~{eta_seconds}s remaining"
        else:
            minutes = eta_seconds // 60
            eta_text = f"~{minutes}m remaining"
        eta_html = f'<div class="step-progress-eta">{eta_text}</div>'
    
    st.markdown(
        f"""
        <div class="step-progress">
            <div class="step-progress-header">
                <div class="step-progress-title">
                    <span class="pulse-indicator"></span>&nbsp;&nbsp;{step_name}
                </div>
                {eta_html}
            </div>
            <div class="step-progress-bar">
                <div class="step-progress-bar-fill" style="width: {progress}%;"></div>
            </div>
            <div class="step-progress-text">Step {current_step} of {total_steps}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_card(
    title: str,
    value: str,
    change: Optional[str] = None,
    change_type: str = "neutral",
    badge: Optional[str] = None,
    badge_type: str = "neutral",
    subtitle: Optional[str] = None,
) -> None:
    """Render a KPI card with optional comparison badge.
    
    Args:
        title: KPI title/label.
        value: Main KPI value to display.
        change: Optional change indicator (e.g., "+15%", "-3 days").
        change_type: One of 'positive', 'negative', 'neutral'.
        badge: Optional badge text (e.g., "✓ Better", "⚠ Worse").
        badge_type: One of 'better', 'worse', 'neutral'.
        subtitle: Optional subtitle or description.
    """
    badge_html = ""
    if badge:
        badge_css = f"kpi-badge-{badge_type}"
        badge_html = f'<div class="kpi-card-badge {badge_css}">{badge}</div>'
    
    change_html = ""
    if change:
        change_css = f"kpi-change-{change_type}"
        change_html = f'<div class="kpi-card-change {change_css}">{change}</div>'
    
    subtitle_html = ""
    if subtitle:
        subtitle_html = f'<div class="kpi-card-subtitle">{subtitle}</div>'
    
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-card-header">
                <div class="kpi-card-title">{title}</div>
                {badge_html}
            </div>
            <div class="kpi-card-value">{value}</div>
            {change_html}
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_result_summary(
    title: str,
    metrics: List[Tuple[str, str]],
    show_actions: bool = True,
) -> None:
    """Render a prominent result summary card with key metrics.
    
    Args:
        title: Summary title.
        metrics: List of (label, value) tuples for metrics to display.
        show_actions: Whether to show action buttons.
    """
    metrics_html = []
    for label, value in metrics:
        metrics_html.append(
            f"""
            <div class="result-metric">
                <div class="result-metric-value">{value}</div>
                <div class="result-metric-label">{label}</div>
            </div>
            """
        )
    
    actions_html = ""
    if show_actions:
        actions_html = """
        <div class="result-summary-actions">
            <span style="font-size: 0.875rem; opacity: 0.9;">📥 Export available below</span>
        </div>
        """
    
    html_content = f"""
    <div class="result-summary">
        <div class="result-summary-header">
            <div class="result-summary-title">{title}</div>
            {actions_html}
        </div>
        <div class="result-summary-metrics">
            {''.join(metrics_html)}
        </div>
    </div>
    """
    
    st.markdown(html_content, unsafe_allow_html=True)


def render_comparison_badge(
    text: str,
    comparison_type: str = "neutral",
    icon: str = "",
) -> None:
    """Render a comparison badge (Better/Worse/Equal).
    
    Args:
        text: Badge text.
        comparison_type: One of 'better', 'worse', 'equal'.
        icon: Optional icon/emoji.
    """
    default_icons = {
        "better": "✓",
        "worse": "⚠",
        "equal": "=",
    }
    display_icon = icon or default_icons.get(comparison_type, "")
    css_class = f"comparison-{comparison_type}"
    
    st.markdown(
        f"""
        <div class="comparison-badge {css_class}">
            <span class="comparison-icon">{display_icon}</span>
            <span>{text}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


__all__ = [
    "inject_custom_css",
    "render_status_banner",
    "render_metric_card",
    "render_workflow_stepper",
    "render_card",
    "create_sparkline_data",
    "render_page_header",
    "render_empty_state",
    "render_help_tooltip",
    "render_getting_started",
    "render_form_section_start",
    "render_form_section_end",
    "render_section_header",
    "render_form_divider",
    "render_validation_message",
    "render_success_toast",
    "render_field_hint",
    "render_progress_tracker",
    "validate_required_field",
    "validate_numeric_range",
    "validate_unique_in_list",
    "render_skeleton_card",
    "render_skeleton_metric",
    "render_skeleton_text",
    "render_loading_spinner",
    "render_progress_bar",
    "render_step_progress",
    "render_kpi_card",
    "render_result_summary",
    "render_comparison_badge",
    "render_keyboard_shortcuts_guide",
    "render_accessibility_widget",
    "render_aria_live_region",
    "render_skip_navigation",
    "render_accessible_button",
    "render_landmark_section",
    "render_progress_with_aria",
    "render_tab_panel",
    "render_alert_banner",
    "render_form_field_with_aria",
]


def render_keyboard_shortcuts_guide() -> None:
    """Render a keyboard shortcuts reference guide."""
    st.markdown(
        """
        <div class="keyboard-shortcuts-guide">
            <h4 style="color: #003865; margin-bottom: 1rem;">⌨️ Keyboard Shortcuts</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;">
                <div>
                    <p><kbd class="keyboard-hint">Tab</kbd> Navigate forward</p>
                    <p><kbd class="keyboard-hint">Shift</kbd> + <kbd class="keyboard-hint">Tab</kbd> Navigate backward</p>
                    <p><kbd class="keyboard-hint">Enter</kbd> Activate button/link</p>
                </div>
                <div>
                    <p><kbd class="keyboard-hint">Ctrl</kbd> + <kbd class="keyboard-hint">S</kbd> Save current plan</p>
                    <p><kbd class="keyboard-hint">Ctrl</kbd> + <kbd class="keyboard-hint">E</kbd> Export results</p>
                    <p><kbd class="keyboard-hint">Ctrl</kbd> + <kbd class="keyboard-hint">R</kbd> Run simulation</p>
                </div>
                <div>
                    <p><kbd class="keyboard-hint">Esc</kbd> Close dialogs</p>
                    <p><kbd class="keyboard-hint">?</kbd> Show this help</p>
                    <p><kbd class="keyboard-hint">/</kbd> Focus search</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_accessibility_widget() -> None:
    """Render accessibility controls widget."""
    with st.expander("♿ Accessibility Options", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Display Options**")
            high_contrast = st.checkbox(
                "High Contrast Mode",
                help="Increase contrast for better visibility",
                key="accessibility_high_contrast"
            )
            reduced_motion = st.checkbox(
                "Reduce Motion",
                help="Minimize animations and transitions",
                key="accessibility_reduced_motion"
            )
            
        with col2:
            st.markdown("**Text Options**")
            font_size = st.select_slider(
                "Font Size",
                options=["Small", "Medium", "Large", "Extra Large"],
                value="Medium",
                help="Adjust text size for better readability",
                key="accessibility_font_size"
            )
        
        # Apply accessibility preferences
        if high_contrast:
            st.markdown(
                """
                <style>
                body { filter: contrast(1.2); }
                </style>
                """,
                unsafe_allow_html=True
            )
        
        if reduced_motion:
            st.markdown(
                """
                <style>
                * {
                    animation-duration: 0.01ms !important;
                    transition-duration: 0.01ms !important;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
        
        if font_size == "Large":
            st.markdown(
                """
                <style>
                body { font-size: 18px; }
                </style>
                """,
                unsafe_allow_html=True
            )
        elif font_size == "Extra Large":
            st.markdown(
                """
                <style>
                body { font-size: 20px; }
                </style>
                """,
                unsafe_allow_html=True
            )
        elif font_size == "Small":
            st.markdown(
                """
                <style>
                body { font-size: 13px; }
                </style>
                """,
                unsafe_allow_html=True
            )
        
        # Keyboard shortcuts guide
        st.markdown("---")
        render_keyboard_shortcuts_guide()


def render_aria_live_region(message: str, priority: str = "polite") -> None:
    """Render an ARIA live region for screen reader announcements.
    
    Args:
        message: Message to announce to screen readers.
        priority: 'polite' (wait) or 'assertive' (interrupt).
    """
    st.markdown(
        f"""
        <div role="status" aria-live="{priority}" aria-atomic="true" class="sr-only">
            {message}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_skip_navigation() -> None:
    """Render skip-to-main-content link for keyboard users."""
    st.markdown(
        """
        <a href="#main-content" class="skip-to-main">
            Skip to main content
        </a>
        <div id="main-content" tabindex="-1"></div>
        """,
        unsafe_allow_html=True,
    )


def render_accessible_button(
    label: str,
    aria_label: Optional[str] = None,
    aria_description: Optional[str] = None,
    disabled: bool = False,
) -> None:
    """Render an accessible button with proper ARIA attributes.
    
    Args:
        label: Button text.
        aria_label: Optional accessible label (if different from visible text).
        aria_description: Optional detailed description.
        disabled: Whether button is disabled.
    """
    aria_attrs = ""
    if aria_label:
        aria_attrs += f'aria-label="{aria_label}" '
    if aria_description:
        aria_attrs += f'aria-describedby="btn-desc" '
    if disabled:
        aria_attrs += 'aria-disabled="true" '
    
    description_html = ""
    if aria_description:
        description_html = f'<span id="btn-desc" class="sr-only">{aria_description}</span>'
    
    st.markdown(
        f"""
        <button class="accessible-button" {aria_attrs} {'disabled' if disabled else ''}>
            {label}
        </button>
        {description_html}
        """,
        unsafe_allow_html=True,
    )


def render_landmark_section(
    content: str,
    role: str = "region",
    aria_label: Optional[str] = None,
) -> None:
    """Render a section with proper ARIA landmark role.
    
    Args:
        content: HTML content for the section.
        role: ARIA role (region, navigation, main, complementary).
        aria_label: Label for the landmark.
    """
    aria_label_attr = f'aria-label="{aria_label}"' if aria_label else ""
    
    st.markdown(
        f"""
        <section role="{role}" {aria_label_attr}>
            {content}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_progress_with_aria(
    value: int,
    max_value: int = 100,
    label: str = "Progress",
) -> None:
    """Render a progress indicator with proper ARIA attributes.
    
    Args:
        value: Current progress value.
        max_value: Maximum progress value.
        label: Accessible label for the progress bar.
    """
    percentage = (value / max_value * 100) if max_value > 0 else 0
    
    st.markdown(
        f"""
        <div role="progressbar" 
             aria-valuenow="{value}" 
             aria-valuemin="0" 
             aria-valuemax="{max_value}"
             aria-label="{label}"
             class="progress-bar-container">
            <div class="progress-bar-fill" style="width: {percentage}%">
                <span class="sr-only">{label}: {value} of {max_value}</span>
            </div>
            <div class="progress-bar-text">{int(percentage)}%</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_tab_panel(
    panels: List[Tuple[str, str, str]],
    active_index: int = 0,
) -> None:
    """Render accessible tab panels with proper ARIA attributes.
    
    Args:
        panels: List of (id, title, content) tuples.
        active_index: Index of the active panel.
    """
    tabs_html = []
    panels_html = []
    
    for idx, (panel_id, title, content) in enumerate(panels):
        is_active = idx == active_index
        aria_selected = "true" if is_active else "false"
        tabindex = "0" if is_active else "-1"
        
        tabs_html.append(
            f"""
            <button role="tab" 
                    id="tab-{panel_id}" 
                    aria-selected="{aria_selected}"
                    aria-controls="panel-{panel_id}"
                    tabindex="{tabindex}"
                    class="tab-button {'tab-active' if is_active else ''}">
                {title}
            </button>
            """
        )
        
        hidden = "" if is_active else "hidden"
        panels_html.append(
            f"""
            <div role="tabpanel"
                 id="panel-{panel_id}"
                 aria-labelledby="tab-{panel_id}"
                 {hidden}
                 class="tab-panel">
                {content}
            </div>
            """
        )
    
    st.markdown(
        f"""
        <div class="tabs-container">
            <div role="tablist" aria-label="Content tabs" class="tab-list">
                {''.join(tabs_html)}
            </div>
            {''.join(panels_html)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_alert_banner(
    message: str,
    alert_type: str = "info",
    dismissible: bool = False,
) -> None:
    """Render an accessible alert banner.
    
    Args:
        message: Alert message.
        alert_type: Type of alert (info, warning, error, success).
        dismissible: Whether the alert can be dismissed.
    """
    role = "alert" if alert_type == "error" else "status"
    icons = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
        "success": "✅",
    }
    icon = icons.get(alert_type, "ℹ️")
    
    dismiss_button = ""
    if dismissible:
        dismiss_button = """
            <button class="alert-dismiss" aria-label="Dismiss alert">×</button>
        """
    
    st.markdown(
        f"""
        <div role="{role}" 
             aria-live="polite" 
             class="alert-banner alert-{alert_type}">
            <span class="alert-icon">{icon}</span>
            <span class="alert-message">{message}</span>
            {dismiss_button}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_form_field_with_aria(
    field_id: str,
    label: str,
    field_type: str = "text",
    required: bool = False,
    error_message: Optional[str] = None,
    help_text: Optional[str] = None,
) -> None:
    """Render a form field with proper ARIA attributes and associations.
    
    Args:
        field_id: Unique field identifier.
        label: Field label.
        field_type: Input type (text, number, email, etc.).
        required: Whether field is required.
        error_message: Error message if validation failed.
        help_text: Helpful description for the field.
    """
    required_attr = "required aria-required='true'" if required else ""
    required_indicator = '<span class="required-indicator" aria-label="required">*</span>' if required else ""
    
    describedby = []
    if help_text:
        describedby.append(f"{field_id}-help")
    if error_message:
        describedby.append(f"{field_id}-error")
    
    describedby_attr = f'aria-describedby="{" ".join(describedby)}"' if describedby else ""
    invalid_attr = 'aria-invalid="true"' if error_message else ""
    
    help_html = ""
    if help_text:
        help_html = f'<div id="{field_id}-help" class="field-help">{help_text}</div>'
    
    error_html = ""
    if error_message:
        error_html = f'<div id="{field_id}-error" class="field-error" role="alert">{error_message}</div>'
    
    st.markdown(
        f"""
        <div class="form-field {'has-error' if error_message else ''}">
            <label for="{field_id}" class="field-label">
                {label} {required_indicator}
            </label>
            <input type="{field_type}" 
                   id="{field_id}" 
                   name="{field_id}"
                   {required_attr}
                   {describedby_attr}
                   {invalid_attr}
                   class="field-input" />
            {help_html}
            {error_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

