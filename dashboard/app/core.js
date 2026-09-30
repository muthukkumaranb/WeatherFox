/* WeatherFox dashboard: shared state, API access, polling, websocket, router and helpers.
 * Every number shown in the UI comes from the FastAPI backend (same origin). Nothing here is mock data. */
(function () {
  'use strict';
  const WF = (window.WF = {});

  WF.state = {
    stations: [], incidents: [], health: [], scorer: null, config: null, benchmark: null,
    connected: false, dataTime: null, verdictCount: 0, audio: false, view: 'overview',
  };

  /* ---------- tiny event bus ---------- */
  const handlers = {};
  WF.on = (ev, fn) => (handlers[ev] = handlers[ev] || []).push(fn);
  WF.emit = (ev, data) => (handlers[ev] || []).forEach((fn) => {
    try { fn(data); } catch (e) { console.error('[WF]', ev, e); }
  });

  /* ---------- API ---------- */
  WF.api = async function (path, opts = {}) {
    const t0 = performance.now();
    let res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      setConnected(false);
      throw e;
    }
    setLatency(performance.now() - t0);
    setConnected(true);
    if (!res.ok) {
      let msg = '';
      try { msg = (await res.json()).detail; } catch (e) { /* not JSON */ }
      throw new Error(msg || `${res.status} on ${path}`);
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('json') ? res.json() : res.text();
  };
  WF.post = (path, body) => WF.api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  });

  function setLatency(ms) {
    const el = document.getElementById('api-latency');
    if (el) el.textContent = `API ${Math.round(ms)} ms`;
  }
  function setConnected(ok) {
    if (WF.state.connected === ok) return;
    WF.state.connected = ok;
    const dot = document.getElementById('conn-dot');
    const txt = document.getElementById('conn-text');
    const api = document.getElementById('api-dot');
    const cls = ok ? 'bg-primary' : 'bg-error';
    [dot, api].forEach((d) => { if (d) d.className = d.className.replace(/bg-\S+/g, '') + ' ' + cls; });
    if (txt) {
      txt.textContent = ok ? 'API connected' : 'API unreachable';
      txt.className = txt.className.replace(/text-(primary|error|outline)\b/g, '') + (ok ? ' text-primary' : ' text-error');
    }
    WF.emit('connection', ok);
  }

  /* ---------- formatting helpers ---------- */
  WF.esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  WF.UNIT = { T: '°C', RH: '%', P: 'hPa' };
  WF.VARNAME = { T: 'Temperature', RH: 'Relative humidity', P: 'Pressure' };
  WF.fmt = (v, variable) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
    const d = variable === 'RH' ? 0 : 1;
    return `${Number(v).toFixed(d)}${variable ? ' ' + WF.UNIT[variable] : ''}`;
  };
  WF.CAUSE = {
    spike: 'Spike', out_of_range: 'Out of range', frozen: 'Frozen / stuck', drift: 'Slow drift', offset: 'Offset',
    noise: 'Noisy sensor', radiation: 'Radiation-shield heating', comms_gap: 'Comms gap', duplicate: 'Duplicate',
    timeshift: 'Time shift', power: 'Power fault', unknown: 'Unclassified', genuine_event: 'Real weather',
  };
  WF.cause = (c) => WF.CAUSE[c] || (c ? String(c).replace(/_/g, ' ') : 'Unclassified');
  WF.pct = (x, d = 0) => (x === null || x === undefined ? '—' : `${(100 * x).toFixed(d)} %`);

  WF.ts = (s) => (s ? new Date(s) : null);
  WF.fmtTs = (s, withDate = true) => {
    const d = WF.ts(s);
    if (!d || isNaN(d)) return '—';
    const iso = d.toISOString();
    return withDate ? `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC` : `${iso.slice(11, 16)} UTC`;
  };
  // Age relative to the newest reading in the system (replays run in the past, so wall-clock age is meaningless).
  WF.age = (s) => {
    const d = WF.ts(s), ref = WF.ts(WF.state.dataTime);
    if (!d || !ref) return '—';
    const min = Math.max(0, Math.round((ref - d) / 60000));
    if (min < 1) return 'latest';
    if (min < 60) return `${min} min before latest`;
    const h = Math.floor(min / 60), m = min % 60;
    return `${h} h ${m ? m + ' min ' : ''}before latest`;
  };

  /* Station status as the UI shows it. The scorer decides; "genuine" only when the scorer said so. */
  WF.stationStatus = (s) => {
    if (!s) return 'unscored';
    if (s.status === 'offline') return 'offline';
    if (s.genuine_event) return 'genuine';
    return s.status || 'unscored';
  };
  WF.STATUS_META = {
    anomaly: { label: 'Anomaly', badge: 'b-anomaly', color: '#ffb4ab', text: 'text-error', rank: 0 },
    uncertain: { label: 'Uncertain', badge: 'b-uncertain', color: '#ffb690', text: 'text-secondary', rank: 1 },
    genuine: { label: 'Real weather', badge: 'b-genuine', color: '#c0c1ff', text: 'text-tertiary', rank: 2 },
    normal: { label: 'Normal', badge: 'b-normal', color: '#4edea3', text: 'text-primary', rank: 3 },
    unscored: { label: 'Not scored yet', badge: 'b-unscored', color: '#86948a', text: 'text-outline', rank: 4 },
    offline: { label: 'No recent data', badge: 'b-offline', color: '#5b6572', text: 'text-outline', rank: 5 },
  };
  WF.statusBadge = (st) => {
    const m = WF.STATUS_META[st] || WF.STATUS_META.unscored;
    return `<span class="badge ${m.badge}">${m.label}</span>`;
  };
  WF.SEV_RANK = { high: 0, medium: 1, low: 2 };
  WF.incidentRank = (i) => (i.label === 'anomaly' ? 0 : 10) + (WF.SEV_RANK[i.severity] ?? 3);

  /* Coarse region from coordinates (for filtering only). */
  WF.region = (lat, lon) => {
    if (lat == null || lon == null) return 'unknown';
    if (lon >= 88 && lat >= 21.5) return 'ne';
    if (lat < 17.5) return 'south';
    if (lat >= 26 && lon < 84) return 'north';
    if (lon >= 83) return 'east';
    if (lon < 77) return 'west';
    return 'central';
  };

  WF.haversineKm = (a, b) => {
    const R = 6371, rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
    const x = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  };
  WF.neighbours = (sid, k = 6) => {
    const me = WF.stationById(sid);
    if (!me || me.lat == null) return [];
    return WF.state.stations
      .filter((s) => s.id !== sid && s.lat != null)
      .map((s) => ({ s, km: WF.haversineKm(me, s) }))
      .sort((a, b) => a.km - b.km)
      .slice(0, k);
  };

  WF.stationById = (id) => WF.state.stations.find((s) => s.id === id);
  WF.stationName = (id) => { const s = WF.stationById(id); return s ? s.name : id; };
  WF.openIncidents = () => WF.state.incidents.filter((i) => i.state === 'open');
  WF.healthFor = (sid) => WF.state.health.filter((h) => h.station_id === sid);

  /* ---------- incident actions (write through to the backend feedback store) ---------- */
  WF.setIncidentState = async function (inc, newState, reason) {
    const ids = inc.alert_ids && inc.alert_ids.length ? inc.alert_ids : [inc.station_id];
    await Promise.all(ids.map((id) => WF.post(`/alerts/${encodeURIComponent(id)}/ack`, {
      state: newState, reason: reason || null, by: 'dashboard operator',
    })));
    await WF.refresh();
  };

  /* ---------- toast / modal / sound ---------- */
  let toastTimer = null;
  WF.toast = function (title, message, kind = 'primary') {
    const el = document.getElementById('toast');
    const c = { error: 'text-error border-error/60', secondary: 'text-secondary border-secondary/60', tertiary: 'text-tertiary border-tertiary/60', primary: 'text-primary border-primary/60' }[kind] || 'text-primary border-primary/60';
    el.className = `fixed bottom-4 left-64 z-50 bg-surface-container-highest/95 px-space-md py-space-sm rounded shadow-2xl border flex items-center gap-space-md ${c.split(' ')[1]}`;
    el.innerHTML = `<span class="font-label-mono-bold text-telemetry-micro uppercase tracking-wider ${c.split(' ')[0]}">${WF.esc(title)}</span>
      <span class="font-label-mono-regular text-telemetry-micro text-on-surface">${WF.esc(message)}</span>
      <button class="text-outline hover:text-on-surface text-xs font-bold pl-2" onclick="this.parentElement.classList.add('hidden')">✕</button>`;
    el.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add('hidden'), 5000);
  };
  WF.modal = function (html) {
    document.getElementById('modal-content').innerHTML = html;
    document.getElementById('modal').classList.remove('hidden');
  };
  WF.closeModal = () => document.getElementById('modal').classList.add('hidden');

  let audioCtx = null;
  WF.beep = function (kind) {
    if (!WF.state.audio) return;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const tones = { alert: [[880, 0], [660, 0.12]], ok: [[523, 0], [659, 0.09]], click: [[1200, 0]] }[kind] || [[1000, 0]];
      tones.forEach(([f, t]) => {
        const o = audioCtx.createOscillator(), g = audioCtx.createGain();
        o.type = 'triangle'; o.frequency.value = f;
        g.gain.setValueAtTime(0.05, audioCtx.currentTime + t);
        g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + t + 0.18);
        o.connect(g); g.connect(audioCtx.destination);
        o.start(audioCtx.currentTime + t); o.stop(audioCtx.currentTime + t + 0.2);
      });
    } catch (e) { /* audio not available */ }
  };

  /* ---------- router ---------- */
  WF.VIEWS = ['overview', 'incidents', 'stations', 'maintenance', 'simulation-lab', 'evaluation', 'data-qc', 'settings', 'documentation'];
  WF.go = function (view, arg) {
    if (!WF.VIEWS.includes(view)) view = 'overview';
    WF.state.view = view;
    document.querySelectorAll('.nav-item[data-view]').forEach((a) => a.classList.toggle('nav-active', a.dataset.view === view));
    document.querySelectorAll('.app-view').forEach((v) => v.classList.toggle('active-view', v.id === `view-${view}`));
    if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    WF.emit('view', { view, arg });
  };

  /* ---------- polling ---------- */
  let lastOpenIds = null;
  WF.refresh = async function () {
    const [stations, incidents] = await Promise.all([WF.api('/stations'), WF.api('/incidents')]);
    WF.state.stations = stations || [];
    WF.state.incidents = (incidents || []).slice().sort((a, b) => WF.incidentRank(a) - WF.incidentRank(b) || (b.end_ts > a.end_ts ? 1 : -1));
    const times = WF.state.stations.map((s) => s.latest_ts).filter(Boolean).sort();
    WF.state.dataTime = times.length ? times[times.length - 1] : null;

    const openIds = new Set(WF.openIncidents().map((i) => i.incident_id));
    if (lastOpenIds) {
      const fresh = [...openIds].filter((id) => !lastOpenIds.has(id));
      if (fresh.length) {
        const inc = WF.state.incidents.find((i) => i.incident_id === fresh[0]);
        WF.beep('alert');
        WF.toast('New incident', `${WF.stationName(inc.station_id)} · ${WF.VARNAME[inc.variable] || inc.variable} · ${WF.cause(inc.root_cause)}`, inc.label === 'anomaly' ? 'error' : 'secondary');
      }
    }
    lastOpenIds = openIds;
    updateChrome();
    WF.emit('data', WF.state);
  };

  async function refreshSlow() {
    try {
      const [scorer, health] = await Promise.all([WF.api('/scorer-info'), WF.api('/health/sensors')]);
      WF.state.scorer = scorer;
      WF.state.health = health || [];
      updateMode();
      WF.emit('health', WF.state.health);
    } catch (e) { /* shown via connection state */ }
  }

  function updateMode() {
    const s = WF.state.scorer;
    if (!s) return;
    const lvl = s.banner_level || 'warning';
    // Full class names (not built from pieces) so the Tailwind build can see them.
    const C = {
      info: { border: 'border-primary/40', bg: 'bg-primary', text: 'text-primary' },
      warning: { border: 'border-secondary/40', bg: 'bg-secondary', text: 'text-secondary' },
      danger: { border: 'border-error/40', bg: 'bg-error', text: 'text-error' },
    }[lvl] || { border: 'border-secondary/40', bg: 'bg-secondary', text: 'text-secondary' };
    const badge = document.getElementById('mode-badge');
    badge.className = `hidden xl:flex items-center gap-space-xs px-space-sm py-space-xs bg-surface-container border rounded ${C.border}`;
    document.getElementById('mode-dot').className = `inline-flex rounded-full h-2 w-2 ${C.bg}`;
    const t = document.getElementById('mode-badge-text');
    t.className = `font-label-mono-bold text-telemetry-micro tracking-wider uppercase ${C.text}`;
    t.textContent = s.backend === 'fake' ? 'DEMO MODE · STAND-IN SCORER' : s.model_version === 'live' ? 'LIVE · IMD WIS 2.0' : `MODEL ${s.model_version}`;
    const b = document.getElementById('banner-text');
    b.className = `font-label-mono-bold uppercase tracking-wider ${C.text}`;
    b.textContent = s.banner_text || '';
    document.getElementById('model-version-foot').textContent = `${s.backend} · ${s.model_version}`;
  }

  function updateChrome() {
    const st = WF.state;
    const open = WF.openIncidents();
    const badge = document.getElementById('nav-incident-badge');
    badge.textContent = open.length;
    badge.classList.toggle('hidden', open.length === 0);
    document.getElementById('nav-station-count').textContent = st.stations.length || '';
    document.getElementById('bar-stations').textContent = st.stations.length;
    document.getElementById('bar-incidents').textContent = open.length;
    document.getElementById('data-clock').textContent = st.dataTime ? `DATA ${WF.fmtTs(st.dataTime)}` : 'DATA TIME —';
  }

  function tickWallClock() {
    const d = new Date();
    const ist = new Date(d.getTime() + 330 * 60000).toISOString().slice(11, 19);
    document.getElementById('wall-clock').textContent = `now ${d.toISOString().slice(11, 19)} UTC · ${ist} IST`;
  }

  /* ---------- websocket: every verdict as it is produced ---------- */
  function connectWs() {
    let ws;
    try {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`);
    } catch (e) { setTimeout(connectWs, 3000); return; }
    ws.onmessage = (ev) => {
      let v;
      try { v = JSON.parse(ev.data); } catch (e) { return; }
      WF.state.verdictCount += 1;
      document.getElementById('bar-verdicts').textContent = WF.state.verdictCount.toLocaleString();
      WF.emit('verdict', v);
    };
    ws.onclose = () => setTimeout(connectWs, 3000);
    const ping = setInterval(() => { if (ws.readyState === 1) ws.send('ping'); else clearInterval(ping); }, 20000);
  }

  /* ---------- work orders (browser-local; the backend has no work-order store) ---------- */
  const WO_KEY = 'weatherfox.workorders.v1';
  let woMem = [];
  WF.wo = {
    list() {
      try { const raw = localStorage.getItem(WO_KEY); if (raw) woMem = JSON.parse(raw); } catch (e) { /* storage blocked */ }
      return woMem;
    },
    save(list) {
      woMem = list;
      try { localStorage.setItem(WO_KEY, JSON.stringify(list)); } catch (e) { /* in-memory only */ }
      WF.emit('workorders', list);
    },
    add(wo) {
      const list = WF.wo.list();
      const n = list.length + 1;
      const item = Object.assign({ id: `WO-${String(n).padStart(4, '0')}`, status: 'open', created_utc: new Date().toISOString() }, wo);
      WF.wo.save([item, ...list]);
      return item;
    },
    update(id, patch) { WF.wo.save(WF.wo.list().map((w) => (w.id === id ? Object.assign({}, w, patch) : w))); },
  };

  WF.openWorkOrderModal = function (prefill = {}) {
    const opts = WF.state.stations.map((s) => `<option value="${WF.esc(s.id)}" ${s.id === prefill.station_id ? 'selected' : ''}>${WF.esc(s.name)} (${WF.esc(s.id)})</option>`).join('');
    WF.modal(`
      <div class="p-space-md flex flex-col gap-space-sm">
        <div class="flex items-center justify-between border-b border-surface-container-highest pb-2">
          <span class="font-headline-md font-bold">New work order</span>
          <button class="text-outline hover:text-on-surface" onclick="WF.closeModal()">✕</button>
        </div>
        <label class="text-telemetry-micro text-outline">Station<select id="wo-f-station" class="input w-full mt-1">${opts}</select></label>
        <div class="grid grid-cols-2 gap-space-sm">
          <label class="text-telemetry-micro text-outline">Variable<select id="wo-f-var" class="input w-full mt-1">${['T', 'RH', 'P'].map((v) => `<option ${v === prefill.variable ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
          <label class="text-telemetry-micro text-outline">Priority<select id="wo-f-prio" class="input w-full mt-1">${['high', 'medium', 'low'].map((p) => `<option ${p === (prefill.priority || 'medium') ? 'selected' : ''}>${p}</option>`).join('')}</select></label>
        </div>
        <label class="text-telemetry-micro text-outline">Assigned to<input id="wo-f-assignee" class="input w-full mt-1" placeholder="Field team or technician" value="${WF.esc(prefill.assignee || '')}"></label>
        <label class="text-telemetry-micro text-outline">Description<textarea id="wo-f-desc" class="input w-full mt-1 h-24">${WF.esc(prefill.description || '')}</textarea></label>
        <div class="flex justify-end gap-2 pt-2 border-t border-surface-container-highest">
          <button class="act-btn" onclick="WF.closeModal()">Cancel</button>
          <button class="act-btn act-primary" id="wo-f-save">Create</button>
        </div>
      </div>`);
    document.getElementById('wo-f-save').onclick = () => {
      const wo = WF.wo.add({
        station_id: document.getElementById('wo-f-station').value,
        variable: document.getElementById('wo-f-var').value,
        priority: document.getElementById('wo-f-prio').value,
        assignee: document.getElementById('wo-f-assignee').value.trim(),
        description: document.getElementById('wo-f-desc').value.trim(),
        incident_id: prefill.incident_id || null,
      });
      WF.closeModal();
      WF.beep('ok');
      WF.toast('Work order created', `${wo.id} · ${WF.stationName(wo.station_id)}`, 'primary');
    };
  };

  /* ---------- global search ---------- */
  function setupSearch() {
    const input = document.getElementById('global-search-input');
    const dd = document.getElementById('search-results-dropdown');
    input.addEventListener('input', () => {
      const q = input.value.trim().toLowerCase();
      if (!q) { dd.classList.add('hidden'); return; }
      const hits = WF.state.stations.filter((s) => `${s.name} ${s.id}`.toLowerCase().includes(q)).slice(0, 12);
      dd.innerHTML = hits.length ? hits.map((s) => `
        <button data-id="${WF.esc(s.id)}" class="w-full text-left px-space-sm py-1.5 hover:bg-surface-bright flex items-center justify-between text-telemetry-micro">
          <span><strong class="text-on-surface">${WF.esc(s.name)}</strong> <span class="text-outline">${WF.esc(s.id)}</span></span>${WF.statusBadge(WF.stationStatus(s))}
        </button>`).join('') : '<div class="px-space-sm py-2 text-telemetry-micro text-outline">No station matches.</div>';
      dd.classList.remove('hidden');
    });
    dd.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-id]');
      if (!b) return;
      dd.classList.add('hidden');
      input.value = '';
      WF.go('stations', b.dataset.id);
    });
    document.addEventListener('click', (e) => { if (!dd.contains(e.target) && e.target !== input) dd.classList.add('hidden'); });
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') { e.preventDefault(); input.focus(); }
      if (e.key === 'Escape') { dd.classList.add('hidden'); WF.closeModal(); WF.emit('escape'); }
    });
  }

  WF.start = function () {
    setupSearch();
    document.getElementById('audio-toggle-btn').addEventListener('click', () => {
      WF.state.audio = !WF.state.audio;
      document.getElementById('audio-icon').textContent = WF.state.audio ? 'volume_up' : 'volume_off';
      WF.beep('click');
    });
    document.getElementById('modal').addEventListener('click', (e) => { if (e.target.id === 'modal') WF.closeModal(); });
    window.addEventListener('hashchange', () => WF.go(location.hash.slice(1)));
    tickWallClock();
    setInterval(tickWallClock, 1000);
    WF.go(location.hash.slice(1) || 'overview');
    const poll = () => WF.refresh().catch(() => {});
    poll();
    setInterval(poll, 3000);
    refreshSlow();
    setInterval(refreshSlow, 10000);
    connectWs();
  };
})();
