/* 01 Overview: map, KPI tiles, needs-attention stack, station drawer, 24 h flag timeline. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;
  const ui = { filter: 'all', region: 'all', attention: false, variable: 'T', drawerStation: null };

  const SPATIAL = {
    neighbours_normal: (n) => `${n ?? 'The'} nearby station${n === 1 ? '' : 's'} read normally, so the deviation is local to this sensor.`,
    neighbours_also_deviating: (n) => `${n ?? 'Nearby'} nearby station${n === 1 ? '' : 's'} deviate the same way, which is what real weather looks like.`,
    no_neighbours: () => 'No nearby station was available to compare with; the verdict rests on this station\'s own history.',
  };
  WF.spatialText = (support, n) => (SPATIAL[support] ? SPATIAL[support](n) : 'Neighbour comparison not reported for this verdict.');

  /* The four triage questions, answered only from the verdict and the series. */
  WF.triageHtml = function (inc, series) {
    const v = inc.variable;
    const row = (series || []).find((r) => r.ts_utc === inc.peak_ts) || (series || []).filter((r) => r.ts_utc >= inc.start_ts && r.ts_utc <= inc.end_ts).pop();
    const observed = row ? row[v] : null;
    const corr = inc.corrected || {};
    const reasons = inc.reasons || [];
    const maxC = Math.max(0.0001, ...reasons.map((r) => Math.abs(r.contribution || 0)));
    const conf = inc.peak_confidence;
    return `
      <div class="grid grid-cols-2 gap-space-sm">
        <div class="sub-panel"><div class="sub-title">Observed at peak</div>
          <div class="font-headline-md text-headline-md font-bold ${inc.label === 'anomaly' ? 'text-error' : 'text-secondary'}">${WF.fmt(observed, v)}</div>
          <div class="text-telemetry-micro text-outline">${WF.fmtTs(inc.peak_ts || inc.end_ts)}</div></div>
        <div class="sub-panel"><div class="sub-title">Model estimate</div>
          <div class="font-headline-md text-headline-md font-bold text-primary">${corr.value != null ? WF.fmt(corr.value, v) : '—'}</div>
          <div class="text-telemetry-micro text-outline">${corr.value != null ? `± ${Number(corr.sigma ?? 0).toFixed(1)} ${WF.UNIT[v]} · ${esc(corr.method || '')}` : 'no corrected value in this verdict'}</div></div>
      </div>
      <div class="sub-panel"><div class="sub-title">1 · What happened?</div>
        <div class="text-body-md">${esc(WF.VARNAME[v] || v)}: <strong>${esc(WF.cause(inc.root_cause))}</strong>, ${inc.n_readings} flagged reading${inc.n_readings === 1 ? '' : 's'} from ${WF.fmtTs(inc.start_ts, false)} to ${WF.fmtTs(inc.end_ts, false)}.</div></div>
      <div class="sub-panel"><div class="sub-title">2 · Why was it flagged?</div>
        ${reasons.length ? reasons.map((r) => `
          <div class="mb-1.5"><div class="kv"><span class="text-on-surface">${esc(r.text || r.feature)}</span><span class="text-outline">${r.contribution != null ? Number(r.contribution).toFixed(2) : ''}</span></div>
          <div class="bar-bg mt-0.5"><div class="h-full ${inc.label === 'anomaly' ? 'bg-error' : 'bg-secondary'}" style="width:${(100 * Math.abs(r.contribution || 0)) / maxC}%"></div></div></div>`).join('') : '<div class="text-telemetry-micro text-outline">The verdict carries no reasons.</div>'}
        <div class="text-telemetry-micro text-on-surface-variant mt-1">${esc(WF.spatialText(inc.spatial_support, inc.n_neighbours))}</div></div>
      <div class="sub-panel"><div class="sub-title">3 · How sure is it?</div>
        <div class="flex items-center gap-2"><div class="bar-bg flex-1"><div class="h-full bg-primary" style="width:${conf != null ? 100 * conf : 0}%"></div></div>
        <span class="font-label-mono-bold text-body-md">${WF.pct(conf)}</span></div>
        <div class="text-telemetry-micro text-outline mt-1">Label <strong class="text-on-surface">${esc(inc.label)}</strong>${inc.severity ? ` · severity ${esc(inc.severity)}` : ''} · scorer ${esc(inc.model_version || '')}</div></div>
      <div class="sub-panel"><div class="sub-title">4 · What should be done?</div>
        <div class="text-body-md">${esc(inc.action || 'No action suggested in the verdict.')}</div></div>`;
  };

  function counts(stations) {
    const c = { all: stations.length, anomaly: 0, uncertain: 0, genuine: 0, normal: 0, unscored: 0, offline: 0 };
    stations.forEach((s) => { c[WF.stationStatus(s)] += 1; });
    return c;
  }

  function visible(s) {
    const st = WF.stationStatus(s);
    if (ui.filter !== 'all' && st !== ui.filter) return false;
    if (ui.attention && !['anomaly', 'uncertain'].includes(st)) return false;
    if (ui.region !== 'all' && WF.region(s.lat, s.lon) !== ui.region) return false;
    return true;
  }

  function renderFilters(c) {
    const defs = [['all', 'All'], ['anomaly', 'Anomaly'], ['uncertain', 'Uncertain'], ['genuine', 'Real weather'], ['normal', 'Normal'], ['offline', 'No recent data']];
    document.getElementById('map-status-filters').innerHTML = '<span class="font-label-mono-bold text-telemetry-micro text-outline mr-1 uppercase">Filter:</span>' +
      defs.map(([k, l]) => `<button data-filter="${k}" class="filter-btn ${ui.filter === k ? 'filter-on' : ''}">${k !== 'all' ? `<span class="w-1.5 h-1.5 rounded-full" style="background:${WF.STATUS_META[k].color}"></span>` : ''}${l} (${c[k]})</button>`).join('');
    document.getElementById('map-legend').innerHTML = ['anomaly', 'uncertain', 'genuine', 'normal', 'unscored', 'offline']
      .map((k) => `<div class="flex items-center gap-2"><span class="w-2 h-2 rounded-full" style="background:${WF.STATUS_META[k].color}"></span><span>${WF.STATUS_META[k].label} (${c[k]})</span></div>`).join('') +
      '<div class="flex items-center gap-2 text-outline"><span class="w-2 h-2 rounded-full border border-dashed border-tertiary"></span><span>inside a simulated weather event</span></div>';
  }

  function renderKpis(c) {
    const open = WF.openIncidents();
    const high = open.filter((i) => i.severity === 'high').length;
    const nAnom = open.filter((i) => i.label === 'anomaly').length;
    const reporting = c.all - c.offline;
    const s = WF.state.scorer || {};
    document.getElementById('kpi-tiles').innerHTML = `
      <div class="kpi"><div class="kv text-outline"><span>STATIONS REPORTING</span><span class="material-symbols-outlined text-xs text-primary">cell_tower</span></div>
        <div class="my-1"><span class="font-headline-lg text-headline-lg font-bold">${reporting}</span><span class="text-body-md text-outline"> / ${c.all}</span></div>
        <div class="text-telemetry-micro text-outline">${c.offline} with no recent data</div></div>
      <div class="kpi"><div class="kv text-outline"><span>OPEN INCIDENTS</span><span class="material-symbols-outlined text-xs text-error">warning</span></div>
        <div class="my-1"><span class="font-headline-lg text-headline-lg font-bold ${open.length ? 'text-error' : 'text-primary'}">${open.length}</span></div>
        <div class="text-telemetry-micro text-outline">${nAnom} anomaly · ${open.length - nAnom} uncertain · ${high} high severity</div></div>
      <div class="kpi"><div class="kv text-outline"><span>REAL WEATHER (PROTECTED)</span><span class="material-symbols-outlined text-xs text-tertiary">verified_user</span></div>
        <div class="my-1"><span class="font-headline-lg text-headline-lg font-bold text-tertiary">${c.genuine}</span><span class="text-body-md text-outline"> stations</span></div>
        <div class="text-telemetry-micro text-outline">scorer judged the deviation to be real weather</div></div>
      <div class="kpi"><div class="kv text-outline"><span>SCORER</span><span class="material-symbols-outlined text-xs text-primary">memory</span></div>
        <div class="my-1 font-label-mono-bold text-body-md truncate">${esc(s.backend === 'fake' ? 'Stand-in (demo)' : s.backend || '—')}</div>
        <div class="text-telemetry-micro text-outline truncate">version ${esc(s.model_version || '—')}</div></div>`;
  }

  function renderStack() {
    const open = WF.openIncidents();
    document.getElementById('alert-stack-count').textContent = `${open.length} OPEN`;
    const el = document.getElementById('incident-card-stack');
    if (!open.length) {
      el.innerHTML = `<div class="text-center py-10 text-telemetry-micro text-outline"><span class="material-symbols-outlined text-primary">check_circle</span><div class="mt-1">No open incidents. Try the Simulation lab to inject a fault.</div></div>`;
      return;
    }
    el.innerHTML = open.slice(0, 30).map((i) => {
      const s = WF.stationById(i.station_id) || {};
      const corr = i.corrected || {};
      const lead = (i.reasons && i.reasons[0] && i.reasons[0].text) || '';
      return `
      <div class="card ${i.label === 'anomaly' ? 'border-error/30' : ''}">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0"><div class="flex items-center gap-1.5">${i.label === 'anomaly' ? '<span class="w-2 h-2 rounded-full bg-error animate-ping"></span>' : ''}
            <span class="font-label-mono-bold text-body-md truncate">${esc(s.name || i.station_id)}</span><span class="text-telemetry-micro text-outline">${esc(i.station_id)}</span></div>
            <div class="text-telemetry-micro text-outline">${esc(WF.VARNAME[i.variable] || i.variable)} · ${WF.age(i.end_ts)}</div></div>
          <span class="badge ${i.label === 'anomaly' ? 'b-anomaly' : 'b-uncertain'}">${esc(i.severity || '')} ${esc(i.label)}</span>
        </div>
        <div class="sub-panel !p-space-xs">
          <div class="kv"><span class="text-outline">CAUSE</span><span class="font-label-mono-bold ${i.label === 'anomaly' ? 'text-error' : 'text-secondary'}">${esc(WF.cause(i.root_cause))}</span></div>
          <div class="kv text-on-surface-variant"><span>Model estimate</span><span>${corr.value != null ? `${WF.fmt(corr.value, i.variable)} ± ${Number(corr.sigma ?? 0).toFixed(1)}` : '—'}</span></div>
          <div class="kv text-on-surface-variant"><span>Confidence</span><span>${WF.pct(i.peak_confidence)}</span></div>
        </div>
        ${lead ? `<div class="text-telemetry-micro text-on-surface-variant">${esc(lead)}</div>` : ''}
        <button data-open-station="${esc(i.station_id)}" class="act-btn w-full justify-center text-primary">Evidence &amp; triage <span class="material-symbols-outlined text-xs">arrow_forward</span></button>
      </div>`;
    }).join('');
  }

  /* ---------- drawer ---------- */
  async function openDrawer(sid) {
    const s = WF.stationById(sid);
    if (!s) return;
    ui.drawerStation = sid;
    const st = WF.stationStatus(s);
    document.getElementById('drawer-title').textContent = `${s.name} (${s.id})`;
    document.getElementById('drawer-icon').className = `material-symbols-outlined text-base ${WF.STATUS_META[st].text}`;
    const body = document.getElementById('drawer-body');
    const incs = WF.state.incidents.filter((i) => i.station_id === sid && i.state === 'open');
    const health = WF.healthFor(sid);
    body.innerHTML = `
      <div class="flex items-center justify-between">${WF.statusBadge(st)}<span class="text-telemetry-micro text-outline">${WF.fmtTs(s.latest_ts)}</span></div>
      <div class="grid grid-cols-3 gap-space-xs">${['T', 'RH', 'P'].map((v) => `<div class="sub-panel !p-space-xs"><div class="sub-title">${v}</div><div class="font-label-mono-bold">${WF.fmt(s.latest && s.latest[v], v)}</div></div>`).join('')}</div>
      <div class="h-40"><canvas id="drawer-chart"></canvas></div>
      <div id="drawer-incidents" class="flex flex-col gap-space-sm">${incs.length ? '<div class="text-telemetry-micro text-outline">Loading evidence…</div>' : `<div class="sub-panel text-telemetry-micro text-on-surface-variant">No open incident at this station. ${st === 'genuine' ? 'The scorer judged the latest deviation to be real weather, so no alert was raised.' : ''}</div>`}</div>
      <div class="sub-panel"><div class="sub-title">Flag-rate health score</div>
        ${health.some((h) => h.score != null) ? health.map((h) => `<div class="kv mb-1"><span>${h.variable}</span><span class="flex-1 mx-2 bar-bg"><span class="block h-full ${h.score < 0.5 ? 'bg-error' : h.score < 0.8 ? 'bg-secondary' : 'bg-primary'}" style="width:${100 * (h.score || 0)}%"></span></span><span>${h.score != null ? WF.pct(h.score) : '—'}</span></div>`).join('')
          : '<div class="text-telemetry-micro text-outline">This scorer does not report a health score.</div>'}
      </div>`;
    document.getElementById('station-drawer').classList.remove('translate-x-[110%]');
    let series = [];
    try { series = (await WF.api(`/stations/${encodeURIComponent(sid)}/series?hours=48`)).series || []; } catch (e) { /* shown empty */ }
    if (ui.drawerStation !== sid) return;
    const variable = incs[0] ? incs[0].variable : ui.variable;
    WF.drawSeries(document.getElementById('drawer-chart'), series, variable, { highlightFrom: incs[0] && incs[0].start_ts, highlightTo: incs[0] && incs[0].end_ts, legend: false });
    if (incs.length) document.getElementById('drawer-incidents').innerHTML = incs.map((i) => WF.triageHtml(i, series)).join('<hr class="border-surface-container-highest">');
    ['drawer-ack', 'drawer-dismiss'].forEach((id) => { document.getElementById(id).disabled = !incs.length; });
  }
  function closeDrawer() {
    ui.drawerStation = null;
    document.getElementById('station-drawer').classList.add('translate-x-[110%]');
  }
  WF.openStationDrawer = (sid) => { WF.go('overview'); openDrawer(sid); };

  async function drawerAction(state, reason) {
    const sid = ui.drawerStation;
    const incs = WF.state.incidents.filter((i) => i.station_id === sid && i.state === 'open');
    if (!incs.length) return;
    try {
      for (const i of incs) await WF.setIncidentState(i, state, reason);
      WF.beep('ok');
      WF.toast(state === 'dismissed' ? 'Marked as real weather' : 'Acknowledged', `${WF.stationName(sid)} · ${incs.length} incident${incs.length > 1 ? 's' : ''}`, state === 'dismissed' ? 'tertiary' : 'primary');
      closeDrawer();
    } catch (e) { WF.toast('Action failed', e.message, 'error'); }
  }

  /* ---------- 24 h timeline of flagged readings (data time) ---------- */
  async function renderTimeline() {
    if (WF.state.view !== 'overview' || !WF.state.dataTime) return;
    let alerts = [];
    try { alerts = await WF.api('/alerts'); } catch (e) { return; }
    const end = WF.ts(WF.state.dataTime).getTime();
    const start = end - 24 * 3600e3;
    const bins = Array.from({ length: 24 }, () => ({ a: 0, u: 0 }));
    alerts.forEach((a) => {
      const t = WF.ts(a.ts_utc).getTime();
      if (t < start || t > end) return;
      const i = Math.min(23, Math.floor((t - start) / 3600e3));
      if (a.label === 'anomaly') bins[i].a += 1; else bins[i].u += 1;
    });
    const max = Math.max(1, ...bins.map((b) => b.a + b.u));
    document.getElementById('timeline-bars').innerHTML = bins.map((b, i) => {
      const h0 = new Date(start + i * 3600e3).toISOString().slice(11, 16);
      return `<div class="flex-1 flex flex-col justify-end h-full bg-surface-container-lowest rounded-sm" title="${h0} UTC · ${b.a} anomaly, ${b.u} uncertain">
        <div class="bg-secondary" style="height:${(100 * b.u) / max}%"></div><div class="bg-error" style="height:${(100 * b.a) / max}%"></div></div>`;
    }).join('');
    document.getElementById('timeline-axis').innerHTML = [0, 6, 12, 18, 24].map((h) => `<span>${new Date(start + h * 3600e3).toISOString().slice(11, 16)}</span>`).join('');
  }

  function render() {
    const stations = WF.state.stations;
    const c = counts(stations);
    renderFilters(c);
    renderKpis(c);
    renderStack();
    WF.map.render(stations.filter(visible));
  }

  let timelineDrawn = false;
  WF.on('data', () => { render(); if (!timelineDrawn && WF.state.dataTime) { timelineDrawn = true; renderTimeline(); } });
  WF.on('escape', closeDrawer);
  WF.on('view', ({ view }) => { if (view === 'overview') renderTimeline(); else closeDrawer(); });

  WF.overviewInit = async function () {
    await WF.map.init((sid) => openDrawer(sid));
    document.getElementById('map-status-filters').addEventListener('click', (e) => {
      const b = e.target.closest('[data-filter]'); if (!b) return;
      ui.filter = b.dataset.filter; render();
    });
    document.getElementById('var-toggle-group').addEventListener('click', (e) => {
      const b = e.target.closest('[data-var]'); if (!b) return;
      ui.variable = WF.map.variable = b.dataset.var;
      document.querySelectorAll('#var-toggle-group [data-var]').forEach((x) => x.classList.toggle('seg-on', x === b));
    });
    document.getElementById('attention-only-checkbox').addEventListener('change', (e) => { ui.attention = e.target.checked; render(); });
    document.getElementById('region-filter-group').addEventListener('click', (e) => {
      const p = e.target.closest('[data-region]'); if (!p) return;
      ui.region = p.dataset.region;
      document.querySelectorAll('#region-filter-group [data-region]').forEach((x) => x.classList.toggle('region-on', x === p));
      render();
    });
    document.getElementById('incident-card-stack').addEventListener('click', (e) => {
      const b = e.target.closest('[data-open-station]'); if (b) openDrawer(b.dataset.openStation);
    });
    document.getElementById('drawer-close').onclick = closeDrawer;
    document.getElementById('drawer-ack').onclick = () => drawerAction('acknowledged');
    document.getElementById('drawer-dismiss').onclick = () => drawerAction('dismissed', 'genuine_weather');
    document.getElementById('drawer-wo').onclick = () => {
      const sid = ui.drawerStation;
      const inc = WF.state.incidents.find((i) => i.station_id === sid && i.state === 'open');
      WF.openWorkOrderModal({
        station_id: sid, variable: inc ? inc.variable : 'T', priority: inc && inc.severity === 'high' ? 'high' : 'medium', incident_id: inc ? inc.incident_id : null,
        description: inc ? `${WF.VARNAME[inc.variable]}: ${WF.cause(inc.root_cause)} (${inc.n_readings} flagged readings, ${WF.fmtTs(inc.start_ts)} – ${WF.fmtTs(inc.end_ts)}). ${inc.action || ''}` : '',
      });
    };
    setInterval(renderTimeline, 10000);
  };
})();
