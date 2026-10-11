/* ═══════════════════════════════════════════════════════════════
   YANTRA — Dashboard JS  (single file, no duplicate declarations)
═══════════════════════════════════════════════════════════════ */

// ── Helpers ──────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const srcClass = src => ({ YANTRA:'yantra', VOICE:'voice', USER:'user',
  AGENT:'agent', TOOL:'tool', STT:'stt', MEMORY:'memory' }[src] || 'yantra');

// ── Socket ────────────────────────────────────────────────────────
const socket = io({ transports: ['websocket', 'polling'] });
let geminiReady = false;
let liveErrorStatus = '';

socket.on('connect',    () => console.log('[YANTRA] Socket connected:', socket.id));
socket.on('disconnect', () => console.warn('[YANTRA] Socket disconnected'));
socket.on('connect_error', e => console.error('[YANTRA] Socket error:', e.message));

socket.on('assistant_config', config => {
  geminiReady = Boolean(config.gemini_ready);
  $('badge-gemini').textContent = config.gemini_ready ? 'GEMINI LIVE' : 'GEMINI OFF';
  $('badge-gemini').title = config.live_model || 'Gemini Live';
  liveErrorStatus = '';
  $('status-gemini').textContent = config.gemini_ready ? 'CONFIGURED' : 'OFFLINE';
  $('status-gemini').classList.remove('online');
  $('badge-groq').textContent = config.groq_ready ? 'GROQ FALLBACK' : 'GROQ OFF';
  $('status-groq').textContent = config.groq_ready ? 'READY' : 'NOT CONFIGURED';
  $('status-groq').classList.toggle('online', Boolean(config.groq_ready));
  $('badge-tools').textContent = `${config.tool_count || 0} TOOLS`;
  if (localStorage.getItem('yantra_auto_listen') === 'true' && config.gemini_ready && !voiceOn) {
    socket.emit('start_voice');
  }
  if (!config.assistant_ready) {
    appendLog({ time:ts(), source:'YANTRA', tag:'[CONFIG]',
      message:'Add GEMINI_API_KEY or GROQ_API_KEY to backend/.env to enable assistant responses.' });
  }
});

socket.on('assistant_error', ({ message }) => {
  if (/Gemini Live quota is exhausted/i.test(message)) {
    liveErrorStatus = 'QUOTA EXCEEDED';
    $('status-gemini').textContent = liveErrorStatus;
    $('status-gemini').classList.remove('online');
  }
  showAssistantResponse(message, [], false);
});

socket.on('voice_state', ({ active }) => {
  voiceOn = active;
  $('btn-mic').classList.toggle('active', active);
  $('btn-mic').textContent = active ? '🎤 MICROPHONE ACTIVE ▶▶' : '🎤 MICROPHONE READY';
  $('tog-voice').checked = active;
  if (!active && !liveErrorStatus) {
    $('status-gemini').textContent = geminiReady ? 'CONFIGURED' : 'OFFLINE';
    $('status-gemini').classList.remove('online');
  }
});

// ═══════════════════════════════════════════════════════════════
// CORE RING — full Canvas renderer
// ═══════════════════════════════════════════════════════════════
const coreCanvas = $('core-canvas');
const coreCtx    = coreCanvas.getContext('2d');
const CSIZE = 280;
coreCanvas.width  = CSIZE;
coreCanvas.height = CSIZE;
const CX = CSIZE / 2, CY = CSIZE / 2;
let coreAngle = 0;
let coreState = 'READY';
let voiceLevel = 0;

function arc(r, startDeg, endDeg, color, lw, glow) {
  const s = (startDeg - 90) * Math.PI / 180;
  const e = (endDeg   - 90) * Math.PI / 180;
  coreCtx.beginPath();
  coreCtx.arc(CX, CY, r, s, e);
  coreCtx.strokeStyle = color;
  coreCtx.lineWidth   = lw;
  coreCtx.shadowColor = glow ? color : 'transparent';
  coreCtx.shadowBlur  = glow || 0;
  coreCtx.stroke();
  coreCtx.shadowBlur  = 0;
}

