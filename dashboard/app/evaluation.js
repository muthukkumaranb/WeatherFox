/* 06 Evaluation: everything read from /benchmark (committed reports). No number is typed into this file. */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;
  const ARM_LABEL = { skyguard: 'WeatherFox', rules_only: 'Rules only', zscore: 'Z-score', isolation_forest: 'Isolation Forest' };
  const f = (x, d = 3) => (x == null ? '—' : Number(x).toFixed(d));
  const p = (x, d = 1) => (x == null ? '—' : `${(100 * x).toFixed(d)} %`);

  function statusChip(sec) {
    if (!sec) return '<span class="badge b-state">missing</span>';
    return sec.status === 'ok' ? `<span class="badge b-normal">from ${esc(sec.source_file || '')}</span>` : `<span class="badge b-uncertain">${esc(sec.status)}</span>`;
  }

  function detection(d) {
    if (!d || d.status !== 'ok' || !d.arms) return `<div class="panel p-space-md text-telemetry-micro text-outline">Detection results not available (${esc(d && d.status)}). Run the final test and commit reports/final/metrics.json.</div>`;
    const arms = Object.keys(d.arms);
    const S = (a) => (d.arms[a] && d.arms[a].summary) || {};
    const wf = S('skyguard');
    const baselines = arms.filter((a) => a !== 'skyguard');
    const bestBase = baselines.reduce((b, a) => (S(a).f1_score > (S(b) || {}).f1_score ? a : b), baselines[0]);
    const tiles = [
      ['F1', f(wf.f1_score), bestBase ? `best baseline ${ARM_LABEL[bestBase] || bestBase}: ${f(S(bestBase).f1_score)}` : ''],
      ['Incident precision', p(wf.incident_precision), bestBase ? `${ARM_LABEL[bestBase] || bestBase}: ${p(S(bestBase).incident_precision)}` : ''],
      ['Event recall', p(wf.event_recall), `${wf.detected_fault_events ?? '—'} of ${wf.total_fault_events ?? '—'} injected faults`],
      [`Recall within alert budget`, p(wf.recall_at_alert_budget), `budget ≤ ${wf.alert_budget ?? '—'} false-alarm incidents per station-day; WeatherFox: ${f(wf.false_alarm_incidents_per_station_day, 4)}`],
    ];
    const rows = [
      ['Event recall', 'event_recall', p], ['Incident precision', 'incident_precision', p], ['F1', 'f1_score', f],
      ['False-alarm incidents / station-day', 'false_alarm_incidents_per_station_day', (x) => f(x, 4)],
      ['Recall within alert budget', 'recall_at_alert_budget', p],
      ['Clean anomaly rate (per reading)', 'clean_false_alarm_rate', (x) => p(x, 2)],
      ['Clean uncertain rate (per reading)', 'clean_uncertain_rate', (x) => p(x, 2)],
      ['False alarms / 100 station-days in real-weather windows', 'genuine_event_fa_per_100_st_days', (x) => f(x, 2)],
    ];
    const pc = (d.arms.skyguard && d.arms.skyguard.per_class) || {};
    const pcBase = (d.arms.rules_only && d.arms.rules_only.per_class) || {};
    const classes = Object.keys(pc).sort((a, b) => pc[b].recall - pc[a].recall);
    return `
      <div class="panel p-space-sm"><div class="flex items-center justify-between"><div class="panel-title">Final test (run once)</div>${statusChip(d)}</div>
        <div class="text-telemetry-micro text-on-surface-variant leading-relaxed">${esc(d.context)}</div></div>
      <div class="grid grid-cols-2 xl:grid-cols-4 gap-space-sm">${tiles.map(([k, v, s]) => `<div class="kpi"><div class="text-telemetry-micro text-outline uppercase">${k}</div><div class="font-display-lg text-[30px] font-bold text-primary my-1">${v}</div><div class="text-telemetry-micro text-outline">${esc(s)}</div></div>`).join('')}</div>
      <div class="panel p-space-sm"><div class="panel-title">Four arms on the same rows</div>
        <table class="tbl"><thead><tr><th>Metric</th>${arms.map((a) => `<th class="${a === 'skyguard' ? 'text-primary' : ''}">${esc(ARM_LABEL[a] || a)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(([l, k, fn]) => `<tr><td>${l}</td>${arms.map((a) => `<td class="${a === 'skyguard' ? 'text-primary font-label-mono-bold' : ''}">${fn(S(a)[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <div class="panel p-space-sm"><div class="panel-title">Recall by variable × fault type (WeatherFox vs rules only)</div>
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-x-space-lg gap-y-1">${classes.map((k) => `
          <div class="text-telemetry-micro"><div class="kv"><span>${esc(k.replace(' x ', ' · ').replace(/_/g, ' '))} <span class="text-outline">(n=${pc[k].n_events})</span></span><span><span class="text-primary">${p(pc[k].recall, 0)}</span> <span class="text-outline">vs ${p(pcBase[k] && pcBase[k].recall, 0)}</span></span></div>
          <div class="relative bar-bg mt-0.5"><div class="absolute inset-y-0 left-0 bg-outline-variant" style="width:${100 * ((pcBase[k] && pcBase[k].recall) || 0)}%"></div><div class="absolute inset-y-0 left-0 bg-primary/80" style="width:${100 * pc[k].recall}%;height:50%"></div></div></div>`).join('')}</div>
        <div class="text-telemetry-micro text-outline mt-1">Upper bar: WeatherFox. Lower bar: rules only. "all · comms gap / duplicate / power / timeshift" are ingest-level faults not scored by the batch scorer, so every arm scores 0 on them.</div></div>`;
  }

  function genuine(g) {
    const ev = g && g.events && g.events.skyguard;
    if (!ev) return '';
    return `<div class="panel p-space-sm"><div class="flex items-center justify-between"><div class="panel-title">Real-weather windows: false alarms WeatherFox raised</div>${statusChip(g)}</div>
      <table class="tbl"><thead><tr><th>Event window</th><th>Stations in box</th><th>Station-days</th><th>False-alarm incidents</th><th>Per 100 station-days</th></tr></thead>
      <tbody>${ev.map((e) => `<tr><td>${esc(e.name.replace(/_/g, ' '))}</td><td>${e.stations_in_bbox}</td><td>${f(e.station_days, 0)}</td><td>${e.false_alarm_incidents}</td><td>${f(e.fa_per_100_st_days, 2)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function drift(dr) {
    const bins = dr && dr.bins && dr.bins.skyguard;
    if (!bins) return '';
    const med = (a) => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
    return `<div class="panel p-space-sm"><div class="panel-title">Drift: how long until detected</div>
      <table class="tbl"><thead><tr><th>Drift rate</th><th>Drift events</th><th>Detected</th><th>Median delay</th></tr></thead>
      <tbody>${Object.entries(bins).map(([k, b]) => `<tr><td>${esc(k)}</td><td>${b.count}</td><td>${b.delays_days.length}</td><td>${med(b.delays_days) != null ? `${med(b.delays_days).toFixed(1)} days` : '—'}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function scale(sc) {
    const r = sc && sc.results;
    if (!r) return '';
    const rows = Object.values(r).filter((x) => x && x.n_stations);
    const any = rows[0] || {};
    return `<div class="panel p-space-sm"><div class="flex items-center justify-between"><div class="panel-title">Throughput</div>${statusChip(sc)}</div>
      <table class="tbl"><thead><tr><th>Simulated stations</th><th>Needed (readings/s)</th><th>Measured (readings/s)</th><th>Headroom</th><th>p95 latency</th></tr></thead>
      <tbody>${rows.map((x) => `<tr><td>${x.n_stations.toLocaleString()}</td><td>${f(x.required_rate_per_sec, 3)}</td><td>${f(x.readings_per_sec_mean, 1)}</td><td>${(x.readings_per_sec_mean / x.required_rate_per_sec).toFixed(0)}×</td><td>${f(x.p95_ms_mean, 1)} ms</td></tr>`).join('')}</tbody></table>
      <div class="text-telemetry-micro text-outline mt-1">One core, scorer "${esc(any.scorer || '')}", ${esc(any.cpu || '')}, Python ${esc(any.python || '')}. Hourly reporting assumed for the "needed" rate.</div></div>`;
  }

  function edge(e) {
    const m = e && e.metrics;
    if (!m) return '';
    const en = e.energy || {};
    return `<div class="panel p-space-sm"><div class="flex items-center justify-between"><div class="panel-title">On-station rule gate (C)</div><span class="badge b-uncertain">${esc(e.label || '')}</span></div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-space-xs text-telemetry-micro">
        <div class="sub-panel"><div class="sub-title">Python ↔ C parity</div><div class="font-label-mono-bold text-body-lg">${m.parity_agreed?.toLocaleString()} / ${m.parity_total?.toLocaleString()}</div></div>
        <div class="sub-panel"><div class="sub-title">Object size</div>${Object.entries(m.object_sizes || {}).map(([k, v]) => `${esc(k)} ${(v / 1024).toFixed(1)} KB`).join('<br>')}</div>
        <div class="sub-panel"><div class="sub-title">Time per reading</div><div class="font-label-mono-bold text-body-lg">${f(m.us_per_reading, 1)} µs</div><div class="text-outline">on a laptop CPU (upper bound)</div></div>
        <div class="sub-panel"><div class="sub-title">Tiny tree accuracy</div><div class="font-label-mono-bold text-body-lg">${p(m.accuracy)}</div><div class="text-outline">${esc(m.training_data || '')}; most rows are normal</div></div>
      </div>
      ${en.fixed_15m ? `<div class="text-telemetry-micro text-on-surface-variant mt-2">Battery (${esc(en.note || '')}): fixed 15-min uplink ≈ ${en.fixed_15m.battery_life_days.toFixed(0)} days; uplinking extra on anomalies ≈ ${en.adaptive_anomaly.battery_life_days.toFixed(0)} days.</div>` : ''}
      <div class="text-telemetry-micro text-outline mt-1">${esc(m.measured_on || '')}. Not measured on ESP32 hardware.</div></div>`;
  }

  function hadisd(h) {
    if (!h || h.status === 'ok') return '';
    return `<div class="panel p-space-sm"><div class="panel-title">Cross-check against HadISD QC flags</div><div class="text-telemetry-micro text-outline">Status: ${esc(h.status)}. Not run yet, so no numbers are shown.</div></div>`;
  }

  let loaded = false;
  async function load() {
    const el = document.getElementById('eval-body');
    if (!loaded) el.innerHTML = '<div class="panel p-space-md text-telemetry-micro text-outline">Loading /benchmark…</div>';
    try {
      const b = await WF.api('/benchmark');
      WF.state.benchmark = b;
      el.innerHTML = detection(b.detection) + `<div class="grid grid-cols-1 xl:grid-cols-2 gap-space-sm">${genuine(b.genuine_events)}${drift(b.drift)}</div>` +
        `<div class="grid grid-cols-1 xl:grid-cols-2 gap-space-sm">${scale(b.scale)}${edge(b.edge)}</div>` + hadisd(b.hadisd);
      loaded = true;
    } catch (e) {
      el.innerHTML = `<div class="panel p-space-md text-telemetry-micro text-error">Could not load /benchmark: ${esc(e.message)}</div>`;
    }
  }
  WF.on('view', ({ view }) => { if (view === 'evaluation') load(); });
})();
