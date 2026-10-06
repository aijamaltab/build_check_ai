"""«Сверочная ведомость»: собственная HTML/CSS/JS-таблица в st.components.v1.html (без внешних скриптов).

Данные из ui/ledger_data.build_ledger передаются JSON в теге script. Таблица только читает: фильтры, подсказки по наведению и по нажатию
(на телефоне наведения нет), панель сведений о строке под таблицей. Шрифт IBM Plex Sans подключается с Google Fonts, без сети будет sans-serif."""
import json

from ui.data import STATUS_COLORS

LEDGER_COLUMNS = [
    {"k": "n", "title": "№"}, {"k": "status", "title": "Статус"}, {"k": "name", "title": "Наименование (по ВОР)"}, {"k": "unit", "title": "Ед."},
    {"k": "plan", "title": "ВОР, кол-во", "num": True}, {"k": "fact", "title": "Акты, кол-во", "num": True},
    {"k": "pct", "title": "Выполнено, %", "num": True}, {"k": "est", "title": "Цена по смете", "num": True},
    {"k": "actp", "title": "Цена по акту (средняя)", "num": True, "hint": "Средневзвешенная по количеству, если актов несколько"},
    {"k": "dp", "title": "Δ цены, %", "num": True}]
# режим «только расхождения»: одна строка = одно расхождение; закреплённых колонок нет
ISSUE_COLUMNS = [
    {"k": "n", "title": "№"}, {"k": "type", "title": "Тип"}, {"k": "name", "title": "Работа"}, {"k": "text", "title": "Что не сходится"},
    {"k": "impact", "title": "Влияние, сом", "num": True}, {"k": "where", "title": "Где смотреть"}]
COLUMN_TITLES = [c["title"] for c in LEDGER_COLUMNS]
HEIGHT = 900
ISSUES_HEIGHT_BASE, ISSUES_HEIGHT_ROW = 330, 78      # запасной расчёт высоты; точная подгоняется скриптом по содержимому

TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root { --ink:#1B2733; --muted:#5B6877; --line:#D8DEE6; --bg:#F4F6F8; --accent:#1F4E79; --accent-soft:#E7EEF5; --red:#C62828; --yellow:#F9A825; --green:#2E7D32; }
* { box-sizing: border-box; }
html, body { margin:0; background:var(--bg); color:var(--ink); font:13px/1.4 'IBM Plex Sans','Segoe UI',Arial,sans-serif; font-variant-numeric: tabular-nums; }
body { padding: 2px 1px 12px 1px; }
.mode-issues .toolbar, .mode-issues #details, .mode-issues #docissues { display:none; }
.panel { background:#fff; border:1px solid var(--line); border-radius:6px; }
.toolbar { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; padding:10px 12px; margin-bottom:8px; }
.toolbar input[type=search], .toolbar select { height:32px; border:1px solid var(--line); border-radius:4px; padding:0 10px; font:inherit; background:#fff; color:var(--ink); min-width:0; }
.toolbar input[type=search] { width:240px; max-width:100%; }
.chips { display:flex; gap:6px; }
.chip { height:32px; padding:0 12px; border:1px solid var(--line); border-radius:4px; background:#fff; color:var(--ink); font:inherit; cursor:pointer; display:inline-flex; align-items:center; gap:6px; }
.chip[aria-pressed=true] { background:var(--accent-soft); border-color:var(--accent); font-weight:600; }
.chip:focus-visible, .toolbar input:focus-visible, .toolbar select:focus-visible, tr:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
.check { display:inline-flex; align-items:center; gap:6px; cursor:pointer; }
.count { margin-left:auto; color:var(--muted); font-size:13px; }
.wrap { max-height:430px; overflow:auto; }
table { border-collapse:separate; border-spacing:0; width:100%; min-width:840px; }
th { position:sticky; top:0; z-index:2; background:#EEF2F6; font-weight:600; text-align:left; padding:0 8px; height:40px; border-bottom:1px solid var(--line); white-space:nowrap; font-size:13px; }
td { height:34px; padding:0 8px; border-bottom:1px solid #E8ECF1; white-space:nowrap; background:#fff; }
th.num, td.num { text-align:right; }
td.c-name, th.c-name { white-space:normal; line-height:1.2; overflow-wrap:anywhere; }
.mode-issues .wrap { max-height:none; overflow:visible; }
.mode-issues table { min-width:0; }
.mode-issues th, .mode-issues td { white-space:normal; height:auto; padding:8px; vertical-align:top; overflow-wrap:anywhere; line-height:1.35; }
.mode-issues th { height:36px; vertical-align:middle; }
.mode-issues td.num { white-space:nowrap; }
.mode-issues .i-n { width:36px; } .mode-issues .i-type { width:150px; } .mode-issues .i-name { width:210px; } .mode-issues .i-impact { width:110px; }
.mode-issues .i-where { width:260px; color:var(--muted); font-size:12px; }
.sub { color:var(--muted); font-size:12px; }
.aib { display:inline-block; margin-left:6px; padding:0 6px; border-radius:4px; background:var(--accent-soft); color:var(--accent); border:1px solid #C9D8E6; font-size:11px; font-weight:600; vertical-align:middle; }
.c-n, .c-status, .c-name { position:sticky; background:#fff; }
th.c-n, th.c-status, th.c-name { background:#EEF2F6; z-index:4; }
td.c-n, td.c-status, td.c-name { z-index:1; }
.c-n { left:0; width:40px; min-width:40px; max-width:40px; }
.c-status { left:40px; width:112px; min-width:112px; max-width:112px; }
.c-name { left:152px; width:190px; min-width:190px; max-width:190px; box-shadow:2px 0 0 #D8DEE6; }
td.c-name.hl-red { box-shadow: inset 0 0 0 1px #E8B4AF, 2px 0 0 #D8DEE6; }
.hint { color:var(--accent); cursor:help; font-weight:400; }
tr { cursor:pointer; }
tr:hover td { background:#F7F9FB; }
tr.sel td { background:var(--accent-soft); }
td.hl-red, tr:hover td.hl-red, tr.sel td.hl-red { background:#FDECEA; box-shadow: inset 0 0 0 1px #E8B4AF; }
td.hl-yellow, tr:hover td.hl-yellow, tr.sel td.hl-yellow { background:#FFF6DB; box-shadow: inset 0 0 0 1px #EBCF8A; }
td[data-tip] { cursor:help; }
.st { display:inline-flex; align-items:center; gap:6px; font-weight:500; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; flex:none; }
.arr { font-size:11px; }
.muted { color:var(--muted); }
#tip { position:fixed; z-index:20; display:none; max-width:330px; background:#fff; border:1px solid var(--accent); border-radius:6px; padding:10px 12px; box-shadow:0 1px 3px rgba(0,0,0,.18); font-size:13px; }
#tip h4 { margin:0 0 4px 0; font-size:13px; }
#tip ul { margin:0 0 6px 0; padding-left:16px; }
#tip .src { color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
#tip .imp { font-weight:600; margin:4px 0; }
#tip .ai { color:var(--accent); margin-top:4px; }
.details { margin-top:8px; padding:12px 14px; }
.details h3 { margin:0 0 2px 0; font-size:16px; font-weight:600; }
.details h5 { margin:12px 0 4px 0; font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
.details .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:4px 18px; }
.details .row { padding:4px 0; border-bottom:1px solid #EEF1F5; overflow-wrap:anywhere; }
.details .where { color:var(--muted); font-size:12px; }
.issue { border-left:3px solid var(--red); padding:4px 0 4px 10px; margin:6px 0; }
.issue.y { border-left-color:var(--yellow); }
.empty { color:var(--muted); }
.docs { margin-top:8px; padding:10px 14px; }
.docs .row { padding:3px 0; overflow-wrap:anywhere; }
@media (max-width: 640px) {
  .mode-issues table, .mode-issues tbody, .mode-issues tr, .mode-issues td { display:block; width:100%; }
  .mode-issues thead { display:none; }
  .mode-issues tr { border-bottom:1px solid var(--line); padding:6px 0; }
  .mode-issues td { border:0; padding:3px 10px; text-align:left; }
  .mode-issues td::before { content:attr(data-label); display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .mode-issues td.i-n, .mode-issues td.i-type, .mode-issues td.i-name, .mode-issues td.i-impact, .mode-issues td.i-where { width:100%; }
 .c-n { width:32px; min-width:32px; max-width:32px; } .c-status { left:32px; width:100px; min-width:100px; max-width:100px; } .c-name { left:132px; width:120px; min-width:120px; max-width:120px; font-size:12px; } .toolbar input[type=search] { width:100%; } .count { margin-left:0; width:100%; } }
</style></head><body>
<div class="panel toolbar" role="search">
  <input id="q" type="search" placeholder="Поиск по названию" aria-label="Поиск по названию">
  <div class="chips" id="chips" role="group" aria-label="Статус светофора"></div>
  <label class="check"><input type="checkbox" id="dev"> Только позиции с отклонением от плана</label>
  <label class="check"><input type="checkbox" id="iss"> Только расхождения</label>
  <select id="unit" aria-label="Единица измерения"><option value="">Все единицы</option></select>
  <span class="count" id="count" aria-live="polite"></span>
</div>
<div class="panel wrap" id="wrap"><table>
  <thead><tr id="head"></tr></thead><tbody id="body"></tbody>
</table></div>
<div class="panel details" id="details"><span class="empty">Нажмите на строку, чтобы увидеть все источники и объяснение. Подсвеченные ячейки показывают, где есть расхождение: подсказка открывается по наведению и по нажатию.</span></div>
<div id="docissues"></div>
<div id="tip" role="tooltip"></div>
<script id="ledger-data" type="application/json">__DATA__</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById('ledger-data').textContent);
  var P = D.palette, C = D.columns, PRE = D.mode === 'issues' ? 'i-' : 'c-';
  var KEYS = C.map(function (c) { return c.k; });
  var NUM = {}; C.forEach(function (c) { if (c.num) NUM[c.k] = 1; });
  document.body.className = 'mode-' + D.mode;
  var CHIPS = [['red','Красные'],['yellow','Жёлтые'],['green','Зелёные']];
  var S = {q:'', stat:{}, dev:false, iss:false, unit:'', sel:null, pin:null};
  var $ = function (id) { return document.getElementById(id); };
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }

  $('head').innerHTML = KEYS.map(function (k, i) { return '<th class="' + PRE + k + ' ' + (NUM[k] ? 'num' : '') + '">' + esc(C[i].title) + (D.hints[k] ? ' <span class="hint" tabindex="0" role="button" aria-label="' + esc(D.hints[k]) + '" data-hint="' + k + '">ⓘ</span>' : '') + '</th>'; }).join('');
  $('chips').innerHTML = CHIPS.map(function (c) {
    return '<button type="button" class="chip" data-s="' + c[0] + '" aria-pressed="false"><span class="dot" style="background:' + P[c[0]] + '"></span>' + c[1] + '</button>';
  }).join('');
  $('unit').innerHTML += D.units.map(function (u) { return '<option>' + esc(u) + '</option>'; }).join('');

  function visible() {
    var q = S.q.trim().toLowerCase(), any = Object.keys(S.stat).some(function (k) { return S.stat[k]; });
    return D.rows.filter(function (r) {
      if (q && r.name.toLowerCase().indexOf(q) < 0) return false;
      if (any && !S.stat[r.status]) return false;
      if (S.dev && r.status === 'green') return false;
      if (S.iss && !r.has_issue) return false;
      if (S.unit && r.unit !== S.unit) return false;
      return true;
    });
  }
  function status(r) {
    var a = r.arrow === 'up' ? '<span class="arr" title="выше плана">▲</span>' : r.arrow === 'down' ? '<span class="arr" title="ниже плана">▼</span>' : '';
    return '<span class="st"><span class="dot" style="background:' + P[r.status] + '"></span>' + esc(r.status_ru) + a + '</span>';
  }
  function cell(r, k) {
    var hl = r.hl[k], tip = r.tips[k];
    var cls = PRE + k + ' ' + (NUM[k] ? 'num ' : '') + (hl ? 'hl-' + hl : '');
    var attr = (tip ? ' data-tip="' + k + '" tabindex="0"' : '') + ' data-label="' + esc(C[KEYS.indexOf(k)].title) + '"';
    var body = k === 'status' ? status(r) : k === 'where' ? (r.where || []).map(esc).join('<br>') : esc(r[k]);
    if (r[k + '_sub']) body += '<div class="sub">' + esc(r[k + '_sub']) + '</div>';
    if (k === 'name' && r.ai_badge) body += '<span class="aib" title="Пару названий сопоставил ИИ">ИИ</span>';
    return '<td class="' + cls + '"' + attr + '>' + body + '</td>';
  }
  function render() {
    var rows = visible();
    $('body').innerHTML = rows.length ? rows.map(function (r) {
      return '<tr data-n="' + r.n + '" tabindex="0" class="' + (S.sel === r.n ? 'sel' : '') + '">' + KEYS.map(function (k) { return cell(r, k); }).join('') + '</tr>';
    }).join('') : '<tr><td colspan="' + KEYS.length + '" class="muted" style="padding:14px">По выбранным фильтрам позиций нет.</td></tr>';
    $('count').textContent = 'Показано ' + rows.length + ' из ' + D.total + ' позиций';
    fit();
  }
  function fit() {
    try { if (D.fit && window.frameElement) window.frameElement.style.height = (document.body.offsetHeight + 12) + 'px'; } catch (e) {}
  }
  function byN(n) { return D.rows.filter(function (r) { return r.n === n; })[0]; }

  function showTip(td, pinned) {
    var tr = td.parentNode, r = byN(+tr.getAttribute('data-n')), t = r && r.tips[td.getAttribute('data-tip')];
    if (!t) return;
    var el = $('tip');
    el.innerHTML = '<h4>' + esc(t.title) + '</h4><ul>' + t.facts.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul>' +
      (t.impact ? '<div class="imp">Возможное влияние на бюджет: ' + esc(t.impact) + '</div>' : '') +
      (t.sources.length ? '<div class="src">' + t.sources.map(esc).join('<br>') + '</div>' : '') +
      (t.ai ? '<div class="ai">' + esc(t.ai) + '</div>' : '');
    el.style.display = 'block';
    var b = td.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
    var left = Math.max(6, Math.min(b.left, window.innerWidth - w - 6));
    var top = b.bottom + 4;
    if (top + h > window.innerHeight - 4) top = Math.max(4, b.top - h - 4);
    el.style.left = left + 'px'; el.style.top = top + 'px';
    S.pin = pinned ? td : null; S.shownAt = Date.now();
  }
  function hideTip() { $('tip').style.display = 'none'; S.pin = null; }

  function details(r) {
    var h = '<h3>' + esc(r.name) + '</h3><div class="muted">' + status(r).replace(/<span class="arr"[^>]*>.*?<\/span>/, '') + ' · ' + esc(r.unit || 'единица не указана') +
      ' · ВОР ' + esc(r.plan) + ' · акты ' + esc(r.fact) + ' · выполнено ' + esc(r.pct) + ' %</div>';
    h += '<h5>Расхождения</h5>';
    h += r.issues.length ? r.issues.map(function (i) {
      return '<div class="issue"><b>' + esc(i.type) + '</b> · важность: ' + esc(i.severity) + (i.impact ? ' · влияние: ' + esc(i.impact) : '') +
        '<div>' + esc(i.text) + '</div>' + (i.note ? '<div class="muted">' + esc(i.note) + '</div>' : '') + '</div>';
    }).join('') : '<div class="empty">Расхождений по правилам нет.' + (r.status === 'yellow' ? ' Статус жёлтый: факт по актам ниже плана.' : '') + '</div>';
    Object.keys(r.sources).forEach(function (role) {
      var list = r.sources[role];
      h += '<h5>' + esc(role) + '</h5>';
      h += list.length ? '<div class="grid">' + list.map(function (s) {
        return '<div class="row">«' + esc(s.name) + '» — ' + esc(s.qty) + (s.price ? ', ' + esc(s.price) : '') + '<div class="where">' + esc(s.where) + '</div></div>';
      }).join('') + '</div>' : '<div class="empty">Строк нет.</div>';
    });
    if (r.ai.length) {
      h += '<h5>Что сопоставил ИИ</h5>' + r.ai.map(function (a) {
        return '<div class="row">' + esc(a.doc) + ' → ВОР: «' + esc(a.vor) + '» · уверенность ' + esc(a.confidence) + (a.reason ? '<div class="where">причина: ' + esc(a.reason) + '</div>' : '') + '</div>';
      }).join('');
    }
    h += '<h5>Документы</h5><div>' + (r.files.length ? r.files.map(esc).join(', ') : 'нет') + '</div>';
    $('details').innerHTML = h;
  }
  function select(n, scroll) {
    S.sel = n; render();
    if (D.mode !== 'issues') { details(byN(n)); fit(); }
    if (scroll && D.mode !== 'issues') $('details').scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }

  function showHint(el) {
    var t = $('tip'); t.innerHTML = '<div>' + esc(D.hints[el.getAttribute('data-hint')]) + '</div>'; t.style.display = 'block';
    var b = el.getBoundingClientRect();
    t.style.left = Math.max(6, Math.min(b.left, window.innerWidth - t.offsetWidth - 6)) + 'px'; t.style.top = (b.bottom + 4) + 'px'; S.shownAt = Date.now();
  }
  $('head').addEventListener('mouseover', function (e) { var h = e.target.closest('.hint'); if (h) showHint(h); });
  $('head').addEventListener('mouseout', function (e) { if (e.target.closest('.hint') && !S.pin) hideTip(); });
  $('head').addEventListener('click', function (e) { var h = e.target.closest('.hint'); if (h) { e.stopPropagation(); showHint(h); } });
  var body = $('body');
  body.addEventListener('mouseover', function (e) { var td = e.target.closest('td[data-tip]'); if (td && !S.pin) showTip(td, false); });
  body.addEventListener('mouseout', function (e) { var td = e.target.closest('td[data-tip]'); if (td && !S.pin) hideTip(); });
  body.addEventListener('focusin', function (e) { var td = e.target.closest('td[data-tip]'); if (td && !S.pin) showTip(td, false); });
  body.addEventListener('click', function (e) {
    e.stopPropagation();
    var tr = e.target.closest('tr[data-n]'); if (!tr) return;
    var td = e.target.closest('td[data-tip]'), n = +tr.getAttribute('data-n');
    var same = td && S.pin === td;
    hideTip(); select(n, !td);
    if (td && !same) { var again = $('body').querySelector('tr[data-n="' + n + '"] td[data-tip="' + td.getAttribute('data-tip') + '"]'); if (again) showTip(again, true); }
  });
  body.addEventListener('keydown', function (e) { if (e.key === 'Enter') { var tr = e.target.closest('tr[data-n]'); if (tr) select(+tr.getAttribute('data-n'), true); } });
  document.addEventListener('click', function (e) { if (!e.target.closest('#body') && !e.target.closest('#tip')) hideTip(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideTip(); });
  $('wrap').addEventListener('scroll', function () { if (Date.now() - (S.shownAt || 0) > 500) hideTip(); });

  $('q').addEventListener('input', function (e) { S.q = e.target.value; render(); });
  $('dev').addEventListener('change', function (e) { S.dev = e.target.checked; render(); });
  $('iss').addEventListener('change', function (e) { S.iss = e.target.checked; render(); });
  $('unit').addEventListener('change', function (e) { S.unit = e.target.value; render(); });
  $('chips').addEventListener('click', function (e) {
    var b = e.target.closest('.chip'); if (!b) return;
    var s = b.getAttribute('data-s'); S.stat[s] = !S.stat[s]; b.setAttribute('aria-pressed', S.stat[s] ? 'true' : 'false'); render();
  });

  if (D.doc_issues.length) {
    $('docissues').innerHTML = '<div class="panel details"><h5 style="margin-top:0">Расхождения по документам (не привязаны к позиции)</h5>' + D.doc_issues.map(function (i) {
      return '<div class="issue y"><b>' + esc(i.type) + '</b> · важность: ' + esc(i.severity) + '<div>' + esc(i.text) + '</div><div class="where muted">' + i.sources.map(esc).join('<br>') + '</div></div>';
    }).join('') + '</div>';
  }
  render();
})();
</script></body></html>"""


def ledger_html(ledger: dict, mode: str = "ledger") -> str:
    """Готовая страница таблицы. mode: "ledger" (позиции) или "issues" (только расхождения, строки из build_issue_rows).
    Данные в JSON; «</» экранируется, чтобы текст из файлов не закрыл тег script."""
    columns = ISSUE_COLUMNS if mode == "issues" else LEDGER_COLUMNS
    hints = {c["k"]: c["hint"] for c in columns if c.get("hint")}
    payload = {**ledger, "palette": {k: v[0] for k, v in STATUS_COLORS.items()}, "columns": columns, "hints": hints, "mode": mode}
    payload["fit"] = not hasattr(__import__("streamlit"), "iframe")      # st.iframe сам подгоняет высоту, иначе подгоняет скрипт
    payload.setdefault("units", [])
    payload.setdefault("doc_issues", [])
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", data)


def render_ledger(ledger: dict, height: int = HEIGHT, mode: str = "ledger") -> None:
    """Таблица в iframe. Скрипт сам подгоняет высоту iframe под содержимое; height это запасное значение до его запуска."""
    import streamlit as st
    html = ledger_html(ledger, mode)
    if hasattr(st, "iframe"):                       # новый API: высота по содержимому (st.components.v1.html объявлен устаревшим)
        st.iframe(html, height="content")
        return
    import streamlit.components.v1 as components
    if mode == "issues":
        height = ISSUES_HEIGHT_BASE + ISSUES_HEIGHT_ROW * ledger["total"]
    components.html(html, height=height, scrolling=True)