function drawTicks(r, count, majorEvery, offset, color, dimColor) {
  for (let i = 0; i < count; i++) {
    const deg = (i / count) * 360 + offset;
    const rad = (deg - 90) * Math.PI / 180;
    const isMajor = i % majorEvery === 0;
    const len = isMajor ? 7 : 3;
    coreCtx.beginPath();
    coreCtx.moveTo(CX + (r - len) * Math.cos(rad), CY + (r - len) * Math.sin(rad));
    coreCtx.lineTo(CX + r * Math.cos(rad),          CY + r * Math.sin(rad));
    coreCtx.strokeStyle = isMajor ? color : dimColor;
    coreCtx.lineWidth   = isMajor ? 1.2 : 0.6;
    coreCtx.shadowBlur  = 0;
    coreCtx.stroke();
  }
}

function drawLabels(r, labels, offset) {
  coreCtx.font          = '7px "Share Tech Mono", monospace';
  coreCtx.fillStyle     = 'rgba(0,229,255,0.6)';
  coreCtx.textAlign     = 'center';
  coreCtx.textBaseline  = 'middle';
  coreCtx.shadowBlur    = 0;
  labels.forEach(({ val, deg }) => {
    const rad = (deg + offset - 90) * Math.PI / 180;
    coreCtx.fillText(val, CX + (r + 11) * Math.cos(rad), CY + (r + 11) * Math.sin(rad));
  });
}

function drawOrangeSegs(r, lw, segs, angle) {
  segs.forEach(([s, e]) => arc(r, s + angle, e + angle, '#ff9800', lw, 8));
}

function drawCrosshair(inner, outer) {
  coreCtx.strokeStyle = 'rgba(0,229,255,0.3)';
  coreCtx.lineWidth   = 0.8;
  coreCtx.shadowBlur  = 0;
  coreCtx.setLineDash([4, 6]);
  [[CX, CY - outer, CX, CY - inner],
   [CX, CY + inner, CX, CY + outer],
   [CX - outer, CY, CX - inner, CY],
   [CX + inner, CY, CX + outer, CY]].forEach(([x1,y1,x2,y2]) => {
    coreCtx.beginPath(); coreCtx.moveTo(x1,y1); coreCtx.lineTo(x2,y2); coreCtx.stroke();
  });
  coreCtx.setLineDash([]);
}

function drawFineTrack(r, count, offset) {
  for (let i = 0; i < count; i++) {
    const deg = (i / count) * 360 + offset;
    const rad = (deg - 90) * Math.PI / 180;
    const major = i % 18 === 0;
    const medium = i % 3 === 0;
    const len = major ? 6 : medium ? 3 : 1.5;
    coreCtx.beginPath();
    coreCtx.moveTo(CX + (r - len) * Math.cos(rad), CY + (r - len) * Math.sin(rad));
    coreCtx.lineTo(CX + r * Math.cos(rad), CY + r * Math.sin(rad));
    coreCtx.strokeStyle = major ? 'rgba(0,229,255,0.9)' : medium
      ? 'rgba(0,188,212,0.5)' : 'rgba(0,150,180,0.24)';
    coreCtx.lineWidth = major ? 1 : 0.55;
    coreCtx.stroke();
  }
}

function drawSweep(angle) {
  const start = (angle - 90) * Math.PI / 180;
  const end = start + 0.42;
  const gradient = coreCtx.createRadialGradient(CX, CY, 18, CX, CY, 132);
  gradient.addColorStop(0, 'rgba(0,229,255,0.12)');
  gradient.addColorStop(1, 'rgba(0,229,255,0)');
  coreCtx.beginPath();
  coreCtx.moveTo(CX, CY);
  coreCtx.arc(CX, CY, 132, start, end);
  coreCtx.closePath();
  coreCtx.fillStyle = gradient;
  coreCtx.fill();
}

function drawOrbitNodes(angle) {
  for (let i = 0; i < 24; i++) {
    const deg = (i / 24) * 360 + angle * (i % 2 ? -0.25 : 0.18);
    const rad = (deg - 90) * Math.PI / 180;
    const radius = i % 3 === 0 ? 116 : i % 3 === 1 ? 102 : 78;
    const size = i % 6 === 0 ? 2.2 : 1.1;
    const x = CX + radius * Math.cos(rad);
    const y = CY + radius * Math.sin(rad);
    coreCtx.beginPath();
    coreCtx.arc(x, y, size, 0, Math.PI * 2);
    coreCtx.fillStyle = i % 6 === 0 ? 'rgba(0,255,255,0.95)' : 'rgba(0,188,212,0.65)';
    coreCtx.shadowColor = '#00e5ff';
    coreCtx.shadowBlur = i % 6 === 0 ? 9 : 3;
    coreCtx.fill();
    coreCtx.shadowBlur = 0;
  }
}

