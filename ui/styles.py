"""Общий CSS экрана: спокойная «бумажная» палитра, засечки в заголовках, без градиентов и свечения.
Один вызов st.markdown; HTML карточек и бейджей собирается в ui/components.py."""
import streamlit as st

CSS = """
:root { --bg: #FBF9F5; --ink: #2A2723; --muted: #6B655C; --line: #E4DED3; --panel: #F3EFE7; --accent: #2E5E4E; --accent-soft: #E6EEEA;
        --vor: #EDF1F0; --vor-line: #D3DCD9; --act: #F8F0E2; --act-line: #EAD9B8; --radius: 10px; --serif: Georgia, 'Times New Roman', serif; }
.block-container { max-width: 1120px; padding-top: 2.2rem; padding-bottom: 3rem; }
#MainMenu, footer { visibility: hidden; }
body, .stApp { color: var(--ink); }
h1, h2, h3, .hero-title, .section-title, .page-title { font-family: var(--serif); color: var(--ink); letter-spacing: 0; }
.hero { padding: 1.2rem 0 0.6rem 0; }
.hero-title { font-size: 2.5rem; line-height: 1.15; font-weight: 700; margin: 0.4rem 0 0.8rem 0; max-width: 820px; }
.hero-lead { font-size: 1.15rem; line-height: 1.55; color: var(--muted); max-width: 760px; margin: 0 0 0.8rem 0; }
.hero-note { font-size: 0.95rem; color: var(--ink); border-left: 3px solid var(--accent); padding: 2px 0 2px 12px; margin: 0.8rem 0 0.4rem 0; max-width: 760px; }
.pill { display: inline-block; font-size: 0.8rem; padding: 3px 12px; border-radius: 999px; background: var(--panel); color: var(--muted); border: 1px solid var(--line); }
.trio { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 1.2rem 0 0.4rem 0; }
.trio-item { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px; }
.trio-num { font-family: var(--serif); color: var(--accent); font-size: 1.5rem; font-weight: 700; }
.trio-title { font-weight: 700; margin: 2px 0 4px 0; font-size: 1.02rem; }
.trio-text { color: var(--muted); font-size: 0.93rem; line-height: 1.5; }
.mode-line { color: var(--muted); font-size: 0.9rem; margin: 0 0 0.4rem 0; }
.banner { background: #FFF4D6; color: #4A3B00; border: 1px solid #EBD58C; border-radius: var(--radius); padding: 0.7rem 1rem; margin: 0.6rem 0 1rem 0; font-size: 0.95rem; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 0.8rem 0 0.4rem 0; }
.metric-card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; }
.metric-label { color: var(--muted); font-size: 0.86rem; }
.metric-value { font-family: var(--serif); color: var(--ink); font-size: 2rem; font-weight: 700; line-height: 1.15; margin-top: 2px; white-space: nowrap; }
.metric-note { color: var(--muted); font-size: 0.78rem; margin-top: 4px; line-height: 1.35; }
.note-small { color: var(--muted); font-size: 0.82rem; margin: 0.2rem 0 0.8rem 0; }
.traffic { display: flex; width: 100%; border-radius: var(--radius); overflow: hidden; margin-top: 0.4rem; }
.seg { padding: 12px 10px; min-width: 24%; text-align: center; box-sizing: border-box; }
.seg-word { font-weight: 700; font-size: 1rem; }
.seg-count { font-size: 0.92rem; }
.legend { color: var(--muted); font-size: 0.86rem; margin: 0.5rem 0 1rem 0; line-height: 1.45; }
.section-title { font-size: 1.55rem; font-weight: 700; margin: 2.2rem 0 0.2rem 0; }
.section-sub { color: var(--muted); font-size: 0.95rem; margin: 0 0 0.7rem 0; max-width: 780px; line-height: 1.5; }
.issue-card { display: flex; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); margin: 0 0 14px 0; overflow: hidden; }
.issue-bar { width: 6px; flex: 0 0 6px; }
.issue-body { padding: 14px 18px 12px 18px; min-width: 0; flex: 1; }
.issue-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.issue-title { font-family: var(--serif); color: var(--ink); font-weight: 700; font-size: 1.2rem; margin: 0 0 6px 0; overflow-wrap: anywhere; }
.issue-amount { font-family: var(--serif); font-weight: 700; font-size: 1.15rem; white-space: nowrap; color: var(--ink); }
.issue-amount small { display: block; font-family: inherit; font-weight: 400; font-size: 0.72rem; color: var(--muted); text-align: right; }
.badge { display: inline-block; font-size: 0.76rem; padding: 2px 10px; border-radius: 999px; margin: 0 6px 6px 0; background: var(--panel); color: var(--muted); border: 1px solid var(--line); }
.badge-high { background: #FBEAE8; color: #8E1B1B; border-color: #EDC3BF; }
.badge-medium { background: #FFF4D6; color: #5A4300; border-color: #EBD58C; }
.badge-low { background: #EEEBE5; color: #4A453E; border-color: #D8D2C7; }
.badge-ai { background: var(--accent-soft); color: var(--accent); border-color: #C3D6CD; }
.issue-phrase { color: var(--ink); font-size: 1.02rem; margin: 2px 0 10px 0; overflow-wrap: anywhere; }
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 4px 0 8px 0; }
.side { border-radius: 8px; padding: 10px 14px; border: 1px solid; min-width: 0; }
.side-vor { background: var(--vor); border-color: var(--vor-line); }
.side-act { background: var(--act); border-color: var(--act-line); }
.side-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 4px; }
.side-name { font-size: 1.02rem; font-weight: 600; color: var(--ink); overflow-wrap: anywhere; }
.side-none { font-size: 1rem; color: var(--muted); font-style: italic; }
.side-value { font-family: var(--serif); font-size: 1.45rem; font-weight: 700; color: var(--ink); margin: 2px 0; }
.side-lines { color: var(--muted); font-size: 0.86rem; line-height: 1.5; margin: 2px 0 4px 0; }
.side-total { font-family: var(--serif); font-size: 1.3rem; font-weight: 700; color: #8E1B1B; }
.side-hint { color: var(--muted); font-size: 0.8rem; margin: 0 0 6px 0; font-style: italic; }
.issue-note { color: #5A4300; font-size: 0.86rem; margin: 2px 0 6px 0; }
.ai-box { background: var(--accent-soft); border: 1px solid #C3D6CD; border-radius: 8px; padding: 8px 12px; margin: 8px 0 4px 0; }
.ai-title { color: var(--accent); font-weight: 700; font-size: 0.82rem; margin-bottom: 4px; }
.ai-pair { margin: 4px 0 6px 0; overflow-wrap: anywhere; }
.ai-names { color: var(--ink); font-size: 0.92rem; }
.ai-before { color: var(--muted); }
.ai-after { color: var(--ink); font-weight: 600; }
.ai-arrow { color: var(--accent); font-weight: 700; }
.ai-meta { color: var(--muted); font-size: 0.82rem; margin-top: 2px; }
.issue-src { color: #7B756B; font-size: 0.78rem; margin-top: 6px; line-height: 1.5; overflow-wrap: anywhere; }
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 0.6rem 0 0.2rem 0; }
.cmp-col { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 18px; }
.cmp-ai { border: 2px solid var(--accent); }
.cmp-title { font-family: var(--serif); color: var(--ink); font-weight: 700; font-size: 1.2rem; margin-bottom: 6px; }
.cmp-row { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-top: 1px solid var(--line); font-size: 0.97rem; }
.cmp-label { color: var(--muted); }
.cmp-value { color: var(--ink); font-weight: 700; text-align: right; }
.ex-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 0.6rem; }
.ex-card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; min-width: 0; }
.ex-row { display: flex; flex-direction: column; margin: 0 0 8px 0; font-size: 0.88rem; color: var(--ink); overflow-wrap: anywhere; }
.ex-label { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; }
.ex-ai { background: var(--accent-soft); border-radius: 8px; padding: 4px 8px; }
.fileinfo { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 18px; margin: 0.6rem 0 0.6rem 0; }
.fileinfo-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.fileinfo-name { font-family: var(--serif); font-weight: 700; font-size: 1.2rem; }
.fileinfo-facts { display: flex; flex-wrap: wrap; gap: 6px 22px; margin: 6px 0; color: var(--muted); font-size: 0.9rem; }
.fileinfo-facts b { color: var(--ink); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.chip { background: var(--vor); border: 1px solid var(--vor-line); border-radius: 6px; padding: 2px 9px; font-size: 0.84rem; color: var(--ink); }
.claim { background: #fff; border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: var(--radius); padding: 12px 16px; margin: 0.8rem 0; font-size: 1rem; line-height: 1.5; }
.claim-warn { border-left-color: #B5792F; }
.app-footer { color: var(--muted); font-size: 0.84rem; text-align: center; margin-top: 2rem; padding-top: 0.9rem; border-top: 1px solid var(--line); }
@media (max-width: 900px) { .ex-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1.2rem; }
  .hero-title { font-size: 1.75rem; }
  .hero-lead { font-size: 1.02rem; }
  .trio { grid-template-columns: 1fr; gap: 10px; }
  .metric-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .metric-value { font-size: 1.5rem; }
  .seg { padding: 10px 4px; min-width: 26%; }
  .seg-word { font-size: 0.85rem; }
  .seg-count { font-size: 0.8rem; }
  .issue-body { padding: 12px 14px 10px 14px; }
  .issue-head { flex-direction: column; gap: 2px; }
  .issue-amount small { text-align: left; }
  .sides { grid-template-columns: 1fr; gap: 8px; }
  .ex-grid { grid-template-columns: 1fr; }
  .cmp-grid { gap: 8px; }
  .cmp-col { padding: 10px 10px; }
  .cmp-row { flex-direction: column; gap: 0; }
  .cmp-value { font-size: 1.05rem; }
  .section-title { font-size: 1.3rem; }
}
"""


def inject() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
