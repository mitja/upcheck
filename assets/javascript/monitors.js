import Chart from 'chart.js/auto';

const REFRESH_MS = 60_000;

async function fetchResults(dataUrl) {
  const response = await fetch(dataUrl, { headers: { 'Accept': 'application/json' } });
  if (!response.ok) throw new Error(`chart data request failed: ${response.status}`);
  const payload = await response.json();
  return payload.results;
}

function toChartData(results) {
  return {
    labels: results.map((r) => new Date(r.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })),
    datasets: [
      {
        label: 'response time (ms)',
        data: results.map((r) => r.ms),
        pointRadius: results.map((r) => (r.ok ? 0 : 4)),
        pointBackgroundColor: results.map((r) => (r.ok ? 'transparent' : '#e5484d')),
        borderWidth: 2,
        tension: 0.3,
        fill: false,
      },
    ],
  };
}

export async function renderMonitorChart(canvasId, dataUrl) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const chart = new Chart(canvas, {
    type: 'line',
    data: toChartData([]),
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: 'ms' } },
        x: { ticks: { maxTicksLimit: 12 } },
      },
    },
  });

  async function refresh() {
    try {
      const results = await fetchResults(dataUrl);
      chart.data = toChartData(results);
      chart.update();
    } catch (e) {
      console.error(e);
    }
  }

  await refresh();
  setInterval(refresh, REFRESH_MS);
}

// Match the boilerplate's SiteJS global convention (see app.js).
if (typeof window.SiteJS === 'undefined') {
  window.SiteJS = {};
}
window.SiteJS.monitors = { renderMonitorChart };