function drawCentralCore() {
  const gradient = coreCtx.createRadialGradient(CX - 8, CY - 10, 2, CX, CY, 50);
  gradient.addColorStop(0, 'rgba(11,75,103,0.9)');
  gradient.addColorStop(0.58, 'rgba(2,35,57,0.86)');
  gradient.addColorStop(1, 'rgba(0,12,25,0.92)');
  coreCtx.beginPath();
  coreCtx.arc(CX, CY, 49, 0, Math.PI * 2);
  coreCtx.fillStyle = gradient;
  coreCtx.fill();
  arc(49, 0, 360, 'rgba(0,229,255,0.72)', 1.2, 9);
  arc(44, 0, 360, 'rgba(0,188,212,0.35)', 0.7, 3);

  for (let i = 0; i < 48; i++) {
    const deg = i * 7.5;
    const rad = (deg - 90) * Math.PI / 180;
    const inner = i % 4 === 0 ? 39 : 42;
    coreCtx.beginPath();
    coreCtx.moveTo(CX + inner * Math.cos(rad), CY + inner * Math.sin(rad));
    coreCtx.lineTo(CX + 45 * Math.cos(rad), CY + 45 * Math.sin(rad));
    coreCtx.strokeStyle = i % 4 === 0 ? 'rgba(0,229,255,0.85)' : 'rgba(0,188,212,0.35)';
    coreCtx.lineWidth = i % 4 === 0 ? 0.8 : 0.45;
    coreCtx.stroke();
  }
}

function drawGlow() {
  const glowRadius = 72 + voiceLevel * 28;
  const [c1, c2] = coreState === 'THINKING'
    ? ['rgba(255,152,0,0.45)',  'rgba(255,152,0,0.0)']
    : coreState === 'SPEAKING'
    ? ['rgba(0,255,136,0.4)',   'rgba(0,255,136,0.0)']
    : ['rgba(0,180,255,0.5)',   'rgba(0,80,150,0.0)'];
  const g = coreCtx.createRadialGradient(CX, CY, 0, CX, CY, glowRadius);
  g.addColorStop(0,    'rgba(255,255,255,0.6)');
  g.addColorStop(0.12, c1);
  g.addColorStop(1,    c2);
  coreCtx.beginPath();
  coreCtx.arc(CX, CY, glowRadius, 0, Math.PI * 2);
  coreCtx.fillStyle  = g;
  coreCtx.shadowBlur = 0;
  coreCtx.fill();
}

const outerLabels = [
  { val:'350',   deg:0   },
  { val:'225',   deg:72  },
  { val:'110',   deg:144 },
  { val:'220',   deg:216 },
  { val:'360',   deg:288 },
];

