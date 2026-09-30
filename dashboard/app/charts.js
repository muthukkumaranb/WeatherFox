/* Time-series charts (Chart.js, vendored). Observed values, the model's corrected estimate, and flagged points. */
(function () {
  'use strict';
  const WF = window.WF;
  const charts = new WeakMap();
  const COLORS = { anomaly: '#ffb4ab', uncertain: '#ffb690', genuine: '#c0c1ff' };

  Chart.defaults.color = '#86948a';
  Chart.defaults.font.family = "'Space Mono', monospace";
  Chart.defaults.font.size = 10;
  Chart.defaults.animation = false;

  /* series: rows from /stations/{id}/series. opts: { highlightFrom, highlightTo, height } */
  WF.drawSeries = function (canvas, series, variable, opts = {}) {
    if (!canvas) return;
    const old = charts.get(canvas);
    if (old) old.destroy();
    const labels = series.map((r) => r.ts_utc);
    const obs = series.map((r) => (r[variable] ?? null));
    const corr = series.map((r) => (r[`corrected_${variable}`] ?? null));
    const pointColor = series.map((r) => (r.genuine_event ? COLORS.genuine : COLORS[r.label] || 'rgba(0,0,0,0)'));
    const pointRadius = series.map((r) => (r.genuine_event || r.label === 'anomaly' || r.label === 'uncertain' ? 3.5 : 0));
    const inWindow = (ts) => opts.highlightFrom && ts >= opts.highlightFrom && ts <= (opts.highlightTo || opts.highlightFrom);
    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: `Observed ${variable}`, data: obs, borderColor: '#4edea3', borderWidth: 1.6, tension: 0.2, spanGaps: false,
            pointBackgroundColor: pointColor, pointBorderColor: pointColor, pointRadius,
            segment: { borderColor: (ctx) => (inWindow(labels[ctx.p1DataIndex]) ? (opts.highlightColor || '#ffb4ab') : undefined) },
          },
          { label: 'Model estimate (corrected)', data: corr, borderColor: '#c0c1ff', borderDash: [4, 3], borderWidth: 1.2, pointRadius: 0, spanGaps: true },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: opts.legend !== false, labels: { boxWidth: 10, boxHeight: 2 } },
          tooltip: {
            callbacks: {
              title: (items) => WF.fmtTs(labels[items[0].dataIndex]),
              afterBody: (items) => {
                const r = series[items[0].dataIndex];
                const tags = [r.label && r.label !== 'normal' ? `verdict: ${r.label}` : null, r.injected ? 'injected in simulation' : null, r.simulated_event ? 'simulated weather event' : null, r.genuine_event ? 'scorer: real weather' : null].filter(Boolean);
                return tags.join(' · ');
              },
            },
          },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 7, maxRotation: 0, autoSkip: true, callback: (v, i) => (labels[i] ? `${labels[i].slice(8, 10)}/${labels[i].slice(5, 7)} ${labels[i].slice(11, 13)}h` : '') }, grid: { color: 'rgba(60,74,66,0.25)' } },
          y: { title: { display: true, text: WF.UNIT[variable] }, grid: { color: 'rgba(60,74,66,0.25)' } },
        },
      },
    });
    charts.set(canvas, chart);
  };
})();
