/* 03 Stations: directory, per-station charts, neighbour comparison, health. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;
  const ui = { q: '', status: 'all', sort: 'severity', selected: null };

  function items() {
    const q = ui.q.toLowerCase();
    const hmin = (sid) => { const h = WF.healthFor(sid).map((x) => x.score).filter((x) => x != null); return h.length ? Math.min(...h) : 2; };
    return WF.state.stations
      .filter((s) => (!q || `${s.name} ${s.id}`.toLowerCase().includes(q)) && (ui.status === 'all' || WF.stationStatus(s) === ui.status))
      .sort((a, b) => {
        if (ui.sort === 'name') return String(a.name).localeCompare(String(b.name));
        if (ui.sort === 'health') return hmin(a.id) - hmin(b.id);
        return WF.STATUS_META[WF.stationStatus(a)].rank - WF.STATUS_META[WF.stationStatus(b)].rank || String(a.name).localeCompare(String(b.name));
      });
  }

  function renderList() {
    const list = items();
    document.getElementById('st-count-chip').textContent = `${WF.state.stations.length} stations`;
    if (!ui.selected && list[0]) ui.selected = list[0].id;
    document.getElementById('st-list').innerHTML = list.length ? list.map((s) => {
      const st = WF.stationStatus(s);
      const flagged = (s.flagged_vars || []).map((f) => `${f.variable}: ${WF.cause(f.root_cause)}`).join(' · ');
      return `<button data-sid="${esc(s.id)}" class="text-left px-space-sm py-space-sm border-b border-surface-container-highest hover:bg-surface-container ${ui.selected === s.id ? 'bg-surface-container-high border-l-2 border-l-primary' : ''}">
        <div class="flex items-center justify-between gap-2"><span class="font-label-mono-bold text-body-md truncate">${esc(s.name)} <span class="text-telemetry-micro text-outline font-label-mono-regular">${esc(s.id)}</span></span>${WF.statusBadge(st)}</div>
        <div class="grid grid-cols-3 text-telemetry-micro text-on-surface-variant mt-0.5">${['T', 'RH', 'P'].map((v) => `<span>${v} ${WF.fmt(s.latest && s.latest[v], v)}</span>`).join('')}</div>
        ${flagged ? `<div class="text-telemetry-micro ${WF.STATUS_META[st].text} truncate">${esc(flagged)}</div>` : ''}
      </button>`;
    }).join('') : '<div class="p-space-md text-telemetry-micro text-outline">No station matches.</div>';
  }

  let token = 0;
  async function renderDetail(force) {
    const el = document.getElementById('st-detail');
    const s = WF.stationById(ui.selected);
    if (!s) { el.innerHTML = '<div class="panel p-space-lg text-center text-telemetry-micro text-outline">No station selected.</div>'; return; }
    const st = WF.stationStatus(s);
    const key = `${s.id}|${s.latest_ts}|${st}`;
    if (!force && el.dataset.key === key) return;
    el.dataset.key = key;
    const t = ++token;
    const nb = WF.neighbours(s.id, 6);
    const health = WF.healthFor(s.id);
    const openIncs = WF.state.incidents.filter((i) => i.station_id === s.id && i.state === 'open');
    el.innerHTML = `
      <div class="panel p-space-md flex flex-col gap-space-sm">
        <div class="flex items-start justify-between gap-2">
          <div><div class="font-display-lg text-[26px] leading-8 font-bold">${esc(s.name)} <span class="text-body-lg text-outline">${esc(s.id)}</span></div>
            <div class="flex items-center gap-2 mt-1">${WF.statusBadge(st)}${s.simulated_event ? '<span class="badge b-genuine">inside simulated event</span>' : ''}${openIncs.length ? `<span class="badge b-state">${openIncs.length} open incident${openIncs.length > 1 ? 's' : ''}</span>` : ''}</div></div>
          <div class="flex gap-space-xs">
            <button class="act-btn" data-st-act="triage" ${openIncs.length ? '' : 'disabled'}><span class="material-symbols-outlined text-sm">assignment_late</span>Triage</button>
            <button class="act-btn" data-st-act="wo"><span class="material-symbols-outlined text-sm">build</span>Work order</button>
            <a class="act-btn" href="/export?station_id=${encodeURIComponent(s.id)}"><span class="material-symbols-outlined text-sm">download</span>CSV</a>
          </div>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-space-xs text-telemetry-micro">
          <div class="sub-panel !p-space-xs"><div class="sub-title">Coordinates</div>${s.lat != null ? `${Number(s.lat).toFixed(3)}°N, ${Number(s.lon).toFixed(3)}°E` : '—'}</div>
          <div class="sub-panel !p-space-xs"><div class="sub-title">Elevation</div>${s.elevation != null ? `${Number(s.elevation).toFixed(0)} m` : '—'}</div>
          <div class="sub-panel !p-space-xs"><div class="sub-title">Last reading</div>${WF.fmtTs(s.latest_ts)}</div>
          <div class="sub-panel !p-space-xs"><div class="sub-title">Neighbour check (latest verdict)</div>${esc(WF.spatialText(s.spatial_support, s.n_neighbours))}</div>
        </div>
      </div>
      ${['T', 'RH', 'P'].map((v) => `<div class="panel p-space-sm"><div class="panel-title">${WF.VARNAME[v]} (${WF.UNIT[v]}) · last 48 h</div><div class="h-44"><canvas id="st-chart-${v}"></canvas></div></div>`).join('')}
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-space-sm">
        <div class="panel p-space-sm"><div class="panel-title">Nearest stations (latest readings)</div>
          ${nb.length ? `<table class="tbl"><thead><tr><th>Station</th><th>km</th><th>T</th><th>RH</th><th>P</th><th>Status</th></tr></thead><tbody>
          ${nb.map(({ s: n, km }) => `<tr class="cursor-pointer hover:bg-surface-container" data-sid="${esc(n.id)}"><td>${esc(n.name)}</td><td>${km.toFixed(0)}</td>${['T', 'RH', 'P'].map((v) => `<td>${WF.fmt(n.latest && n.latest[v])}</td>`).join('')}<td>${WF.statusBadge(WF.stationStatus(n))}</td></tr>`).join('')}
          <tr class="text-primary"><td>${esc(s.name)} (this)</td><td>0</td>${['T', 'RH', 'P'].map((v) => `<td>${WF.fmt(s.latest && s.latest[v])}</td>`).join('')}<td>${WF.statusBadge(st)}</td></tr></tbody></table>`
          : '<div class="text-telemetry-micro text-outline">No other station with coordinates.</div>'}
          <div class="text-telemetry-micro text-outline mt-1">Distances are great-circle from the registry coordinates. The scorer's own neighbour set may differ.</div></div>
        <div class="panel p-space-sm"><div class="panel-title">Flag-rate health score</div>
          ${health.some((h) => h.score != null) ? health.map((h) => `<div class="kv mb-1.5"><span class="w-24">${WF.VARNAME[h.variable]}</span><span class="flex-1 mx-2 bar-bg"><span class="block h-full ${h.score < 0.5 ? 'bg-error' : h.score < 0.8 ? 'bg-secondary' : 'bg-primary'}" style="width:${100 * (h.score || 0)}%"></span></span><span>${h.score != null ? WF.pct(h.score) : '—'}</span></div>`).join('')
            : '<div class="text-telemetry-micro text-outline">The running scorer does not report a health score (the stand-in demo scorer never does).</div>'}
          <div class="text-telemetry-micro text-outline mt-1">Starts at 100 %, −5 points per flagged reading, +1 per normal reading. A flag-rate indicator, not a hardware diagnostic.</div></div>
      </div>`;
    let series = [];
    try { series = (await WF.api(`/stations/${encodeURIComponent(s.id)}/series?hours=48`)).series || []; } catch (e) { /* empty */ }
    if (t !== token) return;
    const inc = openIncs[0];
    ['T', 'RH', 'P'].forEach((v) => WF.drawSeries(document.getElementById(`st-chart-${v}`), series, v, { legend: v === 'T', highlightFrom: inc && inc.variable === v ? inc.start_ts : null, highlightTo: inc && inc.end_ts }));
  }

  function render() {
    if (WF.state.view !== 'stations') return;
    renderList(); renderDetail(false);
  }

  WF.on('data', render);
  WF.on('view', ({ view, arg }) => { if (view === 'stations') { if (arg) ui.selected = arg; render(); } });

  WF.stationsInit = function () {
    document.getElementById('st-search').addEventListener('input', (e) => { ui.q = e.target.value; renderList(); });
    document.getElementById('st-status').addEventListener('change', (e) => { ui.status = e.target.value; renderList(); });
    document.getElementById('st-sort').addEventListener('change', (e) => { ui.sort = e.target.value; renderList(); });
    const pick = (e) => { const b = e.target.closest('[data-sid]'); if (!b) return; ui.selected = b.dataset.sid; renderList(); renderDetail(true); };
    document.getElementById('st-list').addEventListener('click', pick);
    document.getElementById('st-detail').addEventListener('click', (e) => {
      const a = e.target.closest('[data-st-act]');
      if (a && !a.disabled) {
        if (a.dataset.stAct === 'triage') WF.openStationDrawer(ui.selected);
        if (a.dataset.stAct === 'wo') WF.openWorkOrderModal({ station_id: ui.selected });
        return;
      }
      pick(e);
    });
  };
})();