function drawCore() {
  coreCtx.clearRect(0, 0, CSIZE, CSIZE);
  const a = coreAngle;

  drawSweep(a * 0.7);

  arc(136, 0, 360, 'rgba(0,229,255,0.18)', 1, 0);
  drawTicks(136, 72, 9, a * 0.3, 'rgba(0,229,255,0.8)', 'rgba(0,150,180,0.4)');
  drawFineTrack(131, 216, -a * 0.22);
  drawLabels(136, outerLabels, a * 0.3);

  arc(122, 0, 360, 'rgba(0,229,255,0.22)', 1.2, 4);
  drawTicks(122, 48, 6, -a * 0.5, 'rgba(0,229,255,0.6)', 'rgba(0,120,160,0.3)');
  drawOrangeSegs(122, 3.5, [[20,55],[200,230],[290,320]], -a * 0.5);

  arc(108, 0, 360, 'rgba(0,188,212,0.15)', 1, 0);
  arc(108, a,       a + 80,  'rgba(0,229,255,0.55)', 2.5, 8);
  arc(108, a + 180, a + 240, 'rgba(0,188,212,0.4)',  1.5, 4);
  drawTicks(108, 36, 4, a * 0.8, 'rgba(0,229,255,0.5)', 'rgba(0,100,140,0.3)');
  drawFineTrack(113, 144, a * 0.16);

  arc(94, 0, 360, 'rgba(0,229,255,0.2)', 1, 0);
  arc(94, -a + 30,  -a + 100, '#00e5ff', 2.2, 10);
  arc(94, -a + 200, -a + 250, 'rgba(0,188,212,0.5)', 1.5, 5);
  drawOrangeSegs(94, 2.5, [[90,115],[260,285]], -a * 0.7);
  drawTicks(94, 24, 3, -a, 'rgba(0,229,255,0.45)', 'rgba(0,80,120,0.3)');

  arc(80, 0, 360, 'rgba(0,229,255,0.15)', 0.8, 0);
  arc(80, a * 1.2,       a * 1.2 + 60,  'rgba(0,229,255,0.7)', 2,   8);
  arc(80, a * 1.2 + 130, a * 1.2 + 170, '#00ff88',             1.8, 6);
  drawTicks(80, 60, 10, a * 1.2, 'rgba(0,229,255,0.4)', 'rgba(0,80,100,0.25)');

  arc(68, 0, 360, 'rgba(0,188,212,0.12)', 0.8, 0);
  arc(68, -a * 0.9, -a * 0.9 + 90, 'rgba(0,188,212,0.5)', 1.5, 5);

  arc(56, 0, 360, 'rgba(0,229,255,0.25)', 1, 0);
  arc(56, a * 1.5,  a * 1.5 + 120, 'rgba(0,229,255,0.4)', 1.2, 4);

  drawCrosshair(58, 132);
  drawOrbitNodes(a);
  drawGlow();
  drawCentralCore();

  coreAngle += 0.3;
  requestAnimationFrame(drawCore);
}
drawCore();

// ═══════════════════════════════════════════════════════════════
// CLOCK
// ═══════════════════════════════════════════════════════════════
function updateClock() {
  const now = new Date();
  const h = now.getHours(), m = now.getMinutes(), s = now.getSeconds();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const hh = String(h % 12 || 12).padStart(2,'0');
  $('clock').textContent =
    `${hh}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')} ${ampm}`;
  const days   = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
  const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  $('date-display').textContent =
    `${days[now.getDay()]}, ${String(now.getDate()).padStart(2,'0')} ${months[now.getMonth()]} ${now.getFullYear()}`;
}
setInterval(updateClock, 1000);
updateClock();

// ═══════════════════════════════════════════════════════════════
// SPARKLINE CHARTS (Chart.js)
// ═══════════════════════════════════════════════════════════════
function makeSparkline(canvasId, color) {
  const ctx = $(canvasId).getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: Array(60).fill(''),
      datasets: [{ data: Array(60).fill(0), borderColor: color, borderWidth: 1.2,
        fill: true, backgroundColor: color.replace('rgb','rgba').replace(')',',0.1)'),
        pointRadius: 0, tension: 0.4 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display:false }, tooltip: { enabled:false } },
      scales: { x: { display:false }, y: { display:false, min:0, max:100 } }
    }
  });
}

const sparkCPU = makeSparkline('spark-cpu', 'rgb(0,229,255)');
const sparkRAM = makeSparkline('spark-ram', 'rgb(255,152,0)');
const sparkGPU = makeSparkline('spark-gpu', 'rgb(179,136,255)');
const sparkNET = makeSparkline('spark-net', 'rgb(0,255,136)');

function pushSparkline(chart, val) {
  chart.data.datasets[0].data.push(val);
  chart.data.datasets[0].data.shift();
  chart.update('none');
}

// ── Real-time multi-line chart ────────────────────────────────────
const rtChart = new Chart($('rt-chart').getContext('2d'), {
  type: 'line',
  data: {
    labels: Array(60).fill(''),
    datasets: [
      { data: Array(60).fill(0), borderColor:'rgb(0,229,255)',  borderWidth:1.2, pointRadius:0, tension:0.4, fill:false },
      { data: Array(60).fill(0), borderColor:'rgb(255,152,0)',  borderWidth:1.2, pointRadius:0, tension:0.4, fill:false },
      { data: Array(60).fill(0), borderColor:'rgb(0,255,136)',  borderWidth:1.2, pointRadius:0, tension:0.4, fill:false },
      { data: Array(60).fill(0), borderColor:'rgb(179,136,255)',borderWidth:1.2, pointRadius:0, tension:0.4, fill:false },
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display:false }, tooltip: { enabled:false } },
    scales: { x: { display:false }, y: { display:false, min:0, max:100 } }
  }
});

