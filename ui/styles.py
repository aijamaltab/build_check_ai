"""Общий CSS: деловой нейтральный стиль (ERP/CRM): фон #F4F6F8, белые панели, рамка 1px #D8DEE6, один акцент #1F4E79,
шрифт IBM Plex Sans без засечек, цифры табличные, радиус не больше 6px, без градиентов и крупных теней.
Один вызов st.markdown; HTML блоков собирается в ui/components.py."""
import streamlit as st

FONT_IMPORT = "@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');"

CSS = FONT_IMPORT + """
:root { --bg: #F4F6F8; --ink: #1B2733; --muted: #5B6877; --line: #D8DEE6; --panel: #EEF2F6; --accent: #1F4E79; --accent-soft: #E7EEF5;
        --vor: #EEF2F6; --vor-line: #D8DEE6; --act: #F7F1E4; --act-line: #E6D8B8; --radius: 6px;
        --sans: 'IBM Plex Sans', 'Segoe UI', Arial, sans-serif; }
html, body, .stApp, .stApp :is(p, span, div, label, a, li, button, input, textarea, select, h1, h2, h3, h4):not([data-testid="stIconMaterial"], [data-testid="stIconMaterial"] *) { font-family: var(--sans); }
.stApp { background: var(--bg); color: var(--ink); font-variant-numeric: tabular-nums; }
.block-container { max-width: 1240px; padding-top: 3.6rem; padding-bottom: 2.5rem; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
[data-testid="stSidebar"] { background: #fff; border-right: 1px solid var(--line); }
[data-testid="stSidebarNav"] a { border-radius: 4px; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
h1, h2, h3, .hero-title, .section-title { font-family: var(--sans); color: var(--ink); letter-spacing: 0; }
.topbar { display: flex; flex-wrap: wrap; gap: 4px 22px; background: #fff; border: 1px solid var(--line); border-radius: var(--radius);
          padding: 7px 12px; margin: 0 0 12px 0; font-size: 0.84rem; color: var(--muted); }
.topbar b { color: var(--ink); font-weight: 600; }
/* Кнопка открытия меню страниц: яркая, с подписью «Меню» и короткой пульсацией (3 раза), чтобы новички её замечали */
[data-testid="stExpandSidebarButton"] { width: auto !important; height: 38px !important; padding: 0 16px 0 10px !important; gap: 4px; border-radius: 20px !important;
        background: var(--accent) !important; color: #fff !important; box-shadow: 0 2px 8px rgba(31, 78, 121, 0.35); cursor: pointer;
        animation: nav-pulse 1.8s ease-out 3; }
[data-testid="stExpandSidebarButton"]::after { content: "Меню"; font-size: 0.92rem; font-weight: 600; color: #fff; }
[data-testid="stExpandSidebarButton"] span, [data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] { color: #fff !important; }
[data-testid="stExpandSidebarButton"]:hover { background: #17405F !important; }
@keyframes nav-pulse { 0% { box-shadow: 0 0 0 0 rgba(31, 78, 121, 0.6); } 70% { box-shadow: 0 0 0 16px rgba(31, 78, 121, 0); } 100% { box-shadow: 0 0 0 0 rgba(31, 78, 121, 0); } }
@media (prefers-reduced-motion: reduce) { [data-testid="stExpandSidebarButton"] { animation: none; } }
.hero { padding: 0 0 4px 0; }
.hero-title { font-size: 1.5rem; line-height: 1.25; font-weight: 600; margin: 4px 0 4px 0; }
.hero-lead { font-size: 0.95rem; line-height: 1.45; color: var(--muted); margin: 0 0 6px 0; max-width: 860px; }
.hero-note { font-size: 0.88rem; color: var(--ink); border-left: 3px solid var(--accent); padding: 2px 0 2px 10px; margin: 6px 0; max-width: 860px; }
.pill { display: inline-block; font-size: 0.76rem; padding: 1px 8px; border-radius: 4px; background: var(--accent-soft); color: var(--accent); border: 1px solid #C9D8E6; }
.trio { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 10px 0; }
.trio-item { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; }
.trio-num { color: var(--accent); font-size: 1.2rem; font-weight: 600; }
.trio-title { font-weight: 600; margin: 2px 0 4px 0; }
.trio-text { color: var(--muted); font-size: 0.9rem; line-height: 1.45; }
.mode-line { color: var(--muted); font-size: 0.88rem; margin: 0 0 0.4rem 0; }
.banner { background: #FFF6DB; color: #4A3B00; border: 1px solid #EBCF8A; border-radius: var(--radius); padding: 0.55rem 0.9rem; margin: 0.5rem 0 0.8rem 0; font-size: 0.92rem; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 8px 0 4px 0; }
.metric-card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 14px; }
.metric-label { color: var(--muted); font-size: 0.82rem; }
.metric-value { color: var(--ink); font-size: 1.6rem; font-weight: 600; line-height: 1.2; margin-top: 2px; white-space: nowrap; }
.metric-note { color: var(--muted); font-size: 0.76rem; margin-top: 3px; line-height: 1.35; }
.note-small { color: var(--muted); font-size: 0.82rem; margin: 0.2rem 0 0.6rem 0; }
.traffic { display: flex; width: 100%; border-radius: var(--radius); overflow: hidden; margin-top: 6px; }
.seg { padding: 8px 10px; min-width: 24%; text-align: center; box-sizing: border-box; }
.seg-word { font-weight: 600; font-size: 0.95rem; }
.seg-count { font-size: 0.88rem; }
.legend { color: var(--muted); font-size: 0.84rem; margin: 6px 0 10px 0; line-height: 1.45; }
.section-title { font-size: 1.1rem; font-weight: 600; margin: 1.3rem 0 0.2rem 0; }
.section-sub { color: var(--muted); font-size: 0.9rem; margin: 0 0 0.5rem 0; max-width: 860px; line-height: 1.45; }
.irows { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); }
.irow { display: flex; align-items: center; gap: 12px; padding: 9px 14px; border-bottom: 1px solid #E8ECF1; }
.irow:last-child { border-bottom: 0; }
.sev { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.irow-main { flex: 1; min-width: 0; }
.irow-title { font-weight: 600; overflow-wrap: anywhere; }
.irow-sub { color: var(--muted); font-size: 0.84rem; overflow-wrap: anywhere; }
.irow-amt { font-weight: 600; white-space: nowrap; }
.issue-card { display: flex; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); margin: 0 0 10px 0; overflow: hidden; }
.issue-bar { width: 5px; flex: 0 0 5px; }
.issue-body { padding: 10px 14px; min-width: 0; flex: 1; }
.issue-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.issue-title { color: var(--ink); font-weight: 600; font-size: 1.02rem; margin: 0 0 4px 0; overflow-wrap: anywhere; }
.issue-amount { font-weight: 600; white-space: nowrap; color: var(--ink); }
.issue-amount small { display: block; font-weight: 400; font-size: 0.72rem; color: var(--muted); text-align: right; }
.badge { display: inline-block; font-size: 0.74rem; padding: 1px 8px; border-radius: 4px; margin: 0 6px 4px 0; background: var(--panel); color: var(--muted); border: 1px solid var(--line); }
.badge-high { background: #FDECEA; color: #8E1B1B; border-color: #EDC3BF; }
.badge-medium { background: #FFF6DB; color: #5A4300; border-color: #EBCF8A; }
.badge-low { background: #EEF2F6; color: #44505E; border-color: #D8DEE6; }
.badge-ai { background: var(--accent-soft); color: var(--accent); border-color: #C9D8E6; }
.issue-phrase { color: var(--ink); margin: 2px 0 8px 0; overflow-wrap: anywhere; }
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 4px 0 6px 0; }
.side { border-radius: 4px; padding: 8px 12px; border: 1px solid; min-width: 0; }
.side-vor { background: var(--vor); border-color: var(--vor-line); }
.side-act { background: var(--act); border-color: var(--act-line); }
.side-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 3px; }
.side-name { font-weight: 500; color: var(--ink); overflow-wrap: anywhere; }
.side-none { color: var(--muted); font-style: italic; }
.side-value { font-size: 1.2rem; font-weight: 600; color: var(--ink); margin: 2px 0; }
.side-lines { color: var(--muted); font-size: 0.86rem; line-height: 1.5; margin: 2px 0 4px 0; }
.side-total { font-size: 1.1rem; font-weight: 600; color: #8E1B1B; }
.side-hint { color: var(--muted); font-size: 0.8rem; margin: 0 0 6px 0; font-style: italic; }
.issue-note { color: #5A4300; font-size: 0.86rem; margin: 2px 0 6px 0; }
.ai-box { background: var(--accent-soft); border: 1px solid #C9D8E6; border-radius: 4px; padding: 6px 10px; margin: 6px 0 4px 0; }
.ai-title { color: var(--accent); font-weight: 600; font-size: 0.82rem; margin-bottom: 3px; }
.ai-pair { margin: 3px 0 5px 0; overflow-wrap: anywhere; }
.ai-names { color: var(--ink); font-size: 0.92rem; }
.ai-before { color: var(--muted); }
.ai-after { color: var(--ink); font-weight: 600; }
.ai-arrow { color: var(--accent); font-weight: 600; }
.ai-meta { color: var(--muted); font-size: 0.82rem; margin-top: 2px; }
.issue-src { color: #66727F; font-size: 0.78rem; margin-top: 6px; line-height: 1.5; overflow-wrap: anywhere; }
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0.5rem 0 0.2rem 0; }
.cmp-col { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; }
.cmp-ai { border: 1px solid var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.cmp-title { color: var(--ink); font-weight: 600; font-size: 1.05rem; margin-bottom: 6px; }
.cmp-row { display: flex; justify-content: space-between; gap: 8px; padding: 5px 0; border-top: 1px solid var(--line); font-size: 0.95rem; }
.cmp-label { color: var(--muted); }
.cmp-value { color: var(--ink); font-weight: 600; text-align: right; }
.ex-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 0.5rem; }
.ex-card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; min-width: 0; }
.ex-row { display: flex; flex-direction: column; margin: 0 0 8px 0; font-size: 0.88rem; color: var(--ink); overflow-wrap: anywhere; }
.ex-label { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; }
.ex-ai { background: var(--accent-soft); border-radius: 4px; padding: 3px 8px; }
.fileinfo { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; margin: 0.5rem 0; }
.fileinfo-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.fileinfo-name { font-weight: 600; font-size: 1.05rem; }
.fileinfo-facts { display: flex; flex-wrap: wrap; gap: 6px 22px; margin: 6px 0; color: var(--muted); font-size: 0.9rem; }
.fileinfo-facts b { color: var(--ink); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.chip { background: var(--vor); border: 1px solid var(--vor-line); border-radius: 4px; padding: 1px 8px; font-size: 0.84rem; color: var(--ink); }
.claim { background: #fff; border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: var(--radius); padding: 10px 14px; margin: 0.6rem 0; line-height: 1.5; }
.claim-warn { border-left-color: #B5792F; }
.app-footer { color: var(--muted); font-size: 0.82rem; text-align: center; margin-top: 1.6rem; padding-top: 0.8rem; border-top: 1px solid var(--line); }

.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 8px 0 4px 0; }
.step { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 12px; font-size: 0.92rem; line-height: 1.4; }
.steps-note { color: var(--muted); font-size: 0.84rem; margin: 4px 0 8px 0; }
.tiles { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 6px 0; }
.tile { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 7px 12px; min-height: 64px; }
.tile-label { color: var(--muted); font-size: 12px; line-height: 1.25; }
.tile-value { color: var(--ink); font-size: 21px; font-weight: 600; line-height: 1.25; white-space: nowrap; }
.tbar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; margin: 10px 0 4px 0; }
.tcounts { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 0.86rem; color: var(--ink); }
.tcount i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
.roles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 6px 0 10px 0; }
.role { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 14px; }
.role-title { font-weight: 600; color: var(--accent); margin-bottom: 2px; }
.role-text { font-size: 0.92rem; line-height: 1.45; overflow-wrap: anywhere; }
.chain { width: 100%; border-collapse: separate; border-spacing: 0; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); table-layout: fixed; }
.chain th { text-align: left; font-size: 0.82rem; font-weight: 600; background: #EEF2F6; padding: 8px 22px 8px 10px; position: relative; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
.chain th:not(:last-child)::after { content: "→"; position: absolute; right: 6px; top: 50%; transform: translateY(-50%); color: var(--accent); font-weight: 400; }
.chain td { vertical-align: top; padding: 9px 10px; border-bottom: 1px solid #E8ECF1; font-size: 0.88rem; line-height: 1.4; overflow-wrap: anywhere; }
.chain tr:last-child td { border-bottom: 0; }
.chain .sub { color: var(--muted); font-size: 0.8rem; }
.plain { width: 100%; border-collapse: separate; border-spacing: 0; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); margin: 4px 0 8px 0; }
.plain th { text-align: left; font-size: 0.82rem; font-weight: 600; background: #EEF2F6; padding: 8px 10px; border-bottom: 1px solid var(--line); }
.plain td { vertical-align: top; padding: 7px 10px; border-bottom: 1px solid #E8ECF1; font-size: 0.88rem; line-height: 1.4; overflow-wrap: anywhere; }
.plain tr:last-child td { border-bottom: 0; }
.plain tr.row-false td { background: #FFF8E1; }
.plain td[data-label="Тип"] { min-width: 120px; overflow-wrap: break-word; }
.plain td[data-label="Важность"] { min-width: 80px; overflow-wrap: break-word; }
.verdict.v-ok b { color: #1E5E22; }
.verdict.v-no b { color: #5B6877; }
.err-lead { font-size: 1rem; margin: 2px 0 8px 0; }
.plan-line { background: #F7F1E4; border: 1px solid #E6D8B8; border-radius: var(--radius); padding: 8px 12px; margin: 0 0 10px 0; line-height: 1.5; }
.plan-line .sub { color: var(--muted); font-size: 0.84rem; }
.err-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.err-card { background: #fff; border: 1px solid var(--line); border-top: 3px solid #E6D8B8; border-radius: var(--radius); padding: 10px 14px; min-width: 0; }
.err-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.err-tag { font-size: 0.74rem; padding: 1px 8px; border-radius: 4px; background: #F7F1E4; color: #5A4300; border: 1px solid #E6D8B8; }
.err-title { font-weight: 600; overflow-wrap: anywhere; }
.err-row { display: flex; flex-direction: column; margin: 0 0 7px 0; font-size: 0.88rem; line-height: 1.4; overflow-wrap: anywhere; }
.err-label { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; }
.errbox { background: #FFF8E1; border: 1px solid #EBCF8A; border-radius: var(--radius); padding: 10px 14px; margin: 0.6rem 0; line-height: 1.5; }
.summary-list { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); margin: 4px 0 8px 0; padding: 8px 14px 8px 32px; }
.summary-list li { margin: 3px 0; line-height: 1.45; }
.st-key-demo_files [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; align-items: center; gap: 0.5rem; }
.st-key-demo_files [data-testid="stColumn"] { min-width: 0; }
.st-key-demo_files p { margin: 0; font-size: 0.9rem; overflow-wrap: anywhere; }
.st-key-demo_files button { min-height: 2rem; padding: 0 0.6rem; white-space: normal; }
.st-key-demo_files button p { overflow: visible; text-overflow: clip; white-space: normal; }
[data-testid="stFileUploader"] span, [data-testid="stFileUploader"] small { text-overflow: clip !important; white-space: normal !important; overflow: visible !important; }
[data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] style) { display: none; }
@media (max-width: 900px) { .err-grid { grid-template-columns: 1fr; } .ex-grid { grid-template-columns: repeat(2, 1fr); } .tiles { grid-template-columns: repeat(3, 1fr); } .roles, .steps { grid-template-columns: 1fr; } }
@media (max-width: 640px) {
  .tiles { grid-template-columns: repeat(2, 1fr); }
  .chain, .chain tbody, .chain tr, .chain td, .plain, .plain tbody, .plain tr, .plain td { display: block; width: 100%; }
  .chain thead, .plain thead { display: none; }
  .plain td { border: 0; padding: 3px 10px; }
  .plain td::before { content: attr(data-label); display: block; color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em; }
  .plain tr { border-bottom: 1px solid var(--line); padding: 5px 0; }
  .chain tr { border-bottom: 1px solid var(--line); padding: 6px 0; }
  .chain td { border: 0; padding: 4px 10px; }
  .chain td::before { content: attr(data-label); display: block; color: var(--muted); font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.04em; }
  .block-container { padding-left: 0.75rem; padding-right: 0.75rem; padding-top: 3.6rem; }
  .hero-title { font-size: 1.25rem; }
  .trio { grid-template-columns: 1fr; gap: 8px; }
  .metric-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .metric-value { font-size: 1.3rem; }
  .seg { padding: 8px 4px; min-width: 26%; }
  .seg-word { font-size: 0.82rem; }
  .seg-count { font-size: 0.78rem; }
  .irow { flex-wrap: wrap; }
  .irow-amt { width: 100%; padding-left: 22px; }
  .issue-body { padding: 10px 12px; }
  .issue-head { flex-direction: column; gap: 2px; }
  .issue-amount small { text-align: left; }
  .sides { grid-template-columns: 1fr; gap: 8px; }
  .ex-grid { grid-template-columns: 1fr; }
  .cmp-grid { gap: 8px; }
  .cmp-col { padding: 10px; }
  .cmp-row { flex-direction: column; gap: 0; }
  .section-title { font-size: 1rem; }
}
"""


def inject() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
