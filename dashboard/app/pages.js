/* Settings (read-only config from /config) and Documentation (how the system works, with its limits). */
(function () {
  'use strict';
  const WF = window.WF;
  const esc = WF.esc;

  async function settings() {
    const el = document.getElementById('settings-body');
    let c;
    try { c = await WF.api('/config'); WF.state.config = c; } catch (e) { el.innerHTML = `<div class="panel p-space-md text-error text-telemetry-micro">Could not load /config: ${esc(e.message)}</div>`; return; }
    const rg = c.rule_gate || {}, cf = c.conformal || {}, det = c.detector || {}, h = c.harness || {}, sc = c.scorer || {};
    const steps = rg.step || {};
    const ev = (c.genuine_events && c.genuine_events.events) || [];
    el.innerHTML = `
      <div class="panel p-space-sm"><div class="panel-title">Scorer and replay</div>
        <table class="tbl"><tbody>
          <tr><td>Backend</td><td>${esc(sc.backend)}</td></tr><tr><td>Model version</td><td>${esc(sc.model_version)}</td></tr>
          <tr><td>Banner</td><td>${esc(sc.banner_text)}</td></tr>
          <tr><td>Replay mode</td><td>${esc((c.replay && c.replay.mode) || '—')}</td></tr>
          <tr><td>Replay speed</td><td>${c.replay && c.replay.speed_factor != null ? `${Math.round(c.replay.speed_factor)}× real time (change it in the Simulation lab)` : '—'}</td></tr>
        </tbody></table>
        <div class="text-telemetry-micro text-outline mt-1">The scorer is chosen when the server starts: <code>python -m skyguard.demo --scorer real</code> uses the trained model in <code>models/detector.pkl</code>.</div></div>
      <div class="panel p-space-sm"><div class="panel-title">Rule gate: physical limits (FAIL)</div>
        <table class="tbl"><thead><tr><th>Variable</th><th>Min</th><th>Max</th></tr></thead><tbody>
          ${['T', 'RH', 'P'].map((v) => `<tr><td>${WF.VARNAME[v]} (${WF.UNIT[v]})</td><td>${rg[`${v}_min`] ?? '—'}</td><td>${rg[`${v}_max`] ?? '—'}</td></tr>`).join('')}</tbody></table>
        <div class="text-telemetry-micro text-outline mt-1">Frozen: unchanged for ≥ ${rg.frozen_hours ?? '—'} h (${rg.frozen_hours_integer ?? '—'} h for integer-reported values), at least ${rg.min_frozen_readings ?? '—'} readings. Dew point may exceed T by at most ${rg.td_max_above_t ?? '—'} °C.</div></div>
      <div class="panel p-space-sm"><div class="panel-title">Rule gate: step limits between consecutive readings (SUSPECT)</div>
        <table class="tbl"><thead><tr><th>Reporting interval</th><th>T (°C)</th><th>RH (%)</th><th>P (hPa)</th></tr></thead><tbody>
          ${Object.entries(steps).map(([k, s]) => `<tr><td>${esc(k.replace('c', ''))} min</td><td>${s.T}</td><td>${s.RH}</td><td>${s.P}</td></tr>`).join('')}</tbody></table></div>
      <div class="panel p-space-sm"><div class="panel-title">Model thresholds</div>
        <table class="tbl"><tbody>
          <tr><td>Anomaly if conformal p-value below</td><td>${cf.alpha_anomaly ?? '—'}</td></tr>
          <tr><td>Uncertain if p-value below</td><td>${cf.alpha_uncertain ?? '—'}</td></tr>
          <tr><td>History used per reading</td><td>${det.history_hours ?? '—'} h</td></tr>
          <tr><td>Neighbours used (max / radius)</td><td>${det.max_neighbours ?? '—'} within ${det.max_neighbour_km ?? '—'} km</td></tr>
          <tr><td>Alert budget used in evaluation</td><td>${h.alert_budget ?? '—'} false-alarm incidents per station-day</td></tr>
        </tbody></table>
        <div class="text-telemetry-micro text-outline mt-1">p-values are calibrated per variable and reporting interval on calibration stations that were not used for training.</div></div>
      <div class="panel p-space-sm xl:col-span-2"><div class="panel-title">Real-weather windows used in evaluation</div>
        <table class="tbl"><thead><tr><th>Name</th><th>Type</th><th>From</th><th>To</th><th>Lat</th><th>Lon</th></tr></thead><tbody>
          ${ev.map((e) => `<tr><td>${esc(e.name)}</td><td>${esc(e.type)}</td><td>${esc(e.start)}</td><td>${esc(e.end)}</td><td>${e.lat_min}–${e.lat_max}</td><td>${e.lon_min}–${e.lon_max}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function docs() {
    const el = document.getElementById('docs-body');
    let b = WF.state.benchmark;
    if (!b) { try { b = WF.state.benchmark = await WF.api('/benchmark'); } catch (e) { b = null; } }
    const wf = b && b.detection && b.detection.arms && b.detection.arms.skyguard ? b.detection.arms.skyguard.summary : null;
    const p = (x, d = 1) => (x == null ? '—' : `${(100 * x).toFixed(d)} %`);
    const card = (title, html) => `<div class="panel p-space-md"><div class="doc-h">${title}</div>${html}</div>`;
    el.innerHTML =
      card('The problem', `<p class="doc-p">Automatic weather stations report temperature, humidity and pressure unattended. Sensors fail in recognisable ways (spikes, stuck values, slow drift, offsets, radiation-shield heating), but real weather can look extreme too: a heat wave or a cyclone moves several stations at once. Fixed thresholds either miss subtle faults or flag real extremes. WeatherFox separates the two and tells an operator what happened, why, how sure it is, and what to do.</p>`) +
      card('How a reading is scored', `<ol class="doc-p list-decimal pl-5 space-y-1">
        <li><strong>Rule gate.</strong> Physically impossible values FAIL; implausible jumps and stuck values are SUSPECT. Limits are on the Settings page.</li>
        <li><strong>Forecast.</strong> A LightGBM model predicts each variable from the station's recent history and climatology, with a 5–95 % band.</li>
        <li><strong>Neighbours.</strong> Nearby stations' residuals estimate what this station should be doing right now.</li>
        <li><strong>Fusion and calibration.</strong> The two residuals are combined by their uncertainty and turned into a conformal p-value, calibrated per variable and reporting interval on stations kept out of training.</li>
        <li><strong>Real-weather protection.</strong> If neighbours deviate the same way, the reading is treated as weather, not a fault.</li>
        <li><strong>Verdict.</strong> Label, likely cause, reasons, a corrected estimate, and a suggested action. Consecutive flags are grouped into incidents.</li></ol>`) +
      card('The four triage questions', `<p class="doc-p">Every incident panel answers: <strong>What happened?</strong> (variable, cause, time span) · <strong>Why was it flagged?</strong> (the verdict's own reasons and the neighbour check) · <strong>How sure is it?</strong> (confidence and label) · <strong>What should be done?</strong> (the verdict's suggested action). Acknowledge, Resolve and Real weather are stored by the server as feedback.</p>`) +
      card('Modes', `<ul class="doc-p list-disc pl-5 space-y-1"><li><strong>Demo mode</strong>: a stand-in rule-based scorer so the interface can be shown without the trained model. The banner says so.</li>
        <li><strong>Trained model</strong>: <code>--scorer real</code> with <code>models/detector.pkl</code>. The banner shows the model version.</li>
        <li><strong>Live</strong>: the latest IMD WIS 2.0 SYNOP reports. Live station IDs are not yet mapped to the stations the model was trained on, so the trained model would score them without history or neighbours; run live mode with the stand-in scorer until that mapping exists.</li></ul>`) +
      card('What the evaluation says', wf ? `<p class="doc-p">On the final test (run once, 2024 data and stations unseen in training, synthetic faults injected into real observations) WeatherFox found ${p(wf.event_recall)} of injected faults with ${p(wf.incident_precision)} incident precision (F1 ${wf.f1_score.toFixed(3)}), within the alert budget. Details and the three baselines are on the Evaluation page.</p>`
        : '<p class="doc-p">No final-test results are available on this server.</p>') +
      card('Known limits', `<ul class="doc-p list-disc pl-5 space-y-1">
        <li>Humidity faults and slow drift are detected far less often than temperature and pressure faults (see recall by fault type).</li>
        <li>Clean-reading uncertain rate is ${wf ? p(wf.clean_uncertain_rate, 2) : '—'} against a 3 % target; most of the excess comes from the pressure step rule, not from the model's calibration.</li>
        <li>Ingest-level faults (comms gaps, duplicates, time shifts, power) are handled in the replay/ingest layer and are not part of the scored evaluation.</li>
        <li>Health scores are a flag-rate indicator, not a hardware diagnostic; no time-to-maintenance is estimated.</li>
        <li>Edge (C) figures are measured on a laptop CPU, not on ESP32 hardware.</li></ul>`);
  }

  WF.on('view', ({ view }) => { if (view === 'settings') settings(); if (view === 'documentation') docs(); });
})();