function pushRT(cpu, ram, net, gpu) {
  [cpu, ram, net, gpu].forEach((v, i) => {
    rtChart.data.datasets[i].data.push(Math.min(v, 100));
    rtChart.data.datasets[i].data.shift();
  });
  rtChart.update('none');
}

// ── Memory doughnut ───────────────────────────────────────────────
const memRingChart = new Chart($('mem-ring-short').getContext('2d'), {
  type: 'doughnut',
  data: { datasets: [{ data:[0,100], backgroundColor:['rgb(0,229,255)','rgb(5,30,51)'], borderWidth:0 }] },
  options: { responsive:false, animation:false, cutout:'70%',
    plugins: { legend:{display:false}, tooltip:{enabled:false} } }
});

// ═══════════════════════════════════════════════════════════════
// WAVEFORM
// ═══════════════════════════════════════════════════════════════
const wvCanvas = $('waveform-canvas');
const wvCtx    = wvCanvas.getContext('2d');
let waveActive = false, wavePhase = 0;
let microphoneAnalyser = null;
let microphoneStream = null;
let microphoneData = null;

async function startMicrophoneVisualizer() {
  if (!navigator.mediaDevices?.getUserMedia) return;
  try {
    microphoneStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(microphoneStream);
    microphoneAnalyser = audioContext.createAnalyser();
    microphoneAnalyser.fftSize = 256;
    source.connect(microphoneAnalyser);
    microphoneData = new Uint8Array(microphoneAnalyser.frequencyBinCount);
  } catch (error) {
    console.warn('[YANTRA] Microphone visualization unavailable:', error.message);
  }
}

function stopMicrophoneVisualizer() {
  microphoneStream?.getTracks().forEach(track => track.stop());
  microphoneStream = null;
  microphoneAnalyser = null;
  microphoneData = null;
}

function drawWaveform() {
  const W = wvCanvas.width  = wvCanvas.offsetWidth  || 300;
  const H = wvCanvas.height = wvCanvas.offsetHeight || 46;
  wvCtx.clearRect(0, 0, W, H);
  const mid = H / 2;
  if (waveActive && microphoneAnalyser && microphoneData) {
    microphoneAnalyser.getByteFrequencyData(microphoneData);
    const barWidth = W / microphoneData.length;
    let frequencyTotal = 0;
    for (let i = 0; i < microphoneData.length; i++) {
      const barHeight = (microphoneData[i] / 255) * (H * 0.86);
      const x = i * barWidth;
      frequencyTotal += microphoneData[i];
      wvCtx.fillStyle = `rgba(0, ${150 + Math.round(microphoneData[i] * 0.4)}, 255, 0.85)`;
      wvCtx.fillRect(x, mid - barHeight / 2, Math.max(1, barWidth - 1), barHeight);
    }
    voiceLevel = Math.min(frequencyTotal / microphoneData.length / 100, 1);
  } else {
    voiceLevel *= 0.9;
    wvCtx.beginPath();
    wvCtx.strokeStyle = waveActive ? '#00ff88' : '#006080';
    wvCtx.lineWidth   = 1.5;
    for (let x = 0; x < W; x++) {
      const amp = waveActive ? 5 : 2;
      const y = mid + Math.sin((x / W) * Math.PI * 8 + wavePhase) * amp;
      x === 0 ? wvCtx.moveTo(x, y) : wvCtx.lineTo(x, y);
    }
    wvCtx.stroke();
  }
  wavePhase += waveActive ? 0.15 : 0.03;
  requestAnimationFrame(drawWaveform);
}
drawWaveform();

