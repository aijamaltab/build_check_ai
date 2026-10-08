"""Экран детального аудита исходных документов: Google Sheets Lookalike (new_feat.md).

Дизайн:
- Полноэкранный режим: таблица занимает 100% ширины и 100% высоты окна.
- Выезжающая панель деталей проекта (Hover Reveal): появляется плавно при наведении на верхнюю границу.
- Строка формул fx закреплена непосредственно над сеткой данных.
- Интерактивные поповеры и сквозная навигация между документами (ВОР ↔ Смета ↔ Акты).
"""
import json
import streamlit as st

from ui import runner
from ui.data import fmt_num
from ui.screens.empty import empty_state
from ui.sheet_builder import build_sheet_audit_model

DEFAULT_HEIGHT = 880

TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
:root {
  --bg-app: #f8f9fa;
  --bg-sheet: #ffffff;
  --grid-line: #e1e3e1;
  --header-bg: #f8f9fa;
  --header-text: #5f6368;
  --text-main: #1f1f1f;
  --text-muted: #5f6368;
  --accent: #1a73e8;
  --accent-light: #e8f0fe;
  
  --red-bg: #fde8e8;
  --red-border: #f98080;
  --red-marker: #e02424;
  
  --yellow-bg: #fef08a;
  --yellow-border: #facc15;
  --yellow-marker: #ca8a04;
  
  --purple-bg: #f3e8ff;
  --purple-border: #d8b4fe;
  --purple-marker: #9333ea;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  width: 100vw;
  height: 100vh;
  margin: 0;
  padding: 0;
  overflow: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg-app);
  color: var(--text-main);
  user-select: none;
}

.app-wrapper {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  position: relative;
}

/* 0. ВСПЛЫВАЮЩАЯ ПАНЕЛЬ ДЕТАЛЕЙ ПРОЕКТА (Hover Reveal) */
.project-drawer {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 500;
  transform: translateY(-100%);
  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.28s;
  pointer-events: auto;
}

.project-drawer:hover,
.project-drawer:focus-within,
.project-drawer.is-pinned {
  transform: translateY(0);
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.16), 0 2px 8px rgba(15, 23, 42, 0.08);
}

