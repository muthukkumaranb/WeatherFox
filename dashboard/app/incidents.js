/* 02 Incidents: filters, queue, and the evidence panel for the selected incident. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;
  const ui = { state: 'open', vars: new Set(['T', 'RH', 'P']), causes: null, sev: new Set(['high', 'medium', 'low', '']), selected: null };

  const list = () => WF.state.incidents.filter((i) =>
    (ui.state === 'all' || i.state === ui.state) && ui.vars.has(i.variable) &&
    (!ui.causes || ui.causes.has(i.root_cause)) && ui.sev.has(i.severity || ''));

  function renderFilters() {
    const all = WF.state.incidents;
    const n = (f) => all.filter(f).length;
    const causes = [...new Set(all.map((i) => i.root_cause))].sort();
    if (!ui.causes) ui.causes = new Set(causes);
    causes.forEach((c) => { if (!ui._seen || !ui._seen.has(c)) ui.causes.add(c); });
    ui._seen = new Set(causes);
    const stateRow = (k, l, dot) => `<button data-state="${k}" class="w-full flex items-center justify-between px-2 py-1 rounded ${ui.state === k ? 'bg-surface-container-high text-on-surface border-l-2 border-primary' : 'text-on-surface-variant hover:bg-surface-container'}">
      <span class="flex items-center gap-1.5">${dot ? `<span class="w-2 h-2 rounded-full ${dot}"></span>` : ''}${l}</span><span class="chip">${k === 'all' ? all.length : n((i) => i.state === k)}</span></button>`;
    const check = (group, val, label, count) => `<label class="flex items-center justify-between gap-1 cursor-pointer"><span class="flex items-center gap-1.5"><input type="checkbox" data-group="${group}" value="${esc(val)}" class="accent-primary" ${ui[group].has(val) ? 'checked' : ''}>${esc(label)}</span><span class="text-outline">${count}</span></label>`;
    document.getElementById('inc-filters').innerHTML = `
      <div><div class="panel-title">Status</div>
        ${stateRow('open', 'Open', 'bg-error')}${stateRow('acknowledged', 'Acknowledged', 'bg-secondary')}${stateRow('resolved', 'Resolved', 'bg-primary')}${stateRow('dismissed', 'Real weather (dismissed)', 'bg-tertiary')}${stateRow('all', 'All')}</div>
      <div class="flex flex-col gap-1"><div class="panel-title">Variable</div>
        ${['T', 'RH', 'P'].map((v) => check('vars', v, WF.VARNAME[v], n((i) => i.variable === v))).join('')}</div>
      <div class="flex flex-col gap-1"><div class="panel-title">Cause (from the verdict)</div>
        ${causes.length ? causes.map((c) => check('causes', c, WF.cause(c), n((i) => i.root_cause === c))).join('') : '<span class="text-outline">none yet</span>'}</div>
      <div class="flex flex-col gap-1"><div class="panel-title">Severity</div>
        ${['high', 'medium', 'low'].map((s) => check('sev', s, s, n((i) => i.severity === s))).join('')}</div>`;
  }

  function renderQueue() {
    const items = list();
    document.getElementById('inc-queue-count').textContent = `(${items.length})`;
    if (ui.selected && !items.some((i) => i.incident_id === ui.selected)) ui.selected = null;
    if (!ui.selected && items[0]) ui.selected = items[0].incident_id;
    const q = document.getElementById('inc-queue');
    q.innerHTML = items.length ? items.map((i) => {
      const s = WF.stationById(i.station_id) || {};
      return `<div data-inc="${esc(i.incident_id)}" class="card cursor-pointer ${ui.selected === i.incident_id ? 'card-sel' : ''}">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0"><div class="font-headline-md text-body-lg font-bold truncate">${esc(s.name || i.station_id)} <span class="text-telemetry-micro text-outline font-label-mono-regular">${esc(i.station_id)}</span></div>
            <div class="text-telemetry-micro text-on-surface-variant">${esc(WF.VARNAME[i.variable] || i.variable)} · <span class="${i.label === 'anomaly' ? 'text-error' : 'text-secondary'}">${esc(WF.cause(i.root_cause))}</span></div></div>
          <div class="flex flex-col items-end gap-1"><span class="badge ${i.label === 'anomaly' ? 'b-anomaly' : 'b-uncertain'}">${esc(i.label)}</span>${i.state !== 'open' ? `<span class="badge b-state">${esc(i.state)}</span>` : ''}</div>
        </div>
        <div class="kv text-outline"><span>${WF.fmtTs(i.start_ts)} → ${WF.fmtTs(i.end_ts, false)}</span><span>${i.n_readings} reading${i.n_readings === 1 ? '' : 's'}</span></div>
      </div>`;
    }).join('') : '<div class="text-center py-10 text-telemetry-micro text-outline">No incidents match these filters.</div>';
  }

  let detailToken = 0;
  async function renderDetail() {
    const el = document.getElementById('inc-detail');
    const inc = WF.state.incidents.find((i) => i.incident_id === ui.selected);
    if (!inc) {
      el.innerHTML = '<div class="panel p-space-lg text-center text-telemetry-micro text-outline">Select an incident to see its evidence.</div>';
      return;
    }
    const s = WF.stationById(inc.station_id) || {};
    const key = `${inc.incident_id}|${inc.state}|${inc.n_readings}`;
    if (el.dataset.key === key) return; // unchanged; avoid re-drawing the chart every poll
    el.dataset.key = key;
    const token = ++detailToken;
    el.innerHTML = `
      <div class="panel p-space-md">
        <div class="flex items-start justify-between gap-2">
          <div><div class="font-display-lg text-[28px] leading-8 font-bold">${esc(s.name || inc.station_id)} <span class="text-outline text-body-lg">${esc(inc.station_id)}</span></div>
            <div class="flex items-center gap-2 mt-1"><span class="badge ${inc.label === 'anomaly' ? 'b-anomaly' : 'b-uncertain'}">${esc(inc.label)} · ${esc(WF.cause(inc.root_cause))}</span><span class="badge b-state">${esc(inc.state)}</span></div></div>
          <div class="text-right text-telemetry-micro text-outline">${s.lat != null ? `${Number(s.lat).toFixed(3)}°N, ${Number(s.lon).toFixed(3)}°E` : ''}<br>${s.elevation != null ? `elev. ${Number(s.elevation).toFixed(0)} m` : ''}</div>
        </div>
      </div>
      <div class="panel p-space-sm"><div class="panel-title">${esc(WF.VARNAME[inc.variable] || inc.variable)}: observed vs model estimate (48 h)</div><div class="h-56"><canvas id="inc-chart"></canvas></div></div>
      <div class="panel p-space-sm flex flex-col gap-space-sm" id="inc-triage"><div class="text-telemetry-micro text-outline">Loading…</div></div>
      <div class="panel p-space-sm grid grid-cols-2 md:grid-cols-4 gap-space-xs">
        <button class="act-btn act-primary justify-center" data-act="acknowledged" ${inc.state !== 'open' ? 'disabled' : ''}><span class="material-symbols-outlined text-sm">done</span>Acknowledge (A)</button>
        <button class="act-btn justify-center" data-act="resolved" ${inc.state === 'resolved' ? 'disabled' : ''}><span class="material-symbols-outlined text-sm">task_alt</span>Resolve</button>
        <button class="act-btn act-tertiary justify-center" data-act="dismissed" ${inc.state === 'dismissed' ? 'disabled' : ''}><span class="material-symbols-outlined text-sm">cloud</span>Real weather</button>
        <button class="act-btn justify-center" data-act="wo"><span class="material-symbols-outlined text-sm">build</span>Work order</button>
      </div>`;
    let series = [];
    try { series = (await WF.api(`/stations/${encodeURIComponent(inc.station_id)}/series?hours=48`)).series || []; } catch (e) { /* empty */ }
    if (token !== detailToken) return;
    WF.drawSeries(document.getElementById('inc-chart'), series, inc.variable, { highlightFrom: inc.start_ts, highlightTo: inc.end_ts });
    document.getElementById('inc-triage').innerHTML = WF.triageHtml(inc, series);
  }

  async function act(kind) {
    const inc = WF.state.incidents.find((i) => i.incident_id === ui.selected);
    if (!inc) return;
    if (kind === 'wo') {
      WF.openWorkOrderModal({ station_id: inc.station_id, variable: inc.variable, priority: inc.severity === 'high' ? 'high' : 'medium', incident_id: inc.incident_id,
        description: `${WF.VARNAME[inc.variable]}: ${WF.cause(inc.root_cause)} (${inc.n_readings} flagged readings, ${WF.fmtTs(inc.start_ts)} – ${WF.fmtTs(inc.end_ts)}). ${inc.action || ''}` });
      return;
    }
    try {
      await WF.setIncidentState(inc, kind, kind === 'dismissed' ? 'genuine_weather' : null);
      WF.beep('ok');
      WF.toast({ acknowledged: 'Acknowledged', resolved: 'Resolved', dismissed: 'Marked as real weather' }[kind], `${WF.stationName(inc.station_id)} · ${WF.cause(inc.root_cause)}`, kind === 'dismissed' ? 'tertiary' : 'primary');
    } catch (e) { WF.toast('Action failed', e.message, 'error'); }
  }

  function render() {
    if (WF.state.view !== 'incidents') return;
    renderFilters(); renderQueue(); renderDetail();
  }

  WF.on('data', render);
  WF.on('view', ({ view, arg }) => { if (view === 'incidents') { if (arg) ui.selected = arg; render(); } });

  WF.incidentsInit = function () {
    document.getElementById('inc-filters').addEventListener('click', (e) => {
      const b = e.target.closest('[data-state]'); if (!b) return;
      ui.state = b.dataset.state; ui.selected = null; render();
    });
    document.getElementById('inc-filters').addEventListener('change', (e) => {
      const g = e.target.dataset.group; if (!g) return;
      if (e.target.checked) ui[g].add(e.target.value); else ui[g].delete(e.target.value);
      ui.selected = null; render();
    });
    document.getElementById('inc-queue').addEventListener('click', (e) => {
      const c = e.target.closest('[data-inc]'); if (!c) return;
      ui.selected = c.dataset.inc; renderQueue(); renderDetail();
    });
    document.getElementById('inc-detail').addEventListener('click', (e) => {
      const b = e.target.closest('[data-act]'); if (b && !b.disabled) act(b.dataset.act);
    });
    document.getElementById('inc-export').onclick = () => {
      const inc = WF.state.incidents.find((i) => i.incident_id === ui.selected);
      window.location.href = inc ? `/export?station_id=${encodeURIComponent(inc.station_id)}` : '/export';
    };
    document.addEventListener('keydown', (e) => {
      if (WF.state.view !== 'incidents' || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
      const items = list();
      const idx = items.findIndex((i) => i.incident_id === ui.selected);
      if (e.key === 'j' || e.key === 'J') { ui.selected = (items[idx + 1] || items[idx] || {}).incident_id; renderQueue(); renderDetail(); }
      if (e.key === 'k' || e.key === 'K') { ui.selected = (items[Math.max(0, idx - 1)] || {}).incident_id; renderQueue(); renderDetail(); }
      if (e.key === 'a' || e.key === 'A') act('acknowledged');
    });
  };
})();
