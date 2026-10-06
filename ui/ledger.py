"""«Сверочная ведомость»: собственная HTML/CSS/JS-таблица в st.components.v1.html (без внешних скриптов).

Данные из ui/ledger_data.build_ledger передаются JSON в теге script. Таблица только читает: фильтры, подсказки по наведению и по нажатию
(на телефоне наведения нет), панель сведений о строке под таблицей. Шрифт IBM Plex Sans подключается с Google Fonts, без сети будет sans-serif."""
import json

from ui.data import STATUS_COLORS

COLUMN_TITLES = ["№", "Наименование (по ВОР)", "Ед.", "ВОР, кол-во", "Акты, кол-во", "Выполнено, %", "Цена по смете", "Цена по акту", "Δ цены, %", "Статус"]
HEIGHT = 900

TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root { --ink:#1B2733; --muted:#5B6877; --line:#D8DEE6; --bg:#F4F6F8; --accent:#1F4E79; --accent-soft:#E7EEF5; --red:#C62828; --yellow:#F9A825; --green:#2E7D32; }
* { box-sizing: border-box; }
html, body { margin:0; background:var(--bg); color:var(--ink); font:13px/1.4 'IBM Plex Sans','Segoe UI',Arial,sans-serif; font-variant-numeric: tabular-nums; }
body { padding: 2px 1px 12px 1px; }
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
th { position:sticky; top:0; z-index:2; background:#EEF2F6; font-weight:600; text-align:left; padding:0 8px; height:36px; border-bottom:1px solid var(--line); white-space:nowrap; font-size:13px; }
td { height:34px; padding:0 8px; border-bottom:1px solid #E8ECF1; white-space:nowrap; background:#fff; }
th.num, td.num { text-align:right; }
td.name { white-space:normal; min-width:200px; max-width:300px; line-height:1.25; }
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
@media (max-width: 640px) { .toolbar input[type=search] { width:100%; } .count { margin-left:0; width:100%; } }
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
  var P = D.palette, T = D.titles;
  var KEYS = ['n','name','unit','plan','fact','pct','est','actp','dp','status'];
  var NUM = {plan:1,fact:1,pct:1,est:1,actp:1,dp:1};
  var CHIPS = [['red','Красные'],['yellow','Жёлтые'],['green','Зелёные']];
  var S = {q:'', stat:{}, dev:false, iss:false, unit:'', sel:null, pin:null};
  var $ = function (id) { return document.getElementById(id); };
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }

  $('head').innerHTML = KEYS.map(function (k, i) { return '<th class="' + (NUM[k] ? 'num' : '') + '">' + esc(T[i]) + '</th>'; }).join('');
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
    var cls = (NUM[k] ? 'num ' : '') + (k === 'name' ? 'name ' : '') + (hl ? 'hl-' + hl : '');
    var attr = tip ? ' data-tip="' + k + '" tabindex="0"' : '';
    var body = k === 'status' ? status(r) : esc(r[k]);
    return '<td class="' + cls + '"' + attr + '>' + body + '</td>';
  }
  function render() {
    var rows = visible();
    $('body').innerHTML = rows.length ? rows.map(function (r) {
      return '<tr data-n="' + r.n + '" tabindex="0" class="' + (S.sel === r.n ? 'sel' : '') + '">' + KEYS.map(function (k) { return cell(r, k); }).join('') + '</tr>';
    }).join('') : '<tr><td colspan="10" class="muted" style="padding:14px">По выбранным фильтрам позиций нет.</td></tr>';
    $('count').textContent = 'Показано ' + rows.length + ' из ' + D.total + ' позиций';
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
    S.sel = n; render(); details(byN(n));
    if (scroll) $('details').scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }

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


def ledger_html(ledger: dict) -> str:
    """Готовая страница таблицы. Данные в JSON; «</» экранируется, чтобы текст из файлов не закрыл тег script."""
    payload = {**ledger, "palette": {k: v[0] for k, v in STATUS_COLORS.items()}, "titles": COLUMN_TITLES}
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", data)


def render_ledger(ledger: dict, height: int = HEIGHT) -> None:
    import streamlit.components.v1 as components
    components.html(ledger_html(ledger), height=height, scrolling=True)