.project-drawer-content {
  background: #ffffff;
  border-bottom: 1px solid #d0d7de;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.project-info-col {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.project-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.project-title {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}
.project-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}
.project-badge.mode { background: #e0f2fe; color: #0369a1; }
.project-badge.demo { background: #f3f4f6; color: #4b5563; }
.project-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.project-metrics-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.metric-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 4px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  min-width: 64px;
}
.metric-val {
  font-size: 14px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  color: #111827;
}
.metric-lbl {
  font-size: 10px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.metric-box.alert {
  background: #fef2f2;
  border-color: #fecaca;
}
.metric-box.alert .metric-val { color: #dc2626; }
.metric-box.budget {
  background: #fef2f2;
  border-color: #fecaca;
  min-width: 120px;
}
.metric-box.budget .metric-val { color: #b91c1c; }

.traffic-strip {
  display: flex;
  gap: 6px;
}
.traffic-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
}
.traffic-pill.red { background: #fee2e2; color: #991b1b; }
.traffic-pill.yellow { background: #fef9c3; color: #854d0e; }
.traffic-pill.green { background: #dcfce7; color: #166534; }

/* Аккуратный язычок-триггер по центру вверху */
.project-drawer-handle {
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-top: none;
  border-radius: 0 0 8px 8px;
  padding: 4px 16px;
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(0,0,0,0.08);
  white-space: nowrap;
  transition: all 0.2s ease;
}
.project-drawer:hover .project-drawer-handle {
  background: #f9fafb;
  color: #111827;
}
.handle-caret {
  font-size: 9px;
  color: #6b7280;
  transition: transform 0.25s;
}
.project-drawer:hover .handle-caret {
  transform: rotate(180deg);
}

/* 1. СТРОКА ФОРМУЛ FORMULA BAR */
.formula-bar-container {
  display: flex;
  align-items: center;
  background: #ffffff;
  border-bottom: 1px solid var(--grid-line);
  padding: 4px 12px;
  gap: 8px;
  height: 36px;
  flex: none;
  z-index: 10;
}

.cell-name-box {
  width: 76px;
  height: 26px;
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.fx-label {
  font-family: 'JetBrains Mono', serif;
  font-style: italic;
  font-weight: 700;
  color: #747775;
  font-size: 15px;
  padding: 0 4px;
}

.formula-input {
  flex: 1;
  height: 26px;
  border: 1px solid #d0d7de;
  border-radius: 4px;
  padding: 0 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: var(--text-main);
  background: #ffffff;
  outline: none;
}
.formula-input:focus {
  border-color: var(--accent);
}

.toolbar-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}
.stat-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 500;
}
.stat-chip.red { background: var(--red-bg); color: #9b1c1c; }
.stat-chip.yellow { background: var(--yellow-bg); color: #713f12; }
.stat-chip.purple { background: var(--purple-bg); color: #6b21a8; }

/* 2. ПОЛНОРАЗМЕРНАЯ 2D СЕТКА ТАБЛИЦЫ */
.sheet-viewport {
  flex: 1;
  width: 100%;
  height: 100%;
  overflow: auto;
  background: #ffffff;
  position: relative;
}

.sheet-table {
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
  background: #ffffff;
  width: 100%;
}

/* Координатные заголовки */
th.corner-header {
  position: sticky;
  top: 0;
  left: 0;
  z-index: 20;
  width: 44px;
  height: 26px;
  background: var(--header-bg);
  border-right: 1px solid var(--grid-line);
  border-bottom: 1px solid var(--grid-line);
}

th.col-header {
  position: sticky;
  top: 0;
  z-index: 10;
  height: 26px;
  background: var(--header-bg);
  color: var(--header-text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  vertical-align: middle;
  border-right: 1px solid var(--grid-line);
  border-bottom: 1px solid var(--grid-line);
  padding: 0 4px;
}

td.row-header {
  position: sticky;
  left: 0;
  z-index: 8;
  width: 44px;
  background: var(--header-bg);
  color: var(--header-text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  text-align: center;
  vertical-align: middle;
  border-right: 1px solid var(--grid-line);
  border-bottom: 1px solid var(--grid-line);
}

/* Обычные ячейки данных */
td.sheet-cell {
  border-right: 1px solid var(--grid-line);
  border-bottom: 1px solid var(--grid-line);
  padding: 3px 8px;
  font-size: 12.5px;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  position: relative;
  height: 26px;
  line-height: 20px;
  cursor: cell;
}

td.sheet-cell.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

/* Выделенная активная ячейка */
td.sheet-cell.selected-cell {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
  z-index: 5;
}
th.col-header.header-active, td.row-header.header-active {
  background: #e8eaed;
  color: var(--accent);
  font-weight: 700;
}

/* Светофорная подсветка рисков */
td.sheet-cell.status-critical {
  background-color: var(--red-bg) !important;
  color: #9b1c1c;
  cursor: pointer;
}
td.sheet-cell.status-critical::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 0 7px 7px 0;
  border-color: transparent var(--red-marker) transparent transparent;
}

td.sheet-cell.status-warning {
  background-color: var(--yellow-bg) !important;
  color: #713f12;
  cursor: pointer;
}
td.sheet-cell.status-warning::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 0 7px 7px 0;
  border-color: transparent var(--yellow-marker) transparent transparent;
}

td.sheet-cell.status-ai-matched {
  background-color: var(--purple-bg) !important;
  color: #581c87;
  cursor: pointer;
}
td.sheet-cell.status-ai-matched::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 0 7px 7px 0;
  border-color: transparent var(--purple-marker) transparent transparent;
}

/* Анимация перелёта фокуса */
@keyframes cellJumpGlow {
  0% { background-color: #fef08a; transform: scale(1.04); }
  50% { background-color: #bfdbfe; transform: scale(1.02); }
  100% { transform: scale(1); }
}
.cell-jump-flash {
  animation: cellJumpGlow 1.2s ease-out;
  outline: 3px solid #2563eb !important;
  z-index: 12 !important;
}

/* 3. ВСПЛЫВАЮЩАЯ НИЖНЯЯ ПАНЕЛЬ ВКЛАДОК (Hover Reveal) */
.sheet-tabs-drawer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 500;
  transform: translateY(100%);
  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.28s;
  pointer-events: auto;
}

.sheet-tabs-drawer:hover,
.sheet-tabs-drawer:focus-within,
.sheet-tabs-drawer.is-pinned {
  transform: translateY(0);
  box-shadow: 0 -12px 36px rgba(15, 23, 42, 0.16), 0 -2px 8px rgba(15, 23, 42, 0.08);
}

.sheet-tabs-container {
  display: flex;
  align-items: center;
  background: #ffffff;
  border-top: 1px solid #d0d7de;
  height: 42px;
  padding: 0 16px;
  gap: 6px;
  overflow-x: auto;
  box-shadow: 0 -4px 16px rgba(0,0,0,0.06);
}

.sheet-tab-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  color: #374151;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.sheet-tab-button:hover {
  background: #e5e7eb;
}
.sheet-tab-button.active {
  background: var(--accent);
  color: #ffffff;
  font-weight: 600;
  border-color: var(--accent);
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 8px;
}
.tab-badge.red { background: var(--red-bg); color: #9b1c1c; }
.tab-badge.yellow { background: var(--yellow-bg); color: #713f12; }
.tab-badge.ai { background: var(--purple-bg); color: #6b21a8; }
.sheet-tab-button.active .tab-badge.red { background: #fee2e2; color: #991b1b; }
.sheet-tab-button.active .tab-badge.yellow { background: #fef9c3; color: #854d0e; }
.sheet-tab-button.active .tab-badge.ai { background: #f3e8ff; color: #6b21a8; }

/* Аккуратный язычок-индикатор по центру снизу */
.sheet-tabs-handle {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  padding: 4px 16px;
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 -3px 10px rgba(0,0,0,0.08);
  white-space: nowrap;
  transition: all 0.2s ease;
}

.sheet-tabs-drawer:hover .sheet-tabs-handle {
  background: #f9fafb;
  color: #111827;
}

.tabs-handle-caret {
  font-size: 9px;
  color: #6b7280;
  transition: transform 0.25s;
}

.sheet-tabs-drawer:hover .tabs-handle-caret {
  transform: rotate(180deg);
}

/* 4. ИНТЕРАКТИВНЫЙ ПОПОВЕР РАСХОЖДЕНИЯ */
.popover-card {
  position: fixed;
  display: none;
  z-index: 1000;
  width: 360px;
  max-width: 90vw;
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(14, 17, 23, 0.18), 0 2px 6px rgba(14, 17, 23, 0.08);
  padding: 14px 16px;
  font-size: 13px;
  animation: popoverFadeIn 0.15s ease-out;
}
@keyframes popoverFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #f0f2f5;
}
.popover-title-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.popover-close {
  background: none;
  border: none;
  color: #747775;
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
}
.popover-close:hover { color: #1f1f1f; }

.popover-body {
  margin-bottom: 12px;
}
.popover-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: #f8f9fa;
  border-radius: 6px;
  padding: 8px 10px;
  margin: 8px 0;
  font-size: 12px;
}
.popover-cell-label {
  color: var(--text-muted);
  font-size: 11px;
}
.popover-cell-val {
  font-weight: 600;
  color: var(--text-main);
  font-family: 'JetBrains Mono', monospace;
}
.popover-cell-delta {
  font-weight: 700;
  color: #c62828;
  font-family: 'JetBrains Mono', monospace;
}

.popover-expl {
  color: #374151;
  font-size: 12px;
  line-height: 1.4;
  margin: 8px 0 4px 0;
}

.popover-ai-box {
  background: #faf5ff;
  border: 1px solid #e9d5ff;
  border-radius: 6px;
  padding: 8px 10px;
  margin: 6px 0;
  font-size: 12px;
  color: #581c87;
}

.popover-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
}
.jump-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--accent);
  color: #ffffff;
  border: none;
  border-radius: 5px;
  padding: 6px 14px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.jump-button:hover {
  background: #1557b0;
}
</style>
</head>
<body>

<div class="app-wrapper">
  <!-- ВСПЛЫВАЮЩАЯ ПАНЕЛЬ ДЕТАЛЕЙ ПРОЕКТА (Hover Reveal) -->
  <div class="project-drawer" id="project-drawer">
    <div class="project-drawer-content">
      <div class="project-info-col">
        <div class="project-title-row">
          <span class="project-title" id="drawer-proj-name">Капремонт школы</span>
          <span class="project-badge demo">Демо-проект</span>
          <span class="project-badge mode" id="drawer-proj-mode">С ИИ (Gemini)</span>
        </div>
        <div class="project-sub">
          Сквозной аудит исходных файлов и трассировка отклонений (ВОР ↔ Смета ↔ Договор ↔ Акты КС-2)
        </div>
      </div>
      <div class="project-metrics-row">
        <div class="metric-box">
          <span class="metric-val" id="drawer-files-val">9</span>
          <span class="metric-lbl">файлов</span>
        </div>
        <div class="metric-box">
          <span class="metric-val" id="drawer-rows-val">181</span>
          <span class="metric-lbl">строк</span>
        </div>
        <div class="metric-box alert">
          <span class="metric-val" id="drawer-issues-val">13</span>
          <span class="metric-lbl">расхождений</span>
        </div>
        <div class="metric-box budget">
          <span class="metric-val" id="drawer-budget-val">1 378 030 сом</span>
          <span class="metric-lbl">влияние на бюджет</span>
        </div>
      </div>
      <div class="traffic-strip">
        <span class="traffic-pill red" id="drawer-red-pill">11 🔴</span>
        <span class="traffic-pill yellow" id="drawer-yellow-pill">7 🟡</span>
        <span class="traffic-pill green" id="drawer-green-pill">30 🟢</span>
      </div>
    </div>
    <div class="project-drawer-handle" id="drawer-handle">
      <span class="handle-caret">▼</span>
      <span id="handle-summary">Капремонт школы · 13 расхождений · 1 378 030 сом</span>
    </div>
  </div>

  <!-- ВЕРХНЯЯ ПАНЕЛЬ: FORMULA BAR -->
  <div class="formula-bar-container">
    <div class="cell-name-box" id="cell-address-box">A1</div>
    <div class="fx-label">fx</div>
    <input type="text" class="formula-input" id="formula-input-box" readonly placeholder="Выберите ячейку...">
    <div class="toolbar-stats" id="sheet-stats">
      <!-- Бейджи статистики активного листа -->
    </div>
  </div>

  <!-- ОСНОВНАЯ СЕТКА ТАБЛИЦЫ -->
  <div class="sheet-viewport" id="viewport">
    <table class="sheet-table" id="grid-table">
      <thead id="grid-thead"></thead>
      <tbody id="grid-tbody"></tbody>
    </table>
  </div>

  <!-- ВСПЛЫВАЮЩАЯ НИЖНЯЯ ПАНЕЛЬ ВКЛАДОК (Hover Reveal) -->
  <div class="sheet-tabs-drawer" id="tabs-drawer">
    <div class="sheet-tabs-handle" id="tabs-handle">
      <span class="tabs-handle-caret">▲</span>
      <span id="tabs-handle-text">Документы · Наведите для выбора</span>
    </div>
    <div class="sheet-tabs-container" id="tabs-container"></div>
  </div>
</div>

<!-- ИНТЕРАКТИВНЫЙ ПОПОВЕР -->
<div class="popover-card" id="audit-popover">
  <div class="popover-header">
    <div class="popover-title-badge" id="popover-badge">🔴 Превышение</div>
    <button class="popover-close" id="popover-close-btn">&times;</button>
  </div>
  <div class="popover-body" id="popover-content"></div>
  <div class="popover-footer" id="popover-footer"></div>
</div>

<script>
const DATA = __DATA__;
let currentDocId = DATA.active_doc;
let selectedCellCoord = null;

// Инициализация интерфейса
function init() {
  populateProjectDrawer();
  renderTabs();
  loadSheet(currentDocId);
  setupEvents();
}

function populateProjectDrawer() {
  const p = DATA.project;
  if (!p) return;
  if (p.name) document.getElementById("drawer-proj-name").textContent = p.name;
  if (p.mode) document.getElementById("drawer-proj-mode").textContent = p.mode;
  if (p.files) document.getElementById("drawer-files-val").textContent = p.files;
  if (p.items) document.getElementById("drawer-rows-val").textContent = p.items;
  if (p.issues !== undefined) document.getElementById("drawer-issues-val").textContent = p.issues;
  if (p.impact_som) document.getElementById("drawer-budget-val").textContent = p.impact_som;
  if (p.red !== undefined) document.getElementById("drawer-red-pill").textContent = `${p.red} 🔴`;
  if (p.yellow !== undefined) document.getElementById("drawer-yellow-pill").textContent = `${p.yellow} 🟡`;
  if (p.green !== undefined) document.getElementById("drawer-green-pill").textContent = `${p.green} 🟢`;
  
  const handleText = `${p.name || 'Проект'} · ${p.issues || 0} расхождений · ${p.impact_som || ''}`;
  document.getElementById("handle-summary").textContent = handleText;
}

// Рендер вкладок документов
function renderTabs() {
  const container = document.getElementById("tabs-container");
  container.innerHTML = "";
  
  DATA.tabs.forEach(tab => {
    const btn = document.createElement("button");
    btn.className = "sheet-tab-button" + (tab.id === currentDocId ? " active" : "");
    btn.setAttribute("data-doc-id", tab.id);
    
    let badges = "";
    if (tab.red_count > 0) badges += `<span class="tab-badge red">🔴 ${tab.red_count}</span>`;
    if (tab.yellow_count > 0) badges += `<span class="tab-badge yellow">🟡 ${tab.yellow_count}</span>`;
    if (tab.ai_count > 0) badges += `<span class="tab-badge ai">🟣 ${tab.ai_count}</span>`;
    
    btn.innerHTML = `<span>${tab.title}</span>${badges}`;
    btn.addEventListener("click", () => {
      switchSheet(tab.id);
    });
    container.appendChild(btn);
  });
  updateTabsHandle();
}

function updateTabsHandle() {
  const activeTab = DATA.tabs.find(t => t.id === currentDocId);
  const handleEl = document.getElementById("tabs-handle-text");
  if (!handleEl || !activeTab) return;
  let badges = "";
  if (activeTab.red_count > 0) badges += ` 🔴 ${activeTab.red_count}`;
  if (activeTab.yellow_count > 0) badges += ` 🟡 ${activeTab.yellow_count}`;
  if (activeTab.ai_count > 0) badges += ` 🟣 ${activeTab.ai_count}`;
  handleEl.textContent = `Документ: ${activeTab.title}${badges ? ' ·' + badges : ''} · Наведите для выбора (всего ${DATA.tabs.length} файлов)`;
}

// Переключение активного листа
function switchSheet(docId, targetCellCoord = null) {
  if (!DATA.sheets[docId]) return;
  currentDocId = docId;
  
  // Обновляем вкладки
  document.querySelectorAll(".sheet-tab-button").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-doc-id") === docId);
  });
  updateTabsHandle();
  
  hidePopover();
  loadSheet(docId, targetCellCoord);
}

// Загрузка и рендер сетки конкретного документа
function loadSheet(docId, targetCellCoord = null) {
  const sheet = DATA.sheets[docId];
  if (!sheet) return;

  const thead = document.getElementById("grid-thead");
  const tbody = document.getElementById("grid-tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  
  // Обновляем статистику листа
  updateSheetStats(sheet);

  // 1. Формируем строку колонок (Corner + A, B, C...)
  const trHead = document.createElement("tr");
  const thCorner = document.createElement("th");
  thCorner.className = "corner-header";
  trHead.appendChild(thCorner);

  sheet.columns.forEach((col, idx) => {
    const th = document.createElement("th");
    th.className = "col-header";
    th.id = "col-th-" + col;
    th.textContent = col;
    if (col === "A") th.style.width = "48px";
    else if (col === "B" || col === "C") th.style.width = "260px";
    else th.style.width = "110px";
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);

  // 2. Формируем строки данных
  sheet.rows.forEach(r => {
    const tr = document.createElement("tr");
    
    // Номер строки
    const tdRowHead = document.createElement("td");
    tdRowHead.className = "row-header";
    tdRowHead.id = "row-td-" + r.row_num;
    tdRowHead.textContent = r.row_num;
    tr.appendChild(tdRowHead);

    sheet.columns.forEach(col => {
      const td = document.createElement("td");
      const cell = r.cells[col] || { value: "", formula: null, display: "", status: null };
      const coord = col + r.row_num;
      
      td.className = "sheet-cell";
      td.id = "cell-" + coord;
      td.setAttribute("data-coord", coord);
      td.setAttribute("data-col", col);
      td.setAttribute("data-row", r.row_num);
      
      if (typeof cell.value === "number" || (!isNaN(cell.value) && cell.value !== "" && cell.value !== null)) {
        td.classList.add("num");
      }

      if (cell.status === "critical") td.classList.add("status-critical");
      else if (cell.status === "warning") td.classList.add("status-warning");
      else if (cell.status === "ai-matched") td.classList.add("status-ai-matched");

      td.textContent = cell.display || cell.value || "";
      
      td.addEventListener("click", (e) => {
        selectCell(col, r.row_num, cell, td, e);
      });

      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  // Выбор ячейки
  if (targetCellCoord) {
    const targetTd = document.getElementById("cell-" + targetCellCoord);
    if (targetTd) {
      const col = targetTd.getAttribute("data-col");
      const row = targetTd.getAttribute("data-row");
      const cellData = getCellData(docId, col, parseInt(row));
      selectCell(col, row, cellData, targetTd);
      
      targetTd.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
      targetTd.classList.add("cell-jump-flash");
      setTimeout(() => targetTd.classList.remove("cell-jump-flash"), 1500);
    }
  } else {
    const firstIssue = findFirstIssueCell(sheet);
    if (firstIssue) {
      const td = document.getElementById("cell-" + firstIssue.coord);
      if (td) selectCell(firstIssue.col, firstIssue.row, firstIssue.cell, td);
    } else {
      const a1 = document.getElementById("cell-A1");
      if (a1) selectCell("A", 1, getCellData(docId, "A", 1), a1);
    }
  }
}

function getCellData(docId, col, row) {
  const sheet = DATA.sheets[docId];
  if (!sheet) return null;
  const rowObj = sheet.rows.find(r => r.row_num === parseInt(row));
  return rowObj ? rowObj.cells[col] : null;
}

function findFirstIssueCell(sheet) {
  for (let r of sheet.rows) {
    for (let c of sheet.columns) {
      const cell = r.cells[c];
      if (cell && cell.status === "critical") {
        return { coord: c + r.row_num, col: c, row: r.row_num, cell: cell };
      }
    }
  }
  return null;
}

function updateSheetStats(sheet) {
  const container = document.getElementById("sheet-stats");
  let red = 0, yellow = 0, ai = 0;
  sheet.rows.forEach(r => {
    sheet.columns.forEach(c => {
      const st = r.cells[c]?.status;
      if (st === "critical") red++;
      else if (st === "warning") yellow++;
      else if (st === "ai-matched") ai++;
    });
  });
  
  let html = `<span><b>Лист:</b> ${sheet.file_name}</span>`;
  if (red > 0) html += `<span class="stat-chip red">🔴 ${red} крит.</span>`;
  if (yellow > 0) html += `<span class="stat-chip yellow">🟡 ${yellow} пред.</span>`;
  if (ai > 0) html += `<span class="stat-chip purple">🟣 ${ai} с ИИ</span>`;
  container.innerHTML = html;
}

function selectCell(col, row, cellData, tdElement, event = null) {
  const coord = col + row;
  selectedCellCoord = coord;

  document.querySelectorAll(".sheet-cell.selected-cell").forEach(el => el.classList.remove("selected-cell"));
  document.querySelectorAll(".header-active").forEach(el => el.classList.remove("header-active"));

  tdElement.classList.add("selected-cell");
  const colTh = document.getElementById("col-th-" + col);
  const rowTd = document.getElementById("row-td-" + row);
  if (colTh) colTh.classList.add("header-active");
  if (rowTd) rowTd.classList.add("header-active");

  document.getElementById("cell-address-box").textContent = coord;
  const formulaBox = document.getElementById("formula-input-box");
  formulaBox.value = cellData && cellData.formula ? cellData.formula : (cellData ? (cellData.value ?? "") : "");

  if (cellData && (cellData.issue || cellData.ai_match)) {
    showPopover(cellData, tdElement);
  } else {
    hidePopover();
  }
}

function showPopover(cellData, tdElement) {
  const popover = document.getElementById("audit-popover");
  const badge = document.getElementById("popover-badge");
  const content = document.getElementById("popover-content");
  const footer = document.getElementById("popover-footer");
  
  const issue = cellData.issue;
  const ai = cellData.ai_match;

  if (issue) {
    const isCrit = issue.severity === "critical" || cellData.status === "critical";
    badge.innerHTML = isCrit ? `🔴 ${issue.title}` : `🟡 ${issue.title}`;
    badge.style.color = isCrit ? "#9b1c1c" : "#713f12";

    let html = `
      <div class="popover-grid">
        <div>
          <div class="popover-cell-label">План (ВОР / Смета):</div>
          <div class="popover-cell-val">${issue.plan || "—"}</div>
        </div>
        <div>
          <div class="popover-cell-label">Факт (По актам):</div>
          <div class="popover-cell-val">${issue.fact || "—"}</div>
        </div>
      </div>
      <div class="popover-grid">
        <div>
          <div class="popover-cell-label">Отклонение (Δ):</div>
          <div class="popover-cell-delta">${issue.delta || "—"}</div>
        </div>
        <div>
          <div class="popover-cell-label">Влияние на бюджет:</div>
          <div class="popover-cell-val" style="color:#b91c1c;">${issue.impact_som || "—"}</div>
        </div>
      </div>
    `;

    if (issue.explanation) {
      html += `<div class="popover-expl">${issue.explanation}</div>`;
    }

    content.innerHTML = html;

    if (issue.target_jump) {
      footer.innerHTML = `
        <button class="jump-button" id="jump-btn">
          ↗ Показать в ${issue.target_jump.title} (${issue.target_jump.cell})
        </button>
      `;
      document.getElementById("jump-btn").onclick = () => {
        executeJump(issue.target_jump);
      };
    } else {
      footer.innerHTML = `<span style="font-size:11px;color:#6b7280;">Позиция отсутствует во втором документе</span>`;
    }

  } else if (ai) {
    badge.innerHTML = `🟣 Сопоставлено ИИ`;
    badge.style.color = "#6b21a8";

    let html = `
      <div class="popover-ai-box">
        <b>Семантический анализ Gemini:</b><br>
        «${ai.doc_name}» ↔ «${ai.vor_name}»<br>
        <div style="margin-top:4px;font-size:11px;">Уверенность: <b>${(ai.confidence * 100).toFixed(0)}%</b></div>
      </div>
      <div class="popover-expl">${ai.reason}</div>
    `;
    content.innerHTML = html;

    if (ai.target_jump) {
      footer.innerHTML = `
        <button class="jump-button" id="jump-btn">
          ↗ Показать пару в ${ai.target_jump.title} (${ai.target_jump.cell})
        </button>
      `;
      document.getElementById("jump-btn").onclick = () => {
        executeJump(ai.target_jump);
      };
    } else {
      footer.innerHTML = "";
    }
  }

  const rect = tdElement.getBoundingClientRect();
  const popWidth = 360;
  const popHeight = 220;
  
  let left = rect.left;
  let top = rect.bottom + 6;

  if (left + popWidth > window.innerWidth - 16) {
    left = window.innerWidth - popWidth - 16;
  }
  if (top + popHeight > window.innerHeight - 44) {
    top = rect.top - popHeight - 6;
  }

  popover.style.left = Math.max(10, left) + "px";
  popover.style.top = Math.max(10, top) + "px";
  popover.style.display = "block";
}

function hidePopover() {
  const popover = document.getElementById("audit-popover");
  if (popover) popover.style.display = "none";
}

function executeJump(targetJump) {
  hidePopover();
  switchSheet(targetJump.doc_id, targetJump.cell);
}

function setupEvents() {
  document.getElementById("popover-close-btn").addEventListener("click", hidePopover);
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hidePopover();
  });
}

window.addEventListener("DOMContentLoaded", init);
if (document.readyState === "complete" || document.readyState === "interactive") {
  init();
}
</script>
</body>
</html>
"""


def sheets_html(model: dict) -> str:
    """Формирует автономную HTML/JS страницу Google Sheets Lookalike."""
    data_json = json.dumps(model, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", data_json)


def render_sheets_view(model: dict, height: int = DEFAULT_HEIGHT) -> None:
    """Отрисовка интерактивного табличного процессора в Streamlit iframe на всю ширину и высоту."""
    html_content = sheets_html(model)
    if hasattr(st, "iframe"):
        st.iframe(html_content, height=height)
        return
    import streamlit.components.v1 as components
    components.html(html_content, height=height, scrolling=False)


def project_card(run: dict) -> dict:
    """Данные шапки-выдвижки из прогона: все числа берутся из сводки, ничего не зашито."""
    summary = run["summary"]
    statuses = summary.get("statuses", {})
    return {"name": run["label"], "mode": runner.mode_label(run), "files": summary.get("files", 0), "items": summary.get("n", 0),
            "issues": summary.get("z", 0), "impact_som": f"{fmt_num(summary.get('impact_som', 0))} сом",
            "red": int(statuses.get("red", 0)), "yellow": int(statuses.get("yellow", 0)), "green": int(statuses.get("green", 0))}


def sheets_model(run: dict) -> dict:
    """Модель таблиц для прогона; строится один раз и хранится в самом прогоне (страница без виджетов перерисовывается часто)."""
    if "sheets_model" not in run:
        model = build_sheet_audit_model(run["files_dir"], run["db_path"], run["project_id"])
        model["project"] = project_card(run)
        run["sheets_model"] = model
    return run["sheets_model"]


def render(upload_page=None) -> None:
    """Страница «Исходные таблицы» (Edge-to-edge / Fullscreen) по последнему прогону сессии."""
    run = runner.current_run()
    if run is None:
        empty_state(upload_page, key="sheets")
        return
    # Снимаем отступы контейнера Streamlit для полноэкранного режима
    st.markdown(
        """
        <style>
        /* Предотвращаем вертикальный скролл страницы: ровно 100vh */
        html, body, .stApp, section.main, .block-container {
            overflow: hidden !important;
            height: 100vh !important;
            max-height: 100vh !important;
        }

        .block-container {
            max-width: 100% !important;
            padding: 0rem !important;
            margin: 0rem !important;
            display: flex !important;
            flex-direction: column !important;
            height: 100vh !important;
        }

        [data-testid="stHeader"] {
            background: transparent !important;
            height: 0px !important;
            min-height: 0px !important;
            padding: 0 !important;
            border: none !important;
            pointer-events: none !important;
            z-index: 1000 !important;
        }

        /* Кнопка «Меню» (общий вид из ui/styles.py) в полосе topbar слева, высота 28px внутри полосы 38px */
        [data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            visibility: visible !important;
            pointer-events: auto !important;
            z-index: 10001 !important;
            position: fixed !important;
            top: 4px !important;
            left: 8px !important;
            height: 30px !important;
            margin: 0 !important;
            padding: 0 14px 0 12px !important;
        }

        /* Верхняя видимая панель фиксированной высоты 38px с отступом слева под кнопку «Меню» */
        .topbar {
            margin: 0 !important;
            padding: 6px 14px 6px 120px !important;
            border-radius: 0 !important;
            border-left: none !important;
            border-right: none !important;
            border-top: none !important;
            height: 38px !important;
            box-sizing: border-box !important;
            flex: none !important;
            display: flex !important;
            align-items: center !important;
        }

        /* На телефоне в полосе помещается только название проекта: одна строка, лишнее обрезается, режим скрыт */
        @media (max-width: 640px) {
            .topbar { padding-left: 116px !important; overflow: hidden !important; flex-wrap: nowrap !important; }
            .topbar-item { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; }
            .topbar-item:nth-child(n+2) { display: none !important; }
        }

        /* Вычитаем высоту верхней панели (38px) из полной высоты экрана для таблицы */
        iframe, [data-testid="stIFrame"], [data-testid="stCustomComponentV1"] {
            width: 100% !important;
            height: calc(100vh - 38px) !important;
            max-height: calc(100vh - 38px) !important;
            min-height: unset !important;
            border: none !important;
            display: block !important;
            flex: 1 1 auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    try:
        model = sheets_model(run)
    except Exception:  # noqa: BLE001: пользователю человеческая ошибка, подробности в логе Streamlit
        st.error("Не удалось построить исходные таблицы по этому прогону. Загрузите данные заново.")
        return

    render_sheets_view(model)
