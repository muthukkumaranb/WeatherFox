/* 07 Data QC: live verdict feed from the websocket. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;
  const MAX_ROWS = 400;
  const ui = { paused: false, flaggedOnly: false, rows: [], stats: { total: 0, anomaly: 0, uncertain: 0, normal: 0, genuine: 0, injected: 0, stations: new Set(), first: null, last: null } };

  function detail(v) {
    const parts = [];
    Object.entries(v.vars || {}).forEach(([k, r]) => {
      if (r && (r.label === 'anomaly' || r.label === 'uncertain')) parts.push(`${k}: ${WF.cause(r.root_cause)}${r.reasons && r.reasons[0] ? ' — ' + r.reasons[0].text : ''}`);
    });
    if (v.genuine_event) parts.push('real weather (neighbours agree)');
    return parts.join(' · ');
  }

  function rowHtml(v) {
    const lab = v.genuine_event ? 'genuine' : v.label;
    const m = WF.STATUS_META[lab] || WF.STATUS_META.unscored;
    const rd = v.reading || {};
    return `<div class="grid grid-cols-12 gap-2 px-space-sm py-0.5 border-b border-surface-container-highest/50 ${lab === 'anomaly' ? 'bg-error-container/10' : ''}">
      <span class="col-span-2 text-outline">${esc((v.ts_utc || '').replace('T', ' ').replace('Z', ''))}</span>
      <span class="col-span-2 truncate">${esc(WF.stationName(v.station_id))} <span class="text-outline">${esc(v.station_id)}</span></span>
      <span class="col-span-1 ${m.text} font-label-mono-bold">${esc(lab)}</span>
      <span class="col-span-1">${WF.fmt(rd.T)}</span><span class="col-span-1">${WF.fmt(rd.RH)}</span><span class="col-span-1">${WF.fmt(rd.P)}</span>
      <span class="col-span-4 truncate text-on-surface-variant" title="${esc(detail(v))}">${rd.injected ? '<span class="text-secondary">[injected] </span>' : ''}${esc(detail(v))}</span></div>`;
  }

  function renderStats() {
    const s = ui.stats;
    const line = (k, v, cls = '') => `<div class="kv"><span class="text-outline">${k}</span><span class="font-label-mono-bold ${cls}">${v}</span></div>`;
    document.getElementById('qc-stats').innerHTML =
      line('Verdicts received', s.total.toLocaleString()) + line('Stations seen', s.stations.size) +
      line('Anomaly', `${s.anomaly} (${s.total ? ((100 * s.anomaly) / s.total).toFixed(2) : '0.00'} %)`, 'text-error') +
      line('Uncertain', `${s.uncertain} (${s.total ? ((100 * s.uncertain) / s.total).toFixed(2) : '0.00'} %)`, 'text-secondary') +
      line('Real weather', s.genuine, 'text-tertiary') + line('Normal', s.normal, 'text-primary') +
      line('Injected readings', s.injected, 'text-secondary') +
      line('Reading times', s.first ? `${WF.fmtTs(s.first, false)} → ${WF.fmtTs(s.last, false)}` : '—') +
      '<div class="text-telemetry-micro text-outline mt-2">Counts cover only what this browser tab has received. The CSV download is the server\'s full export with every verdict label.</div>';
  }

  let pendingRender = false;
  function flush() {
    pendingRender = false;
    const feed = document.getElementById('qc-feed');
    const shown = ui.flaggedOnly ? ui.rows.filter((v) => v.label !== 'normal' || v.genuine_event) : ui.rows;
    feed.innerHTML = shown.length ? shown.map(rowHtml).join('') : '<div class="p-space-md text-outline">Waiting for verdicts from the replay…</div>';
    renderStats();
  }

  WF.on('verdict', (v) => {
    const s = ui.stats;
    s.total += 1;
    s.stations.add(v.station_id);
    if (v.genuine_event) s.genuine += 1; else if (s[v.label] !== undefined) s[v.label] += 1;
    if (v.reading && v.reading.injected) s.injected += 1;
    if (!s.first || v.ts_utc < s.first) s.first = v.ts_utc;
    if (!s.last || v.ts_utc > s.last) s.last = v.ts_utc;
    if (ui.paused) return;
    ui.rows.unshift(v);
    if (ui.rows.length > MAX_ROWS) ui.rows.length = MAX_ROWS;
    if (WF.state.view === 'data-qc' && !pendingRender) { pendingRender = true; requestAnimationFrame(flush); }
  });
  WF.on('view', ({ view }) => { if (view === 'data-qc') flush(); });

  WF.dataqcInit = function () {
    document.getElementById('qc-pause').onclick = (e) => {
      ui.paused = !ui.paused;
      const b = e.currentTarget;
      b.querySelector('.material-symbols-outlined').textContent = ui.paused ? 'play_arrow' : 'pause';
      b.querySelector('span:last-child').textContent = ui.paused ? 'Resume' : 'Pause';
    };
    document.getElementById('qc-flagged-only').onchange = (e) => { ui.flaggedOnly = e.target.checked; flush(); };
  };
})();
