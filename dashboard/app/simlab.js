/* 05 Simulation lab: inject faults / weather events into the running replay, watch the verdicts; score a CSV. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;

  // Each scenario maps 1:1 to a backend call. Magnitudes are what gets sent; nothing else is simulated here.
  const SCENARIOS = [
    { id: '55C', kind: 'fault', variable: 'T', title: 'Temperature stuck at 55 °C', note: 'Out-of-range value for 6 h (preset "55C").', body: { preset: '55C' } },
    { id: 'radiation', kind: 'fault', variable: 'T', title: 'Radiation-shield heating', note: 'Daytime warm bias of up to +5 °C for 3 days (preset "radiation").', body: { preset: 'radiation' } },
    { id: 'spike', kind: 'fault', variable: 'T', title: 'Single temperature spike +12 °C', note: 'One reading jumps, then back to normal.', body: { variable: 'T', root_cause: 'spike', magnitude: 12, duration_hours: 1 } },
    { id: 'frozen', kind: 'fault', variable: 'RH', title: 'Humidity sensor frozen', note: 'RH repeats its last value for 8 h.', body: { variable: 'RH', root_cause: 'frozen', magnitude: 0, duration_hours: 8 } },
    { id: 'drift', kind: 'fault', variable: 'T', title: 'Slow temperature drift', note: '+0.4 °C per hour for 12 h.', body: { variable: 'T', root_cause: 'drift', magnitude: 0.4, duration_hours: 12 } },
    { id: 'offset', kind: 'fault', variable: 'P', title: 'Barometer offset −6 hPa', note: 'Constant −6 hPa for 6 h.', body: { variable: 'P', root_cause: 'offset', magnitude: -6, duration_hours: 6 } },
    { id: 'heat_wave', kind: 'event', variable: 'T', title: 'Real heat wave (station + neighbours)', note: '+6 °C, −15 % RH at the station and all its neighbours for 6 h. Should be protected, not flagged.', body: { kind: 'heat_wave', duration_hours: 6 } },
    { id: 'squall', kind: 'event', variable: 'T', title: 'Real squall (station + neighbours)', note: '−8 °C, +30 % RH, +3 hPa, ramped, for 3 h.', body: { kind: 'squall', duration_hours: 3 } },
  ];
  const ui = { scenario: '55C', run: null, poll: null };

  function renderScenarios() {
    document.getElementById('sim-scenarios').innerHTML = SCENARIOS.map((s) => `
      <label class="sub-panel !p-space-xs flex items-start gap-2 cursor-pointer ${ui.scenario === s.id ? 'border-primary' : ''}">
        <input type="radio" name="sim-scn" value="${s.id}" class="mt-1 accent-primary" ${ui.scenario === s.id ? 'checked' : ''}>
        <span><span class="font-label-mono-bold text-body-md ${s.kind === 'event' ? 'text-tertiary' : 'text-on-surface'}">${esc(s.title)}</span>
        <span class="block text-telemetry-micro text-outline">${esc(s.note)}</span></span></label>`).join('');
  }

  function renderStations() {
    const sel = document.getElementById('sim-station');
    const cur = sel.value;
    sel.innerHTML = WF.state.stations.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)))
      .map((s) => `<option value="${esc(s.id)}">${esc(s.name)} (${esc(s.id)}) · ${WF.STATUS_META[WF.stationStatus(s)].label}</option>`).join('');
    if (cur && WF.stationById(cur)) sel.value = cur;
  }

  /* Fixed-threshold check with the server's configured limits, run here on the readings since injection. */
  function staticRules(rows, variable) {
    const rg = (WF.state.config && WF.state.config.rule_gate) || null;
    if (!rg) return { text: 'Thresholds not loaded.', fired: false };
    const lo = rg[`${variable}_min`], hi = rg[`${variable}_max`];
    const step = rg.step && rg.step.c60 ? rg.step.c60[variable] : null;
    const hits = [];
    rows.forEach((r, i) => {
      const x = r[variable];
      if (x == null) return;
      if ((lo != null && x < lo) || (hi != null && x >= hi)) hits.push(`${WF.fmtTs(r.ts_utc, false)} ${WF.fmt(x, variable)} outside [${lo}, ${hi}]`);
      else if (step != null && i > 0 && rows[i - 1][variable] != null && Math.abs(x - rows[i - 1][variable]) > step) hits.push(`${WF.fmtTs(r.ts_utc, false)} step ${Math.abs(x - rows[i - 1][variable]).toFixed(1)} > ${step}`);
    });
    return { fired: hits.length > 0, text: hits.length ? `Fired on ${hits.length} reading${hits.length > 1 ? 's' : ''}: ${hits.slice(0, 3).join('; ')}${hits.length > 3 ? '…' : ''}` : `No reading crossed a fixed limit (range ${lo}…${hi} ${WF.UNIT[variable]}, hourly step ${step ?? '—'}).` };
  }

  async function poll() {
    const run = ui.run;
    if (!run) return;
    let series = [];
    try { series = (await WF.api(`/stations/${encodeURIComponent(run.sid)}/series?hours=48`)).series || []; } catch (e) { return; }
    const after = series.filter((r) => r.ts_utc > run.fromTs);
    const touched = after.filter((r) => r.injected || r.simulated_event);
    WF.drawSeries(document.getElementById('sim-chart'), series.slice(-60), run.variable, { highlightFrom: touched[0] && touched[0].ts_utc, highlightTo: touched.length ? touched[touched.length - 1].ts_utc : null, highlightColor: run.kind === 'event' ? '#c0c1ff' : '#ffb4ab' });
    const rules = staticRules(touched, run.variable);
    document.getElementById('sim-rule').innerHTML = touched.length
      ? `<div class="font-label-mono-bold ${rules.fired ? 'text-error' : 'text-primary'}">${rules.fired ? 'FLAGGED' : 'PASSED'}</div><div>${esc(rules.text)}</div><div class="text-outline mt-1">Computed in the browser from the server's configured limits, for comparison only.</div>`
      : '<span class="text-outline">Waiting for the replay to reach the injected readings…</span>';
    const c = { anomaly: 0, uncertain: 0, genuine: 0, normal: 0, unscored: 0 };
    touched.forEach((r) => { c[r.genuine_event ? 'genuine' : (c[r.label] !== undefined ? r.label : 'unscored')] += 1; });
    const inc = WF.state.incidents.find((i) => i.station_id === run.sid && i.end_ts > run.fromTs);
    const badge = document.getElementById('sim-verdict-badge');
    if (!touched.length) { badge.className = 'chip'; badge.textContent = 'waiting for readings'; return; }
    let verdict;
    if (c.anomaly) verdict = ['b-anomaly', 'Flagged as sensor fault'];
    else if (c.uncertain) verdict = ['b-uncertain', 'Flagged as uncertain'];
    else if (c.genuine) verdict = ['b-genuine', 'Protected as real weather'];
    else verdict = ['b-normal', 'Not flagged'];
    badge.className = `badge ${verdict[0]}`;
    badge.textContent = verdict[1];
    document.getElementById('sim-model').innerHTML = `
      <div class="grid grid-cols-4 gap-1 mb-1 text-center">${[['anomaly', 'text-error'], ['uncertain', 'text-secondary'], ['genuine', 'text-tertiary'], ['normal', 'text-primary']].map(([k, cl]) => `<div class="sub-panel !p-1"><div class="font-label-mono-bold ${cl}">${c[k]}</div><div class="text-outline">${k === 'genuine' ? 'real wx' : k}</div></div>`).join('')}</div>
      <div class="text-outline">Verdicts on the ${touched.length} affected reading${touched.length > 1 ? 's' : ''} so far.</div>
      ${inc ? `<div class="mt-1"><strong class="text-on-surface">${esc(WF.cause(inc.root_cause))}</strong> · ${esc((inc.reasons && inc.reasons[0] && inc.reasons[0].text) || '')}</div><button class="act-btn mt-1" data-goto-inc="${esc(inc.incident_id)}">Open incident</button>` : ''}`;
    if (Date.now() - run.started > 5 * 60e3) { clearInterval(ui.poll); ui.poll = null; }
  }

  async function inject() {
    const sid = document.getElementById('sim-station').value;
    const scn = SCENARIOS.find((s) => s.id === ui.scenario);
    if (!sid || !scn) return;
    const btn = document.getElementById('sim-run');
    btn.disabled = true;
    try {
      const s = WF.stationById(sid);
      const res = await WF.post(scn.kind === 'event' ? '/inject-event' : '/inject-fault', Object.assign({ station_id: sid }, scn.body));
      ui.run = { sid, kind: scn.kind, variable: scn.variable, fromTs: (s && s.latest_ts) || '', started: Date.now() };
      document.getElementById('sim-log').textContent = `${res.message || 'Injected'} at data time ${WF.fmtTs(ui.run.fromTs)}.`;
      document.getElementById('sim-rule').textContent = '—';
      document.getElementById('sim-model').textContent = '—';
      WF.toast('Injected', `${scn.title} → ${WF.stationName(sid)}`, scn.kind === 'event' ? 'tertiary' : 'secondary');
      clearInterval(ui.poll);
      ui.poll = setInterval(poll, 2000);
      poll();
    } catch (e) {
      WF.toast('Injection failed', e.message, 'error');
    } finally { btn.disabled = false; }
  }

  /* ---------- CSV upload ---------- */
  async function uploadCsv(file) {
    const out = document.getElementById('csv-result');
    out.innerHTML = `<div class="text-telemetry-micro text-outline">Scoring ${esc(file.name)}…</div>`;
    const fd = new FormData();
    fd.append('data_file', file);
    try {
      const res = await WF.api('/upload/score', { method: 'POST', body: fd });
      const lab = (res.counts && res.counts.label) || {};
      const rc = (res.counts && res.counts.root_cause) || {};
      out.innerHTML = `
        <div class="grid grid-cols-2 md:grid-cols-5 gap-space-xs mb-2">${[['Valid rows', res.n_valid], ['Invalid rows', res.invalid_count], ['Anomaly', lab.anomaly || 0], ['Uncertain', lab.uncertain || 0], ['Normal', lab.normal || 0]].map(([k, v]) => `<div class="sub-panel !p-space-xs"><div class="sub-title">${k}</div><div class="font-label-mono-bold text-body-lg">${v ?? 0}</div></div>`).join('')}</div>
        ${Object.keys(rc).length ? `<div class="text-telemetry-micro text-on-surface-variant mb-2">Causes: ${Object.entries(rc).map(([k, v]) => `${esc(WF.cause(k))} ${v}`).join(' · ')}</div>` : ''}
        ${(res.alerts || []).length ? `<table class="tbl"><thead><tr><th>Station</th><th>Time</th><th>Cause</th><th>Source</th><th>Reason</th></tr></thead><tbody>
          ${res.alerts.slice(0, 100).map((a) => `<tr><td>${esc(a.station_id)}</td><td>${esc(a.ts_utc)}</td><td>${esc(WF.cause(a.root_cause))}</td><td>${esc(a.source)}</td><td>${esc(a.reason)}</td></tr>`).join('')}</tbody></table>`
          : '<div class="text-telemetry-micro text-primary">No anomalies in this file.</div>'}`;
    } catch (e) {
      out.innerHTML = `<div class="text-telemetry-micro text-error">${esc(e.message)}</div>`;
    }
  }

  async function sampleCsv() {
    const sid = document.getElementById('sim-station').value || (WF.state.stations[0] || {}).id;
    let series = [];
    try { series = (await WF.api(`/stations/${encodeURIComponent(sid)}/series?hours=48`)).series || []; } catch (e) { /* empty */ }
    const rows = series.filter((r) => r.T != null).slice(-24);
    if (!rows.length) { WF.toast('No data yet', 'Wait for the replay to produce readings.', 'secondary'); return; }
    const k = Math.floor(rows.length * 0.75);
    const lines = ['station_id,ts_utc,T,RH,P'].concat(rows.map((r, i) => [sid, r.ts_utc, i === k ? 55.0 : r.T, r.RH ?? '', r.P ?? ''].join(',')));
    const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${sid}_last24_with_one_injected_55C.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  WF.on('data', () => { if (WF.state.view === 'simulation-lab') renderStations(); });
  WF.on('view', async ({ view }) => {
    if (view !== 'simulation-lab') return;
    renderStations();
    try { WF.state.config = await WF.api('/config'); const sf = WF.state.config.replay && WF.state.config.replay.speed_factor; if (sf) document.getElementById('sim-speed').value = String(Math.round(sf)); } catch (e) { /* keep */ }
  });

  WF.simInit = function () {
    renderScenarios();
    document.getElementById('sim-scenarios').addEventListener('change', (e) => { if (e.target.name === 'sim-scn') { ui.scenario = e.target.value; renderScenarios(); } });
    document.getElementById('sim-run').onclick = inject;
    document.getElementById('sim-speed').onchange = async (e) => {
      try { await WF.post('/replay/speed', { speed_factor: Number(e.target.value) }); WF.toast('Replay speed', `${e.target.value}× real time`, 'primary'); } catch (err) { WF.toast('Failed', err.message, 'error'); }
    };
    document.getElementById('sim-model').addEventListener('click', (e) => { const b = e.target.closest('[data-goto-inc]'); if (b) WF.go('incidents', b.dataset.gotoInc); });
    const input = document.getElementById('csv-input');
    input.onchange = () => { if (input.files[0]) uploadCsv(input.files[0]); input.value = ''; };
    const drop = document.getElementById('csv-drop');
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('border-primary'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('border-primary'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('border-primary'); if (e.dataTransfer.files[0]) uploadCsv(e.dataTransfer.files[0]); });
    document.getElementById('csv-sample').onclick = sampleCsv;
  };
})();
