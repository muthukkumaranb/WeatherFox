/* India map drawn from the vendored DataMeet state boundaries (vendor/india_states.geojson).
 * Equirectangular projection with cos(latitude) scaling; stations are placed at their real lat/lon. */
(function () {
  'use strict';
  const WF = window.WF;
  const NS = 'http://www.w3.org/2000/svg';
  const BBOX = { lonMin: 67.5, lonMax: 98.0, latMin: 6.0, latMax: 37.5 };
  const K = Math.cos((22 * Math.PI) / 180); // shrink longitude at India's mid-latitude
  const W = (BBOX.lonMax - BBOX.lonMin) * K * 100;
  const H = (BBOX.latMax - BBOX.latMin) * 100;
  const project = (lon, lat) => [(lon - BBOX.lonMin) * K * 100, (BBOX.latMax - lat) * 100];

  const view = { k: 1, x: 0, y: 0 };
  let svg, vp, gStations, onPick = () => {}, lastStations = [];

  function ringPath(ring) {
    return ring.map(([lon, lat], i) => { const [x, y] = project(lon, lat); return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`; }).join('') + 'Z';
  }

  async function drawStates() {
    const g = document.getElementById('map-states');
    try {
      const gj = await fetch('vendor/india_states.geojson').then((r) => r.json());
      g.innerHTML = gj.features.map((f) => {
        const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
        const d = polys.map((p) => p.map(ringPath).join('')).join('');
        return `<path d="${d}" fill="#151b2a" stroke="#2e3544" stroke-width="${1.2}" vector-effect="non-scaling-stroke"><title>${WF.esc(f.properties.name || '')}</title></path>`;
      }).join('');
    } catch (e) {
      g.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="#86948a" font-size="60" text-anchor="middle">Map outline not available</text>`;
    }
  }

  // Map units per screen pixel at zoom 1 (the viewBox is ~3000 units wide, the SVG a few hundred pixels).
  function unitsPerPx() {
    const ctm = svg && svg.getScreenCTM();
    return ctm && ctm.a ? 1 / ctm.a : W / 800;
  }
  // Marker radius given in screen pixels, independent of zoom and window size.
  const rUnits = (px) => ((px * unitsPerPx()) / view.k).toFixed(2);

  function applyView() {
    vp.setAttribute('transform', `translate(${view.x},${view.y}) scale(${view.k})`);
    gStations.querySelectorAll('circle').forEach((c) => c.setAttribute('r', rUnits(Number(c.dataset.r))));
  }

  function setupZoomPan() {
    const zoomAt = (factor, cx = W / 2, cy = H / 2) => {
      const k2 = Math.min(8, Math.max(1, view.k * factor));
      view.x = cx - ((cx - view.x) * k2) / view.k;
      view.y = cy - ((cy - view.y) * k2) / view.k;
      view.k = k2;
      if (view.k === 1) { view.x = 0; view.y = 0; }
      applyView();
    };
    document.getElementById('map-zoom-in').onclick = () => zoomAt(1.5);
    document.getElementById('map-zoom-out').onclick = () => zoomAt(1 / 1.5);
    document.getElementById('map-reset-zoom').onclick = () => { view.k = 1; view.x = 0; view.y = 0; applyView(); };
    const toSvg = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
    svg.addEventListener('wheel', (e) => { e.preventDefault(); const p = toSvg(e); zoomAt(e.deltaY < 0 ? 1.25 : 0.8, p.x, p.y); }, { passive: false });
    let drag = null;
    svg.addEventListener('mousedown', (e) => { if (e.target.closest('.st-dot')) return; drag = { p: toSvg(e), x: view.x, y: view.y }; svg.classList.add('dragging'); });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      const p = toSvg(e);
      view.x = drag.x + (p.x - drag.p.x); view.y = drag.y + (p.y - drag.p.y);
      drag.p = p; drag.x = view.x; drag.y = view.y;
      applyView();
    });
    window.addEventListener('mouseup', () => { drag = null; svg.classList.remove('dragging'); });
  }

  function tooltip(s, e, variable) {
    const tt = document.getElementById('map-tooltip');
    if (!s) { tt.classList.add('hidden'); return; }
    const st = WF.stationStatus(s);
    const m = WF.STATUS_META[st];
    const flagged = (s.flagged_vars || []).map((f) => `${f.variable}: ${WF.cause(f.root_cause)}`).join(', ');
    tt.innerHTML = `<div class="font-label-mono-bold text-on-surface">${WF.esc(s.name)} <span class="text-outline">${WF.esc(s.id)}</span></div>
      <div class="${m.text}">${m.label}${flagged ? ' · ' + WF.esc(flagged) : ''}</div>
      <div class="text-on-surface-variant">${WF.VARNAME[variable]}: ${WF.fmt(s.latest && s.latest[variable], variable)}</div>
      <div class="text-outline">${WF.fmtTs(s.latest_ts)}</div>`;
    const box = document.getElementById('map-wrap').getBoundingClientRect();
    tt.style.left = `${Math.min(e.clientX - box.left + 14, box.width - 230)}px`;
    tt.style.top = `${Math.max(e.clientY - box.top - 70, 4)}px`;
    tt.classList.remove('hidden');
  }

  WF.map = {
    async init(pick) {
      onPick = pick;
      svg = document.getElementById('india-map-svg');
      vp = document.getElementById('map-viewport');
      gStations = document.getElementById('map-stations');
      svg.setAttribute('viewBox', `0 0 ${W.toFixed(0)} ${H.toFixed(0)}`);
      svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      setupZoomPan();
      window.addEventListener('resize', applyView);
      await drawStates();
      gStations.addEventListener('click', (e) => { const c = e.target.closest('[data-id]'); if (c) onPick(c.dataset.id); });
      gStations.addEventListener('mousemove', (e) => {
        const c = e.target.closest('[data-id]');
        tooltip(c ? WF.stationById(c.dataset.id) : null, e, WF.map.variable || 'T');
      });
      gStations.addEventListener('mouseleave', () => tooltip(null));
    },
    variable: 'T',
    render(stations) {
      lastStations = stations;
      // draw calm stations first so flagged ones sit on top
      const order = stations.slice().sort((a, b) => WF.STATUS_META[WF.stationStatus(b)].rank - WF.STATUS_META[WF.stationStatus(a)].rank);
      gStations.innerHTML = order.filter((s) => s.lat != null && s.lon != null).map((s) => {
        const st = WF.stationStatus(s);
        const m = WF.STATUS_META[st];
        const [x, y] = project(s.lon, s.lat);
        const r = st === 'anomaly' || st === 'uncertain' ? 6 : st === 'genuine' ? 5.5 : 4;
        const pulse = st === 'anomaly' ? `<circle class="st-pulse" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rUnits(r)}" data-r="${r}" fill="${m.color}" pointer-events="none"></circle>` : '';
        const ring = s.simulated_event ? `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rUnits(r + 4)}" data-r="${r + 4}" fill="none" stroke="#c0c1ff" stroke-dasharray="2 2" stroke-width="1" vector-effect="non-scaling-stroke" pointer-events="none"></circle>` : '';
        return `<g data-id="${WF.esc(s.id)}">${pulse}${ring}<circle class="st-dot" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rUnits(r)}" data-r="${r}" fill="${m.color}" stroke="#0c1321" stroke-width="1" vector-effect="non-scaling-stroke"></circle></g>`;
      }).join('');
    },
    rerender() { WF.map.render(lastStations); },
  };
})();