// ═══════════════════════════════════════════════════════════════
// SOCKET EVENT HANDLERS — live data
// ═══════════════════════════════════════════════════════════════
socket.on('metrics', data => {
  // CPU
  $('cpu-pct').textContent  = data.cpu.toFixed(0) + '%';
  pushSparkline(sparkCPU, data.cpu);
  // RAM
  $('ram-pct').textContent  = data.ram.toFixed(0) + '%';
  $('ram-info').textContent = `${data.ram_used} / ${data.ram_total} GB`;
  pushSparkline(sparkRAM, data.ram);
  // Disk
  $('disk-pct').textContent  = data.disk.toFixed(0) + '%';
  $('disk-info').textContent = `${data.disk_used} / ${data.disk_total} GB`;
  // Net
  const netPct = Math.min(data.net * 10, 100);
  $('net-pct').textContent  = data.net + ' MB/s';
  $('net-info').textContent = `↓ ${data.net} MB/s`;
  pushSparkline(sparkNET, netPct);
  // GPU (no GPU lib, stays 0)
  pushSparkline(sparkGPU, 0);
  // RT chart
  pushRT(data.cpu, data.ram, netPct, 0);
  // System info
  $('si-uptime').textContent = data.uptime;
  $('si-os').textContent     = data.platform;
  $('si-arch').textContent   = data.arch;
  // Connections (live count from psutil)
  $('net-conns').textContent = data.net_conns || '—';
  // Memory ring
  memRingChart.data.datasets[0].data = [data.ram, 100 - data.ram];
  memRingChart.update('none');
  $('mem-short-val').textContent = data.mem_short + ' MB';
  $('mem-short').textContent     = data.mem_short + ' MB';
  $('mem-long').textContent      = data.mem_long  + ' MB';
  // Processes
  renderProcesses(data.processes || []);
});

socket.on('activity_log',     entry   => appendLog(entry));
socket.on('activity_history', entries => {
  $('log-body').innerHTML = '';
  entries.forEach(appendLog);
});

socket.on('status_update', ({ status: s }) => {
  coreState = s;
  $('status-label').textContent = s;
  $('core-sub').textContent = s === 'READY' ? 'AI CORE ONLINE' : s + '...';
  $('core-ring').className  = 'core-overlay' + (s === 'THINKING' ? ' thinking' : s === 'SPEAKING' ? ' speaking' : '');
  $('wave-label').textContent = s;
  if (voiceOn && ['CONNECTING', 'CONNECTED', 'LISTENING', 'THINKING', 'SPEAKING', 'INTERRUPTED', 'RECONNECTING'].includes(s)) {
    liveErrorStatus = '';
    $('status-gemini').textContent = s;
    $('status-gemini').classList.toggle('online', ['CONNECTED', 'LISTENING', 'SPEAKING'].includes(s));
  }
});

socket.on('waveform_active', ({ active }) => {
  waveActive = active;
  $('wave-label').textContent = active ? 'LISTENING...' : 'STANDBY';
  if (active) startMicrophoneVisualizer();
  else stopMicrophoneVisualizer();
});

socket.on('agent_response', ({ text, sources = [], success = true }) => {
  showAssistantResponse(text, sources, success);
});

function showAssistantResponse(text, sources, success) {
  const box = $('agent-response-box');
  box.style.display = 'block';
  box.classList.toggle('response-error', !success);
  const answer = document.createElement('div');
  answer.className = 'response-text';
  answer.textContent = text || 'No response received.';
  box.replaceChildren(answer);
  if (sources.length) {
    const sourceList = document.createElement('div');
    sourceList.className = 'response-sources';
    const label = document.createElement('span');
    label.textContent = 'SOURCES';
    sourceList.appendChild(label);
    sources.forEach(source => {
      try {
        const url = new URL(source.url);
        if (!['https:', 'http:'].includes(url.protocol)) return;
        const link = document.createElement('a');
        link.href = url.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = source.title || url.hostname;
        sourceList.appendChild(link);
      } catch (_) {
        return;
      }
    });
    if (sourceList.childElementCount > 1) box.appendChild(sourceList);
  }
}

socket.on('wake_detected', () => {
  appendLog({ time: ts(), source:'YANTRA', tag:'[WAKE]',
    message:'Wake word detected — listening for command…' });
});

socket.on('user_command', ({ text }) => {
  $('cmd-input').value = text;
});

// ═══════════════════════════════════════════════════════════════
// ACTIVITY LOG
// ═══════════════════════════════════════════════════════════════
function ts() {
  return new Date().toLocaleTimeString('en-US', { hour12:false });
}

