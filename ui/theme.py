"""Shared visual theme and lightweight layout helpers for GeoModel Studio."""
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
html, body, [class*="css"] {{ font-family: Inter, "Segoe UI", Arial, sans-serif; color: {INK}; }}
h1, h2, h3, .action-title {{ font-family: Inter, "Segoe UI", Arial, sans-serif !important; color: {NAVY}; letter-spacing: -.025em; }}
.block-container {{ padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1540px; }}
section[data-testid="stSidebar"] {{ background: #F7F9FC; border-right: 1px solid {LINE}; }}
section[data-testid="stSidebar"] * {{ color: {INK}; }}
section[data-testid="stSidebar"] div.stButton > button {{ width: 100%; justify-content: flex-start; text-align: left; background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; font-size: 13px; color: {INK}; }}
section[data-testid="stSidebar"] div.stButton > button:hover {{ background: #EAF0F8; border-color: #E0E7F0; }}
section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {{ background: #E7EEFF; border-color: #D4E0FF; color: {BLUE}; font-weight: 700; }}
section[data-testid="stSidebar"] [data-testid="stExpander"] {{ border: 1px solid {LINE}; border-radius: 10px; background: #FFFFFF; margin-bottom: 8px; }}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {{ padding: 8px 10px; font-size: 13px; font-weight: 650; }}
section[data-testid="stSidebar"] hr {{ border-color: {LINE}; }}
section[data-testid="stSidebar"] [class*="st-key-tree_ok_"] button p {{ color: #167541 !important; }}
section[data-testid="stSidebar"] [class*="st-key-tree_stale_"] button p {{ color: #B45B15 !important; }}
section[data-testid="stSidebar"] [class*="st-key-tree_missing_"] button p {{ color: {MUTE} !important; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_"] {{ border-left: 3px solid {LINE}; padding-left: 6px; margin-bottom: 5px; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_surface"] {{ border-left-color: #2251FF; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_fault"] {{ border-left-color: #D7263D; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_polygon"] {{ border-left-color: #6A4C93; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_well"] {{ border-left-color: #B45B15; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_structure"] {{ border-left-color: #2251FF; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_zone"] {{ border-left-color: #1B998B; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_grid"] {{ border-left-color: #00A9F4; }}
section[data-testid="stSidebar"] [class*="st-key-tree_kind_prop"] {{ border-left-color: #6A4C93; }}
.brand {{ font-size: 1.22rem; font-weight: 750; letter-spacing: -.035em; color: {NAVY} !important; margin: .2rem 0 .95rem 0; }}
.brand small {{ display:block; font-size: 10px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: {MUTE} !important; margin-top: 4px; }}
.nav-label {{ color: {MUTE}; font-size: 10px; font-weight: 750; letter-spacing: .12em; margin: 0 0 6px 2px; }}
.project-chip {{ padding: 10px 12px; border: 1px solid {LINE}; border-radius: 9px; background: #FFFFFF; color: {NAVY}; overflow-wrap: anywhere; }}
.banner {{ background: linear-gradient(110deg, #F1F5FF, #FFFFFF 68%); color: {INK}; padding: 18px 22px; border: 1px solid #DDE6F4; border-left: 4px solid {BLUE}; border-radius: 12px; margin-bottom: 18px; }}
.banner .kicker {{ font-size: 10px; font-weight: 750; letter-spacing: .13em; text-transform: uppercase; color: {BLUE}; }}
.banner .action-title {{ color: {NAVY} !important; font-size: clamp(1.25rem, 2vw, 1.65rem); font-weight: 700; margin: 4px 0 0; line-height: 1.3; }}
.kpis {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0 18px; }}
.kpi {{ flex: 1; min-width: 130px; background: #FFFFFF; border: 1px solid {LINE}; border-radius: 10px; padding: 12px 14px; box-shadow: 0 1px 2px #12243A08; }}
.kpi .v {{ font-size: 1.45rem; line-height: 1.2; font-weight: 700; color: {NAVY}; }}
.kpi .l {{ font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: {MUTE}; margin-top: 4px; }}
.stepper {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 8px 0 18px; }}
.step {{ min-width: 0; padding: 11px 12px; background: #FFFFFF; border: 1px solid {LINE}; border-radius: 9px; font-size: 12px; color: {MUTE}; }}
.step b {{ display: block; color: {NAVY}; font-size: 13px; margin-bottom: 3px; }}
.step.done {{ background: #F0F5FF; border-color: #D5E2FF; box-shadow: inset 0 2px 0 {BLUE}; }}
.step.todo {{ border-style: dashed; }}
.workflow-construction {{ --task-color: #2251FF; }}
.workflow-layering {{ --task-color: #1B998B; }}
.workflow-conditioning {{ --task-color: #6A4C93; }}
.workflow-refinement {{ --task-color: #B45B15; }}
.workflow-faults {{ --task-color: #D7263D; }}
.workflow-node {{ display: flex; align-items: flex-start; gap: 14px; border-left: 4px solid var(--task-color); padding: 10px 12px; background: {BG}; border-radius: 8px; margin-bottom: 10px; }}
.workflow-number {{ flex: 0 0 34px; background: var(--task-color); color: #FFFFFF; text-align: center; padding: 7px 0; border-radius: 8px; font-weight: 750; }}
.workflow-content {{ min-width: 0; overflow-wrap: anywhere; }}
.workflow-category {{ color: var(--task-color); font-size: 10px; font-weight: 750; text-transform: uppercase; letter-spacing: .08em; }}
.workflow-title {{ font-size: 16px; color: {NAVY}; font-weight: 700; margin: 3px 0 9px; }}
.workflow-io {{ font-size: 12px; color: {INK}; margin-top: 4px; }}
.workflow-io b {{ display: inline-block; min-width: 32px; color: {MUTE}; font-size: 10px; }}
.workflow-connector {{ text-align: center; color: {MUTE}; font-size: 26px; line-height: 1.2; margin: 3px 0 8px; }}
.workflow-output {{ border: 1px dashed {BLUE}; border-radius: 10px; background: #F1F5FF; padding: 14px; text-align: center; font-size: 13px; color: {INK}; }}
.workflow-legend {{ display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 6px 0 18px; }}
.workflow-legend span {{ border-left: 4px solid var(--task-color); padding-left: 7px; color: {INK}; font-size: 12px; }}
.sidebar-flow-title {{ display: flex; align-items: center; gap: 8px; color: {NAVY}; font-size: 13px; font-weight: 700; }}
.sidebar-flow-title span {{ background: {BLUE}; color: #FFFFFF !important; padding: 4px 6px; border-radius: 6px; font-size: 11px; }}
.sidebar-flow-arrow {{ text-align: center; color: {BLUE}; font-size: 22px; line-height: 1.1; margin: 4px 0; }}
.note {{ border-left: 3px solid {CYAN}; background: {BG}; border-radius: 0 8px 8px 0; padding: 10px 13px; margin: 8px 0; font-size: 13px; }}
.note.warn {{ border-left-color: {RED}; }}
div.stButton > button {{ border-radius: 8px; border: 1px solid {LINE}; font-weight: 650; transition: background .15s ease, border-color .15s ease; }}
div.stButton > button[kind="primary"] {{ background: {BLUE}; border-color: {BLUE}; color: #FFFFFF; }}
div.stButton > button[kind="primary"]:hover {{ background: #1A40CC; border-color: #1A40CC; }}
div.stDownloadButton > button {{ border-radius: 8px; font-weight: 650; border: 1px solid {BLUE}; color: {BLUE}; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 5px; border-bottom: 1px solid {LINE}; }}
.stTabs [data-baseweb="tab"] {{ background: transparent; border-radius: 8px 8px 0 0; padding: 8px 14px; }}
.stTabs [aria-selected="true"] {{ background: #E7EEFF; color: {BLUE} !important; }}
.stTabs [aria-selected="true"] p {{ color: {BLUE} !important; }}
.footer {{ margin-top: 30px; padding-top: 10px; border-top: 1px solid {LINE}; color: {MUTE}; font-size: 11.5px; }}
.block-container {{ padding-top: 3.4rem !important; padding-bottom: 4.5rem !important; }}
.st-key-ribbon {{ background: linear-gradient(180deg, {NAVY}, #0B2A45); border-radius: 10px 10px 0 0; padding: 6px 8px 0 8px; gap: 0 !important; }}
.st-key-ribbon [data-testid="stHorizontalBlock"], .st-key-ribbon_tools [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; gap: 4px !important; }}
.st-key-ribbon [data-testid="stColumn"], .st-key-ribbon_tools [data-testid="stColumn"] {{ flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }}
.st-key-ribbon div.stButton > button {{ background: transparent; border: none; border-radius: 7px 7px 0 0; color: #C9D6E6; font-size: 12.5px; font-weight: 650; padding: 7px 12px; min-height: 0; white-space: nowrap; }}
.st-key-ribbon div.stButton > button p {{ color: #C9D6E6 !important; font-size: 12.5px; }}
.st-key-ribbon div.stButton > button:hover {{ background: #16395C; }}
.st-key-ribbon div.stButton > button[kind="primary"] {{ background: #F5F8FC; }}
.st-key-ribbon div.stButton > button[kind="primary"] p {{ color: {NAVY} !important; font-weight: 750; }}
.st-key-ribbon_tools {{ background: {BG}; border: 1px solid {LINE}; border-top: none; border-radius: 0 0 10px 10px; padding: 8px 10px; margin-bottom: 6px; }}
.st-key-ribbon_tools div.stButton > button {{ font-size: 12.5px; padding: 5px 12px; min-height: 0; background: #FFFFFF; white-space: nowrap; }}
.st-key-ribbon_tools div.stButton > button[kind="primary"] {{ background: {BLUE}; color: #FFFFFF; }}
.breadcrumb {{ color: {MUTE}; font-size: 12px; letter-spacing: .02em; margin: 2px 0 8px 2px; }}
.breadcrumb span {{ margin: 0 6px; }}
.breadcrumb b {{ color: {NAVY}; }}
.statusbar {{ position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000002; display: flex; justify-content: space-between; gap: 16px;
             background: {NAVY}; color: #C9D6E6; font-size: 11.5px; padding: 5px 16px; }}
.statusbar span, .statusbar b {{ color: #E4ECF5 !important; }}
.statusbar i {{ color: #4E6A86; font-style: normal; margin: 0 8px; }}
.statusbar .sb-left {{ overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }}
.statusbar .sb-right {{ color: #9FB4CB !important; white-space: nowrap; }}
.disclaimer {{ margin-top: 10px; font-size: 10.5px; line-height: 1.4; color: {MUTE} !important; }}
.disclaimer-box {{ border: 1px solid #F0D9A8; background: #FFF9EC; border-left: 4px solid #C5A100; border-radius: 8px; padding: 10px 14px; margin: 6px 0 16px; font-size: 13px; }}
section[data-testid="stSidebar"] .stTabs [data-baseweb="tab"] {{ padding: 6px 10px; font-size: 12.5px; }}
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


DISCLAIMER_HTML = ("<b>Disclaimer.</b> GeoModel Studio is built by <b>Merouane Hamdani</b> for <b>non-commercial use only</b>, "
                   "under the PolyForm Noncommercial License 1.0.0 (see LICENSE). It is a concept-modelling tool provided "
                   "as is, without warranty, and is not a substitute for validated commercial geomodelling software. "
                   "Results must be checked by a qualified geoscientist before any decision is based on them.")


def disclaimer():
    st.markdown(f'<div class="disclaimer-box">{DISCLAIMER_HTML}</div>', unsafe_allow_html=True)


def footer():
    st.markdown('<div class="footer">GeoModel Studio &middot; structural framework to simulation grid &middot; '
                'Built by Merouane Hamdani &middot; Non-commercial use only (PolyForm Noncommercial 1.0.0). '
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
