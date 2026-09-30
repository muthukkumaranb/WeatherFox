/* 04 Maintenance: browser-local work orders, plus the real health scores from /health/sensors. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;
  const COLS = [['open', 'Open'], ['in_progress', 'In progress'], ['done', 'Done']];
  const NEXT = { open: 'in_progress', in_progress: 'done' };

  function renderBoard() {
    const list = WF.wo.list();
    const open = list.filter((w) => w.status !== 'done').length;
    const badge = document.getElementById('nav-wo-badge');
    badge.textContent = open;
    badge.classList.toggle('hidden', open === 0);
    document.getElementById('wo-board').innerHTML = COLS.map(([k, label]) => {
      const items = list.filter((w) => w.status === k);
      return `<div class="flex flex-col gap-space-xs">
        <div class="kv text-outline font-label-mono-bold uppercase"><span>${label}</span><span class="chip">${items.length}</span></div>
        ${items.length ? items.map((w) => {
          const inc = w.incident_id && WF.state.incidents.find((i) => i.incident_id === w.incident_id);
          return `<div class="card">
            <div class="kv"><span class="font-label-mono-bold text-on-surface">${esc(w.id)}</span><span class="badge ${w.priority === 'high' ? 'b-anomaly' : w.priority === 'medium' ? 'b-uncertain' : 'b-state'}">${esc(w.priority)}</span></div>
            <div class="text-body-md font-bold">${esc(WF.stationName(w.station_id))} <span class="text-telemetry-micro text-outline">${esc(w.station_id)} · ${esc(w.variable)}</span></div>
            ${w.description ? `<div class="text-telemetry-micro text-on-surface-variant">${esc(w.description)}</div>` : ''}
            <div class="text-telemetry-micro text-outline">${w.assignee ? `Assigned: ${esc(w.assignee)} · ` : ''}created ${esc(new Date(w.created_utc).toISOString().slice(0, 16).replace('T', ' '))} UTC${inc ? ` · incident ${esc(inc.state)}` : ''}</div>
            <div class="flex gap-1">
              ${NEXT[w.status] ? `<button class="act-btn flex-1 justify-center" data-wo="${esc(w.id)}" data-to="${NEXT[w.status]}">${w.status === 'open' ? 'Start' : 'Mark done'}</button>` : `<button class="act-btn flex-1 justify-center" data-wo="${esc(w.id)}" data-to="open">Reopen</button>`}
              ${inc && inc.state === 'open' && w.status === 'done' ? `<button class="act-btn act-primary" data-resolve="${esc(inc.incident_id)}">Resolve incident</button>` : ''}
            </div>
          </div>`;
        }).join('') : '<div class="text-telemetry-micro text-outline py-2">—</div>'}
      </div>`;
    }).join('');
  }

  function renderHealth() {
    const rows = WF.state.health.filter((h) => h.score != null).sort((a, b) => a.score - b.score).slice(0, 60);
    const el = document.getElementById('health-list');
    if (!rows.length) {
      el.innerHTML = '<div class="text-telemetry-micro text-outline">No health scores: the running scorer does not report them (the stand-in demo scorer never does; the trained model does).</div>';
      return;
    }
    el.innerHTML = rows.map((h) => `<button data-sid="${esc(h.station_id)}" class="kv px-1 py-1 rounded hover:bg-surface-container text-left">
      <span class="w-40 truncate">${esc(WF.stationName(h.station_id))} · ${esc(h.variable)}</span>
      <span class="flex-1 mx-2 bar-bg"><span class="block h-full ${h.score < 0.5 ? 'bg-error' : h.score < 0.8 ? 'bg-secondary' : 'bg-primary'}" style="width:${100 * h.score}%"></span></span>
      <span class="w-12 text-right">${WF.pct(h.score)}</span></button>`).join('');
  }

  const render = () => { if (WF.state.view === 'maintenance') { renderBoard(); renderHealth(); } else renderBoard(); };
  WF.on('workorders', render);
  WF.on('data', render);
  WF.on('health', render);
  WF.on('view', ({ view }) => { if (view === 'maintenance') render(); });

  WF.maintenanceInit = function () {
    document.getElementById('wo-new').onclick = () => WF.openWorkOrderModal({});
    document.getElementById('wo-board').addEventListener('click', async (e) => {
      const b = e.target.closest('[data-wo]');
      if (b) { WF.wo.update(b.dataset.wo, { status: b.dataset.to, updated_utc: new Date().toISOString() }); return; }
      const r = e.target.closest('[data-resolve]');
      if (r) {
        const inc = WF.state.incidents.find((i) => i.incident_id === r.dataset.resolve);
        if (inc) { await WF.setIncidentState(inc, 'resolved'); WF.toast('Incident resolved', WF.stationName(inc.station_id), 'primary'); }
      }
    });
    document.getElementById('health-list').addEventListener('click', (e) => {
      const b = e.target.closest('[data-sid]'); if (b) WF.go('stations', b.dataset.sid);
    });
    render();
  };
})();
