"""McKinsey-style visual identity: deep navy, electric blue, serif action titles, restrained cards."""
from __future__ import annotations

import streamlit as st

NAVY = "#051C2C"
BLUE = "#2251FF"
CYAN = "#00A9F4"
INK = "#1F2A37"
MUTE = "#6B7A8C"
LINE = "#D5DEE9"
BG = "#F5F8FC"
RED = "#D7263D"
PALETTE = ["#2251FF", "#00A9F4", "#051C2C", "#1B998B", "#6A4C93", "#F46036", "#C5A100", "#7B8FA6"]
ZONE_COLORS = ["#CFE3F7", "#9CC5EE", "#5E9BE0", "#2251FF", "#1D4FB0", "#0B2A6B", "#00A9F4", "#7FD1F5", "#1B998B", "#6A4C93"]

CSS = f"""
<style>
html, body, [class*="css"] {{ font-family: Arial, Helvetica, sans-serif; color: {INK}; }}
h1, h2, h3, .action-title {{ font-family: Georgia, 'Times New Roman', serif !important; color: {NAVY}; letter-spacing: .1px; }}
.block-container {{ padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1500px; }}
section[data-testid="stSidebar"] {{ background: {NAVY}; }}
section[data-testid="stSidebar"] * {{ color: #E8EEF5 !important; }}
section[data-testid="stSidebar"] .stRadio label {{ padding: 5px 8px; border-radius: 2px; }}
section[data-testid="stSidebar"] .stRadio label:hover {{ background: #0B3350; }}
section[data-testid="stSidebar"] div.stButton > button {{ width: 100%; justify-content: flex-start; text-align: left; background: transparent; border: 0; border-left: 3px solid transparent; border-radius: 0; padding: 2px 8px; font-size: 12.5px; color: #E8EEF5; }}
section[data-testid="stSidebar"] div.stButton > button:hover {{ background: #0B3350; }}
section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {{ background: #0B3350; border-left: 3px solid {BLUE}; font-weight: 700; }}
section[data-testid="stSidebar"] [data-testid="stExpander"] {{ border: 0; background: transparent; }}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {{ padding: 3px 4px; font-size: 12.5px; }}
.tree-grp {{ font-size: 10.5px; letter-spacing: .9px; text-transform: uppercase; color: #7FD1F5; margin: 8px 0 2px; border-bottom: 1px solid #20405a; padding-bottom: 2px; }}
section[data-testid="stSidebar"] hr {{ border-color: #20405a; }}
.brand {{ font-family: Georgia, serif; font-size: 1.35rem; color: #fff !important; margin: .2rem 0 0 0; }}
.brand small {{ display:block; font: 11px Arial; letter-spacing: 1.6px; text-transform: uppercase; color: {CYAN} !important; margin-top: 2px; }}
.banner {{ background: {NAVY}; color: #fff; padding: 14px 22px; border-left: 6px solid {BLUE}; margin-bottom: 14px; }}
.banner .kicker {{ font-size: 11px; letter-spacing: 1.6px; text-transform: uppercase; color: {CYAN}; }}
.banner .action-title {{ color: #fff !important; font-size: 1.55rem; margin: 2px 0 0 0; line-height: 1.25; }}
.kpis {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 14px 0; }}
.kpi {{ flex: 1; min-width: 130px; background: {BG}; border: 1px solid {LINE}; border-top: 3px solid {BLUE}; padding: 8px 12px; }}
.kpi .v {{ font: 1.55rem Georgia, serif; color: {NAVY}; }}
.kpi .l {{ font-size: 11px; letter-spacing: .8px; text-transform: uppercase; color: {MUTE}; }}
.stepper {{ display: flex; gap: 0; margin: 6px 0 16px 0; flex-wrap: wrap; }}
.step {{ flex: 1; min-width: 120px; padding: 8px 10px; background: {BG}; border: 1px solid {LINE}; border-right: none; font-size: 12px; }}
.step:last-child {{ border-right: 1px solid {LINE}; }}
.step b {{ display: block; color: {NAVY}; font-size: 12.5px; }}
.step.done {{ background: #E3EBFF; border-bottom: 3px solid {BLUE}; }}
.step.todo {{ color: {MUTE}; }}
.note {{ border-left: 3px solid {CYAN}; background: {BG}; padding: 8px 12px; margin: 8px 0; font-size: 13px; }}
.note.warn {{ border-left-color: {RED}; }}
div.stButton > button {{ border-radius: 2px; border: 1px solid {LINE}; font-weight: 600; }}
div.stButton > button[kind="primary"] {{ background: {BLUE}; border-color: {BLUE}; color: #fff; }}
div.stButton > button[kind="primary"]:hover {{ background: #1A40CC; border-color: #1A40CC; }}
div.stDownloadButton > button {{ border-radius: 2px; font-weight: 600; border: 1px solid {BLUE}; color: {BLUE}; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 2px; border-bottom: 2px solid {NAVY}; }}
.stTabs [data-baseweb="tab"] {{ background: {BG}; border-radius: 2px 2px 0 0; padding: 6px 14px; }}
.stTabs [aria-selected="true"] {{ background: {NAVY}; color: #fff !important; }}
.stTabs [aria-selected="true"] p {{ color: #fff !important; }}
.footer {{ margin-top: 30px; padding-top: 8px; border-top: 1px solid {LINE}; color: {MUTE}; font-size: 11.5px; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def banner(kicker: str, title: str):
    st.markdown(f'<div class="banner"><div class="kicker">{kicker}</div><div class="action-title">{title}</div></div>',
                unsafe_allow_html=True)


def kpis(items):
    cells = "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>' for l, v in items)
    st.markdown(f'<div class="kpis">{cells}</div>', unsafe_allow_html=True)


def note(text: str, warn: bool = False):
    st.markdown(f'<div class="note{" warn" if warn else ""}">{text}</div>', unsafe_allow_html=True)


def stepper(stages):
    cells = "".join(f'<div class="step {"done" if ok else "todo"}"><b>{n}</b>{d}</div>' for n, d, ok in stages)
    st.markdown(f'<div class="stepper">{cells}</div>', unsafe_allow_html=True)


def footer():
    st.markdown('<div class="footer">GeoModel Studio &middot; structural framework to simulation grid &middot; MIT License. '
                'Vertical-separation fault model with stair-stepped corner-point faults: a concept-modelling tool, '
                'not a substitute for a full pillar-gridding product.</div>', unsafe_allow_html=True)


CONFIG_TOML = f"""[theme]
base = "light"
primaryColor = "{BLUE}"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "{BG}"
textColor = "{INK}"
font = "sans serif"

[server]
maxUploadSize = 500
"""
