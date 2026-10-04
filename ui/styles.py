"""Общий CSS экрана. Один вызов st.markdown; HTML карточек и бейджей собирается в ui/components.py."""
import streamlit as st

CSS = """
:root { --navy: #1F3A5F; --ink: #1B2430; --muted: #5B6675; --line: #E3E8EF; --panel: #F4F6F9; --radius: 12px;
        --shadow: 0 1px 3px rgba(31, 58, 95, 0.10), 0 1px 2px rgba(31, 58, 95, 0.06); }
.block-container { max-width: 1180px; padding-top: 2rem; padding-bottom: 3rem; }
#MainMenu, footer { visibility: hidden; }
h2, h3 { color: var(--navy); letter-spacing: -0.01em; }
.app-title { font-size: 1.9rem; font-weight: 700; color: var(--navy); line-height: 1.2; margin: 0; }
.app-sub { color: var(--muted); font-size: 1.02rem; margin: 0.25rem 0 0.6rem 0; }
.pill { display: inline-block; font-size: 0.78rem; font-weight: 600; padding: 2px 10px; border-radius: 999px;
        background: var(--panel); color: var(--navy); border: 1px solid var(--line); vertical-align: middle; margin-left: 8px; }
.mode-line { color: var(--ink); font-size: 0.95rem; margin: 0 0 0.4rem 0; }
.banner { background: #FFF4CC; color: #4A3B00; border: 1px solid #F0D875; border-radius: var(--radius); padding: 0.7rem 1rem;
          margin: 0.6rem 0 1rem 0; font-size: 0.95rem; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 0.8rem 0 0.4rem 0; }
.metric-card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 14px 16px; }
.metric-label { color: var(--muted); font-size: 0.85rem; }
.metric-value { color: var(--navy); font-size: 1.9rem; font-weight: 700; line-height: 1.15; margin-top: 2px; white-space: nowrap; }
.metric-note { color: var(--muted); font-size: 0.74rem; margin-top: 4px; line-height: 1.3; }
.note-small { color: var(--muted); font-size: 0.8rem; margin: 0.2rem 0 0.8rem 0; }
.traffic { display: flex; width: 100%; border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); margin-top: 0.4rem; }
.seg { padding: 12px 10px; min-width: 24%; text-align: center; box-sizing: border-box; }
.seg-word { font-weight: 700; font-size: 1rem; }
.seg-count { font-size: 0.92rem; }
.legend { color: var(--muted); font-size: 0.84rem; margin: 0.5rem 0 1rem 0; line-height: 1.4; }
.section-title { color: var(--navy); font-size: 1.25rem; font-weight: 700; margin: 1.6rem 0 0.2rem 0; }
.section-sub { color: var(--muted); font-size: 0.88rem; margin: 0 0 0.6rem 0; }
.issue-card { display: flex; background: #fff; border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow);
              margin: 0 0 12px 0; overflow: hidden; }
.issue-bar { width: 8px; flex: 0 0 8px; }
.issue-body { padding: 12px 16px; min-width: 0; flex: 1; }
.issue-title { color: var(--ink); font-weight: 700; font-size: 1.05rem; margin: 0 0 6px 0; overflow-wrap: anywhere; }
.badge { display: inline-block; font-size: 0.74rem; font-weight: 600; padding: 2px 9px; border-radius: 999px; margin: 0 6px 6px 0;
         background: var(--panel); color: var(--navy); border: 1px solid var(--line); }
.badge-high { background: #FDECEA; color: #8E1B1B; border-color: #F3C4C0; }
.badge-medium { background: #FFF6DB; color: #5A4300; border-color: #F0D875; }
.badge-low { background: #EEF0F3; color: #3F4955; border-color: #D5DAE1; }
.badge-ai { background: #E8EEF7; color: var(--navy); border-color: #C5D3E8; }
.issue-phrase { color: var(--ink); font-size: 0.97rem; margin: 2px 0; overflow-wrap: anywhere; }
.issue-impact { color: var(--ink); font-size: 0.93rem; font-weight: 600; margin: 4px 0 2px 0; }
.issue-note { color: #5A4300; font-size: 0.84rem; margin: 2px 0; }
.issue-src { color: #6B7480; font-size: 0.78rem; margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; }
.how { background: var(--panel); border-radius: var(--radius); padding: 0.8rem 1rem; color: var(--ink); margin-top: 1.6rem; font-size: 0.95rem; }
.app-footer { color: var(--muted); font-size: 0.82rem; text-align: center; margin-top: 1.4rem; padding-top: 0.8rem; border-top: 1px solid var(--line); }
.ai-line { background: #E8EEF7; color: var(--navy); border-radius: var(--radius); padding: 0.6rem 1rem; font-weight: 600; font-size: 0.97rem;
           margin: 0.2rem 0 0.8rem 0; border-left: 5px solid var(--navy); }
.ai-box { background: #F1F5FB; border: 1px solid #D5E0F0; border-radius: 10px; padding: 8px 12px; margin: 8px 0 4px 0; }
.ai-title { color: var(--navy); font-weight: 700; font-size: 0.85rem; margin-bottom: 4px; }
.ai-pair { margin: 4px 0 6px 0; overflow-wrap: anywhere; }
.ai-names { color: var(--ink); font-size: 0.9rem; }
.ai-before { color: #5B6675; }
.ai-after { color: var(--navy); font-weight: 600; }
.ai-arrow { color: var(--navy); font-weight: 700; }
.ai-meta { color: var(--muted); font-size: 0.8rem; margin-top: 2px; }
.cmp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 0.6rem 0 0.2rem 0; }
.cmp-col { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px 16px; }
.cmp-ai { border: 2px solid var(--navy); }
.cmp-title { color: var(--navy); font-weight: 700; font-size: 1.05rem; margin-bottom: 6px; }
.cmp-row { display: flex; justify-content: space-between; gap: 8px; padding: 5px 0; border-top: 1px solid var(--line); font-size: 0.93rem; }
.cmp-label { color: var(--muted); }
.cmp-value { color: var(--ink); font-weight: 700; white-space: nowrap; }
.ex-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 0.6rem; }
.ex-card { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px 14px; min-width: 0; }
.ex-row { display: flex; flex-direction: column; margin: 0 0 8px 0; font-size: 0.86rem; color: var(--ink); overflow-wrap: anywhere; }
.ex-label { color: var(--muted); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; }
.ex-ai { background: #E8EEF7; border-radius: 8px; padding: 4px 8px; }
@media (max-width: 900px) { .ex-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) {
  .ex-grid { grid-template-columns: 1fr; }
  .cmp-grid { gap: 8px; }
  .cmp-col { padding: 10px 10px; }
  .cmp-row { flex-direction: column; gap: 0; }
  .cmp-value { font-size: 1.05rem; }
  .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1.2rem; }
  .app-title { font-size: 1.45rem; }
  .metric-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .metric-value { font-size: 1.45rem; }
  .seg { padding: 10px 4px; min-width: 26%; }
  .seg-word { font-size: 0.85rem; }
  .seg-count { font-size: 0.8rem; }
  .issue-body { padding: 10px 12px; }
}
"""


def inject() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