function appendLog(entry) {
  const el = document.createElement('div');
  el.className = 'log-entry';
  const fields = [
    ['log-time', entry.time],
    [`log-src ${srcClass(entry.source)}`, entry.source],
    ['log-tag', entry.tag],
    ['log-msg', entry.message],
  ];
  fields.forEach(([className, value]) => {
    const field = document.createElement('span');
    field.className = className;
    field.textContent = value || '';
    el.appendChild(field);
  });
  const body = $('log-body');
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
}

// ═══════════════════════════════════════════════════════════════
// PROCESSES
// ═══════════════════════════════════════════════════════════════
function renderProcesses(procs) {
  $('proc-list').innerHTML = procs.map((p, i) => `
    <div class="proc-row">
      <span class="proc-name">${i+1}. ${p.name}</span>
      <span class="proc-pct">${p.cpu}%</span>
    </div>
    <div class="proc-bar"><div class="proc-fill" style="width:${Math.min(p.cpu*5,100)}%"></div></div>`
  ).join('');
}

// ═══════════════════════════════════════════════════════════════
// COMMAND INPUT
// ═══════════════════════════════════════════════════════════════
$('cmd-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendCommand(); }
});

function sendCommand(text) {
  text = (text || $('cmd-input').value).trim();
  if (!text) return;
  socket.emit('text_command', { text, inspect_screen: $('tog-vision').checked });
  $('agent-response-box').style.display = 'none';
}

function quickCmd(cmd) { $('cmd-input').value = cmd; sendCommand(cmd); }
function clearCmd()    { $('cmd-input').value = ''; $('agent-response-box').style.display = 'none'; }
function interrupt()   { socket.emit('interrupt'); }

// ── Voice toggle ──────────────────────────────────────────────────
let voiceOn = false;
function toggleVoice() {
  voiceOn = !voiceOn;
  const btn = $('btn-mic');
  socket.emit(voiceOn ? 'start_voice' : 'stop_voice');
  btn.classList.toggle('active', voiceOn);
  btn.textContent = voiceOn ? '🎤 MICROPHONE ACTIVE ▶▶' : '🎤 MICROPHONE READY';
  $('tog-voice').checked = voiceOn;
}
function toggleVoiceMode(el) { if (el.checked !== voiceOn) toggleVoice(); }

$('tog-auto').addEventListener('change', event => {
  const enabled = event.target.checked;
  localStorage.setItem('yantra_auto_listen', String(enabled));
  if (enabled !== voiceOn) toggleVoice();
});
$('tog-vision').addEventListener('change', event => {
  socket.emit('set_vision_mode', { enabled: event.target.checked });
});

document.addEventListener('keydown', e => { if (e.key === 'Escape') interrupt(); });

// ── File upload ───────────────────────────────────────────────────
$('upload-zone').addEventListener('click',      () => $('file-input').click());
$('upload-zone').addEventListener('dragover',   () => $('upload-zone').classList.add('dragover'));
$('upload-zone').addEventListener('dragleave',  () => $('upload-zone').classList.remove('dragover'));

function handleDrop(e) {
  e.preventDefault();
  $('upload-zone').classList.remove('dragover');
  handleFiles(e.dataTransfer.files);
}
async function handleFiles(files) {
  if (!files.length) return;
  const names = Array.from(files).map(file => file.name).join(', ');
  const status = $('upload-status');
  status.classList.remove('error');
  status.textContent = `ANALYZING: ${names}`;
  const form = new FormData();
  Array.from(files).forEach(file => form.append('files', file, file.name));
  form.append('prompt', $('cmd-input').value.trim());
  try {
    const response = await fetch('/api/upload', { method:'POST', body:form });
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.message || 'File analysis failed.');
    status.textContent = `ANALYSIS COMPLETE: ${names}`;
    showAssistantResponse(result.message, result.sources || [], true);
    appendLog({ time:ts(), source:'AGENT', tag:'[FILES]', message:`Analyzed ${names}` });
  } catch (error) {
    status.classList.add('error');
    status.textContent = error.message;
    showAssistantResponse(error.message, [], false);
  }
}

// ── Boot log ──────────────────────────────────────────────────────
appendLog({ time:ts(), source:'YANTRA', tag:'[SYSTEM]', message:'UI initialized successfully.' });
