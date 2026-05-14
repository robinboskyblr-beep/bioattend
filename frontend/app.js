

const API = 'https://bioattend-1.onrender.com/api';

let scanStationClockInterval = null;

let capturedPhotos = [];

let autoScanInterval = null;

let kioskStream = null;

let adminStream = null;

let regStream = null;

let empStream = null;

let empAutoOn = false;

let empAutoInterval = null;

let currentEmpId = null;



/* Screens */

function showScreen(id) {

  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));

  document.getElementById(id).classList.add('active');

  if (id === 'kiosk-screen') {
    startCamera('kiosk-video', 'kiosk').then(s => kioskStream = s);
    loadKioskTodayLog();
    setKioskStatus('', 'Position your face inside the oval guide');
  }

  if (id === 'dashboard-screen') {

    startCamera('reg-video', 'reg').then(s => regStream = s);

    loadDashboard(); loadEmployees(); loadAttendance();

  }

  if (id === 'employee-screen') {

    startCamera('emp-video', 'emp').then(s => empStream = s);

    loadEmpTodayAttendance();

  }

  if (id === 'login-screen') {

    stopStream(kioskStream); stopStream(adminStream); stopStream(regStream); stopStream(empStream);

    // Stop kiosk auto scan
    if (kioskAutoOn) { kioskAutoOn = false; clearInterval(kioskAutoInterval); const ab = document.getElementById('kiosk-auto-btn'); if(ab) ab.classList.remove('active'); }

    // Stop employee auto scan if running

    if (empAutoOn) { empAutoOn = false; clearInterval(empAutoInterval); }

    currentEmpId = null;

  }

}



function stopStream(s) { if (s) s.getTracks().forEach(t => t.stop()); }



/* ── Employee Kiosk (no login) ── */

function enterEmployeeKiosk() {
  showScreen('kiosk-screen');
  // Auto-enable auto-scan after short delay
  setTimeout(() => {
    if (!kioskAutoOn) toggleKioskAuto();
  }, 1500);
}



/* ── Beep sound via Web Audio API ── */

function playBeep(type = 'success') {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    if (type === 'success') {
      // Two-tone success beep
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.15);
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.4, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.55);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.55);
    } else {
      // Error beep — low tone
      osc.frequency.value = 300;
      osc.type = 'sawtooth';
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.4);
    }
  } catch(e) { /* AudioContext blocked — ignore */ }
}



/* ── Convert stored UTC time string "HH:MM:SS" → IST display ── */
/* Old records were stored in UTC; add +5:30 for display.         */
/* New records (after backend fix) are already IST — detected by  */
/* checking if hour < 6 (very unlikely to be working at 1–5 AM).  */

function toIST(timeStr) {
  if (!timeStr) return null;
  try {
    const [h, m, s] = timeStr.split(':').map(Number);
    // If hour < 6 assume UTC → convert to IST
    if (h < 6) {
      const totalMin = h * 60 + m + 330; // +5h30m
      const ih = Math.floor(totalMin / 60) % 24;
      const im = totalMin % 60;
      return String(ih).padStart(2,'0') + ':' + String(im).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    }
    return timeStr; // already IST
  } catch { return timeStr; }
}



/* Clock */

function updateClocks() {

  const now = new Date();

  const time = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  const date = now.toLocaleDateString('en-IN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  const el1 = document.getElementById('kiosk-time');

  const el2 = document.getElementById('kiosk-date');

  const el3 = document.getElementById('topbar-time');

  const el4 = document.getElementById('emp-kiosk-time');

  const el5 = document.getElementById('emp-kiosk-date');

  if (el1) el1.textContent = time;

  if (el2) el2.textContent = date;

  if (el3) el3.textContent = time;

  if (el4) el4.textContent = time;

  if (el5) el5.textContent = date;

}

setInterval(updateClocks, 1000); updateClocks();



/* Particles */

(function spawnParticles() {

  const c = document.getElementById('particles');

  if (!c) return;

  for (let i = 0; i < 30; i++) {

    const d = document.createElement('div');

    d.style.cssText = `position:absolute;width:${Math.random()*3+1}px;height:${Math.random()*3+1}px;background:rgba(14,165,233,${Math.random()*0.5+0.1});border-radius:50%;left:${Math.random()*100}%;top:${Math.random()*100}%;animation:float ${Math.random()*10+8}s linear infinite;animation-delay:-${Math.random()*10}s`;

    c.appendChild(d);

  }

  const style = document.createElement('style');

  style.textContent = '@keyframes float{0%{transform:translateY(0) translateX(0);opacity:0}10%{opacity:1}90%{opacity:1}100%{transform:translateY(-100vh) translateX(40px);opacity:0}}';

  document.head.appendChild(style);

})();



/* Camera */

async function startCamera(videoId, ctx) {

  try {

    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 } });

    const v = document.getElementById(videoId);

    if (v) { v.srcObject = stream; }

    return stream;

  } catch (e) {

    toast('Camera access denied: ' + e.message, 'error');

    return null;

  }

}



function captureFrame(videoId, canvasId) {

  const v = document.getElementById(videoId);

  const c = document.getElementById(canvasId);

  if (!v || !c) return null;

  c.width = v.videoWidth || 640;

  c.height = v.videoHeight || 480;

  c.getContext('2d').drawImage(v, 0, 0);

  return c.toDataURL('image/jpeg', 0.8);

}



/* Auth */

function toggleAdminLogin() {
  const panel = document.getElementById('admin-login-panel');
  const arrow = document.getElementById('admin-toggle-arrow');
  if (!panel) return;
  const isOpen = panel.classList.toggle('open');
  if (arrow) arrow.style.transform = isOpen ? 'rotate(180deg)' : '';
  // Focus username field when opening
  if (isOpen) setTimeout(() => { const u = document.getElementById('login-username'); if (u) u.focus(); }, 350);
}

async function doLogin() {

  const u = document.getElementById('login-username').value.trim();

  const p = document.getElementById('login-password').value;

  if (!u || !p) { showError('login-error', 'Please enter username and password.'); return; }

  const btn = document.getElementById('login-btn');

  const btnText = document.getElementById('login-btn-text');

  if (btnText) btnText.textContent = 'Authenticating...';

  btn.disabled = true;

  try {

    const r = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: p }) });

    const d = await r.json();

    if (d.success) {

      if (d.role === 'employee') {

        // Employee → generic kiosk (face identifies who they are)
        showScreen('kiosk-screen');

      } else {

        // Admin / Manager → full dashboard
        document.getElementById('sidebar-user-name').textContent = d.name;

        showScreen('dashboard-screen');

      }

    } else { showError('login-error', 'Invalid username or password.'); }

  } catch { showError('login-error', 'Cannot connect to server. Is the backend running?'); }

  if (btnText) btnText.textContent = 'Access System';
  btn.disabled = false;

}



function doLogout() { showScreen('login-screen'); }

document.getElementById('login-password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });



/* Employee Screen Scan */

async function empScan() {

  const btn = document.getElementById('emp-scan-btn');

  const label = document.getElementById('emp-scan-label');

  const dot = document.getElementById('emp-status-dot');

  const txt = document.getElementById('emp-status-text');

  if (dot) dot.className = 'scan-status-dot scanning';

  if (txt) txt.textContent = 'Scanning please hold still';

  if (btn) btn.disabled = true;

  if (label) label.textContent = 'Scanning...';

  const img = captureFrame('emp-video', 'emp-canvas');

  if (!img) {

    if (dot) dot.className = 'scan-status-dot error';

    if (txt) txt.textContent = 'Camera not ready';

    if (btn) btn.disabled = false;

    if (label) label.textContent = 'Scan My Attendance';

    return;

  }

  try {

    const r = await fetch(`${API}/attendance/scan`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: img }) });

    const d = await r.json();

    showEmpResult(d);

    if (d.success && d.detected) loadEmpTodayAttendance();

  } catch (e) {

    if (dot) dot.className = 'scan-status-dot error';

    if (txt) txt.textContent = 'Server error - is the backend running?';

    showEmpResult({ success: false, message: 'Cannot reach server.' });

  }

  if (btn) btn.disabled = false;

  if (label) label.textContent = 'Scan My Attendance';

}



function showEmpResult(d) {

  const card = document.getElementById('emp-result-card');

  const idle = document.getElementById('emp-idle-card');

  const dot = document.getElementById('emp-status-dot');

  const txt = document.getElementById('emp-status-text');

  if (!card) return;

  card.className = 'scan-result-card glass-card';

  card.classList.remove('hidden');

  if (idle) idle.classList.add('hidden');

  const icon = document.getElementById('emp-src-icon');

  const name = document.getElementById('emp-src-name');

  const dept = document.getElementById('emp-src-dept');

  const action = document.getElementById('emp-src-action');

  const timeEl = document.getElementById('emp-src-time');

  const conf = document.getElementById('emp-src-conf');

  if (!d.success || !d.detected) {

    card.classList.add('fail');

    icon.textContent = ''; name.textContent = 'Not Recognised'; dept.textContent = '';

    action.textContent = d.message || 'No face detected'; action.className = 'src-action fail';

    timeEl.textContent = new Date().toLocaleTimeString(); conf.textContent = '';

    if (dot) dot.className = 'scan-status-dot error';

    if (txt) txt.textContent = d.message || 'No face detected';

  } else {

    const res = d.results[0];

    if (res.action === 'check_in') {

      card.classList.add('check-in');

      icon.textContent = '...'; name.textContent = res.name; dept.textContent = '';

      action.textContent = ' Clocked IN'; action.className = 'src-action in';

      timeEl.textContent = res.time; conf.textContent = `Confidence: ${res.confidence}%`;

      if (dot) dot.className = 'scan-status-dot success';

      if (txt) txt.textContent = `${res.name} clocked IN at ${res.time}`;

    } else if (res.action === 'check_out') {

      card.classList.add('check-out');

      icon.textContent = ''; name.textContent = res.name; dept.textContent = '';

      action.textContent = ' Clocked OUT'; action.className = 'src-action out';

      timeEl.textContent = res.time; conf.textContent = `Confidence: ${res.confidence}%`;

      if (dot) dot.className = 'scan-status-dot success';

      if (txt) txt.textContent = `${res.name} clocked OUT at ${res.time}`;

    } else {

      card.classList.add('fail');

      icon.textContent = ''; name.textContent = res.name || 'Unknown'; dept.textContent = '';

      action.textContent = res.message || 'Already complete'; action.className = 'src-action fail';

      timeEl.textContent = new Date().toLocaleTimeString(); conf.textContent = '';

      if (dot) dot.className = 'scan-status-dot error';

      if (txt) txt.textContent = res.message || 'Attendance already complete';

    }

  }

  setTimeout(() => {

    card.classList.add('hidden');

    if (idle) idle.classList.remove('hidden');

    if (dot) dot.className = 'scan-status-dot';

    if (txt) txt.textContent = 'Position your face inside the guide';

  }, 6000);

}



function toggleEmpAutoScan() {

  empAutoOn = !empAutoOn;

  const btn = document.getElementById('emp-auto-btn');

  if (empAutoOn) {

    empAutoInterval = setInterval(empScan, 3000);

    if (btn) btn.classList.add('active');

    toast('Auto Scan ON', 'success');

  } else {

    clearInterval(empAutoInterval);

    if (btn) btn.classList.remove('active');

    toast('Auto Scan OFF');

  }

}



async function loadEmpTodayAttendance() {

  if (!currentEmpId) return;

  try {

    const r = await fetch(`${API}/employees/my-attendance/${currentEmpId}`);

    const d = await r.json();

    const badge  = document.getElementById('emp-today-status-badge');
    const cin    = document.getElementById('emp-checkin-val');
    const cout   = document.getElementById('emp-checkout-val');
    const cin2   = document.getElementById('emp-checkin2-val');
    const cout2  = document.getElementById('emp-checkout2-val');

    const fmt = v => v ? `<span style="color:var(--cyan);font-weight:600">${toIST(v)}</span>` : '<span style="opacity:.35">—</span>';

    if (d.today) {

      const rec = d.today;

      if (cin)   cin.innerHTML   = fmt(rec.check_in);
      if (cout)  cout.innerHTML  = fmt(rec.check_out);
      if (cin2)  cin2.innerHTML  = fmt(rec.check_in_2);
      if (cout2) cout2.innerHTML = fmt(rec.check_out_2);


      if (badge) {
        if (rec.check_out_2)      { badge.textContent = 'Complete ✅'; badge.className = 'log-entry-badge out'; }
        else if (rec.check_in_2)  { badge.textContent = 'Afternoon In'; badge.className = 'log-entry-badge in'; }
        else if (rec.check_out)   { badge.textContent = 'Lunch Break'; badge.className = 'log-entry-badge'; }
        else if (rec.check_in)    { badge.textContent = 'Morning In'; badge.className = 'log-entry-badge in'; }
        else                      { badge.textContent = 'Not yet'; badge.className = 'log-entry-badge'; }
      }

    } else {

      if (cin)   cin.innerHTML   = fmt(null);
      if (cout)  cout.innerHTML  = fmt(null);
      if (cin2)  cin2.innerHTML  = fmt(null);
      if (cout2) cout2.innerHTML = fmt(null);

      if (badge) { badge.textContent = 'Not yet'; badge.className = 'log-entry-badge'; }

    }

  } catch (e) { console.error('loadEmpTodayAttendance:', e); }

}




/* Tabs */

function switchTab(el) {

  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));

  el.classList.add('active');

  document.getElementById(el.dataset.tab).classList.add('active');

  document.getElementById('topbar-title').textContent = el.querySelector('.nav-label').textContent;

  if (el.dataset.tab === 'tab-dashboard') loadDashboard();

  if (el.dataset.tab === 'tab-employees') loadEmployees();

  if (el.dataset.tab === 'tab-attendance') loadAttendance();

  if (el.dataset.tab === 'tab-settings') loadBackupEmail();

  // Auto-close sidebar on mobile after tab selection
  const sidebar = document.getElementById('sidebar');
  if (sidebar && sidebar.classList.contains('open')) {
    sidebar.classList.remove('open');
    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.classList.remove('show');
  }

}



function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  const overlay = document.getElementById('sidebar-overlay');
  if (overlay) overlay.classList.toggle('show');
}



/* Kiosk Scan */

let kioskAutoOn = false;
let kioskAutoInterval = null;
let kioskPopupTimer = null;

function setKioskStatus(state, msg) {
  const dot = document.getElementById('kiosk-status-dot');
  const txt = document.getElementById('kiosk-status-text');
  if (dot) dot.className = 'kiosk-status-dot ' + state;
  if (txt) txt.textContent = msg;
}

async function startScan() {

  const btn = document.getElementById('scan-btn');

  const btnTxt = document.getElementById('scan-btn-text');

  if (btn) btn.disabled = true;

  if (btnTxt) btnTxt.textContent = 'Scanning...';

  setKioskStatus('scanning', 'Analyzing face — please hold still');

  const img = captureFrame('kiosk-video', 'kiosk-canvas');

  if (!img) {
    setKioskStatus('error', 'Camera not ready');
    if (btn) btn.disabled = false;
    if (btnTxt) btnTxt.textContent = 'Scan Attendance';
    return;
  }

  try {

    const r = await fetch(`${API}/attendance/scan`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: img }) });

    const d = await r.json();

    showKioskPopup(d);

  } catch { showKioskPopup({ success: false, message: 'Server error. Please try again.' }); }

  if (btn) btn.disabled = false;

  if (btnTxt) btnTxt.textContent = 'Scan Attendance';

  setKioskStatus('', 'Position your face inside the oval guide');

}



function showKioskPopup(d) {

  const popup   = document.getElementById('kiosk-popup');
  const card    = document.getElementById('kiosk-popup-card');
  const avatar  = document.getElementById('kiosk-popup-avatar');
  const greet   = document.getElementById('kiosk-popup-greeting');
  const name    = document.getElementById('kiosk-popup-name');
  const action  = document.getElementById('kiosk-popup-action');
  const timeEl  = document.getElementById('kiosk-popup-time');
  const conf    = document.getElementById('kiosk-popup-conf');
  const prog    = document.getElementById('kiosk-popup-progress');
  const punches = document.getElementById('kiosk-popup-punches');

  if (!popup) return;

  if (kioskPopupTimer) clearTimeout(kioskPopupTimer);

  const hr = new Date().getHours();
  const greeting = hr < 12 ? 'Good Morning!' : hr < 17 ? 'Good Afternoon!' : 'Good Evening!';

  card.className = 'kiosk-popup-card';
  if (punches) punches.innerHTML = '';

  if (!d.success || !d.detected) {

    card.classList.add('fail');
    avatar.textContent  = '⚠';
    greet.textContent   = 'Not Recognised';
    name.textContent    = '';
    action.textContent  = d.message || 'No face detected';
    action.className    = 'kiosk-popup-action fail';
    timeEl.textContent  = '';
    conf.textContent    = 'Please try again or adjust lighting';
    setKioskStatus('error', d.message || 'No face detected');
    playBeep('error');

  } else {

    const res = d.results[0];

    const PUNCH_CONFIG = {
      check_in:    { cls: 'check-in',  greet: greeting,              icon: '✅', label: 'Clocked <strong>IN</strong>',            badge: '🟢 Morning In',    actionCls: 'in'  },
      check_out:   { cls: 'check-out', greet: 'Enjoy your lunch! 🍽', icon: '☕', label: 'Clocked <strong>OUT</strong> (Lunch)',    badge: '🔴 Lunch Break',   actionCls: 'out' },
      check_in_2:  { cls: 'check-in',  greet: 'Welcome back! 👋',    icon: '✅', label: 'Clocked <strong>IN</strong> (Afternoon)', badge: '🟢 Afternoon In',  actionCls: 'in'  },
      check_out_2: { cls: 'check-out', greet: 'See you tomorrow! 🌙', icon: '🚪', label: 'Clocked <strong>OUT</strong> — Day Done', badge: '🔴 End of Day',    actionCls: 'out' },
    };

    const cfg = PUNCH_CONFIG[res.action];

    if (cfg) {

      card.classList.add(cfg.cls);
      avatar.textContent = res.name ? res.name[0].toUpperCase() : '?';
      greet.textContent  = cfg.greet;
      name.textContent   = res.name;
      action.innerHTML   = cfg.icon + ' ' + cfg.label;
      action.className   = 'kiosk-popup-action ' + cfg.actionCls;
      timeEl.textContent = '⏰ ' + toIST(res.time);
      conf.textContent   = cfg.badge + '  ·  Confidence: ' + res.confidence + '%';
      setKioskStatus('success', res.name + ' — ' + cfg.badge + ' at ' + toIST(res.time));
      playBeep('success');
      loadKioskTodayLog();

      // Show today's punch summary in popup
      if (punches) {
        // Fetch today record for this employee to show all punches
        fetch(`${API}/employees/my-attendance/${res.employee_id}`)
          .then(r => r.json())
          .then(data => {
            if (data.today) {
              const rec = data.today;
              const punchData = [
                { label: '🟢 Morning In',   val: rec.check_in },
                { label: '🔴 Lunch Out',     val: rec.check_out },
                { label: '🟢 Lunch In',      val: rec.check_in_2 },
                { label: '🔴 Day Out (7PM)', val: rec.check_out_2 },
              ];
              punches.innerHTML = punchData.map(p =>
                `<div style="background:rgba(255,255,255,.06);border-radius:8px;padding:5px 8px;">
                  <div style="opacity:.55;font-size:.7rem">${p.label}</div>
                  <div style="font-weight:600;color:${p.val ? '#00d4ff' : 'rgba(255,255,255,.25)'}">${p.val ? toIST(p.val) : '—'}</div>
                </div>`
              ).join('');
            }
          }).catch(() => {});
      }

    } else {

      card.classList.add('fail');
      avatar.textContent = res.name ? res.name[0].toUpperCase() : '⚠';
      greet.textContent  = greeting;
      name.textContent   = res.name || '';
      action.textContent = res.message || 'All 4 punches complete for today ✅';
      action.className   = 'kiosk-popup-action fail';
      timeEl.textContent = new Date().toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'});
      conf.textContent   = '';
      setKioskStatus('error', res.message || 'Already complete');
      playBeep('error');

    }

  }

  // Show popup with animation
  popup.classList.remove('hidden');
  popup.classList.add('show');

  // Animate progress bar
  if (prog) {
    prog.style.transition = 'none';
    prog.style.width = '100%';
    setTimeout(() => {
      prog.style.transition = 'width 5s linear';
      prog.style.width = '0%';
    }, 50);
  }

  // Auto-dismiss after 5s
  kioskPopupTimer = setTimeout(() => {
    popup.classList.remove('show');
    setTimeout(() => popup.classList.add('hidden'), 400);
    setKioskStatus('', 'Position your face inside the oval guide');
  }, 5200);

}





function toggleKioskAuto() {
  kioskAutoOn = !kioskAutoOn;
  const btn = document.getElementById('kiosk-auto-btn');
  if (kioskAutoOn) {
    kioskAutoInterval = setInterval(startScan, 3000);
    if (btn) btn.classList.add('active');
    setKioskStatus('scanning', 'Auto scan ON — scanning every 3 seconds');
    toast('Auto Scan ON', 'success');
  } else {
    clearInterval(kioskAutoInterval);
    if (btn) btn.classList.remove('active');
    setKioskStatus('', 'Position your face inside the oval guide');
    toast('Auto Scan OFF');
  }
}



async function loadKioskTodayLog() {
  try {
    const r = await fetch(`${API}/attendance/today`);
    const d = await r.json();
    const log = document.getElementById('kiosk-today-log');
    const cnt = document.getElementById('kiosk-today-count');
    if (!log) return;
    if (cnt) cnt.textContent = d.total + ' entr' + (d.total === 1 ? 'y' : 'ies') + ' today';
    if (d.total === 0) {
      log.innerHTML = '<div class="kiosk-today-empty">No check-ins yet today</div>';
      return;
    }
    log.innerHTML = d.records.slice().reverse().slice(0, 6).map(rec => {
      // Show all filled punches
      const punches = [
        rec.check_in    ? `<span style="color:var(--green)">▶ ${rec.check_in}</span>`    : '',
        rec.check_out   ? `<span style="color:var(--blue)">◀ ${rec.check_out}</span>`   : '',
        rec.check_in_2  ? `<span style="color:var(--green)">▶ ${rec.check_in_2}</span>` : '',
        rec.check_out_2 ? `<span style="color:var(--blue)">◀ ${rec.check_out_2}</span>` : '',
      ].filter(Boolean);
      const pCount = punches.length;
      const isDone = pCount === 4;
      return `<div class="kiosk-today-row">
        <div class="kiosk-today-av">${rec.name[0]}</div>
        <div class="kiosk-today-info">
          <div class="kiosk-today-name">${rec.name}</div>
          <div class="kiosk-today-meta" style="display:flex;gap:8px;flex-wrap:wrap">${punches.join('<span style="opacity:.3">·</span>')}</div>
        </div>
        <span class="kiosk-today-badge ${isDone ? 'out' : 'in'}">${pCount}/4</span>
      </div>`;
    }).join('');

  } catch(e) { console.error('loadKioskTodayLog:', e); }
}




/* Scan Station */

function startScanStationClock() {

  stopScanStationClock();

  function tick() { const el = document.getElementById('scan-live-clock'); if (el) el.textContent = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }

  tick();

  scanStationClockInterval = setInterval(tick, 1000);

}

function stopScanStationClock() { if (scanStationClockInterval) { clearInterval(scanStationClockInterval); scanStationClockInterval = null; } }



function setScanStatus(state, msg) {

  const dot = document.getElementById('scan-status-dot');

  const txt = document.getElementById('scan-status-text');

  if (dot) { dot.className = 'scan-status-dot ' + state; }

  if (txt) txt.textContent = msg;

}



async function adminScan() {

  const btn = document.getElementById('admin-scan-btn');

  const label = document.getElementById('scan-btn-label');

  setScanStatus('scanning', 'Scanning please hold still');

  if (btn) btn.disabled = true;

  if (label) label.textContent = 'Scanning...';

  const img = captureFrame('admin-video', 'admin-canvas');

  if (!img) { setScanStatus('error', 'Camera not ready'); if (btn) btn.disabled = false; if (label) label.textContent = 'Scan My Attendance'; return; }

  try {

    const r = await fetch(`${API}/attendance/scan`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: img }) });

    const d = await r.json();

    showScanStationResult(d);

    if (d.success && d.detected) { loadScanLog(); loadDashboard(); }

  } catch (e) {

    setScanStatus('error', 'Server error - is the backend running?');

    showScanStationResult({ success: false, message: 'Cannot reach server.' });

  }

  if (btn) btn.disabled = false;

  if (label) label.textContent = 'Scan My Attendance';

}



function showScanStationResult(d) {

  const card = document.getElementById('scan-result-card');

  const idle = document.getElementById('scan-idle-card');

  if (!card) return;

  card.className = 'scan-result-card glass-card';

  card.classList.remove('hidden');

  if (idle) idle.classList.add('hidden');



  const icon = document.getElementById('src-icon');

  const name = document.getElementById('src-name');

  const dept = document.getElementById('src-dept');

  const action = document.getElementById('src-action');

  const timeEl = document.getElementById('src-time');

  const conf = document.getElementById('src-conf');



  if (!d.success || !d.detected) {

    card.classList.add('fail');

    icon.textContent = ''; name.textContent = 'Not Recognised'; dept.textContent = '';

    action.textContent = d.message || 'No face detected'; action.className = 'src-action fail';

    timeEl.textContent = new Date().toLocaleTimeString(); conf.textContent = '';

    setScanStatus('error', d.message || 'No face detected');

  } else {

    const res = d.results[0];

    if (res.action === 'check_in') {

      card.classList.add('check-in');

      icon.textContent = '...'; name.textContent = res.name; dept.textContent = '';

      action.textContent = ' Clocked IN'; action.className = 'src-action in';

      timeEl.textContent = res.time; conf.textContent = `Confidence: ${res.confidence}%`;

      setScanStatus('success', `${res.name} clocked IN at ${res.time}`);

    } else if (res.action === 'check_out') {

      card.classList.add('check-out');

      icon.textContent = ''; name.textContent = res.name; dept.textContent = '';

      action.textContent = ' Clocked OUT'; action.className = 'src-action out';

      timeEl.textContent = res.time; conf.textContent = `Confidence: ${res.confidence}%`;

      setScanStatus('success', `${res.name} clocked OUT at ${res.time}`);

    } else {

      card.classList.add('fail');

      icon.textContent = ''; name.textContent = res.name || 'Unknown'; dept.textContent = '';

      action.textContent = res.message || 'Already complete'; action.className = 'src-action fail';

      timeEl.textContent = new Date().toLocaleTimeString(); conf.textContent = '';

      setScanStatus('error', res.message || 'Attendance already complete');

    }

  }

  setTimeout(() => {

    card.classList.add('hidden');

    if (idle) idle.classList.remove('hidden');

    setScanStatus('ready', 'Position your face inside the guide');

  }, 6000);

}



async function loadScanLog() {

  try {

    const r = await fetch(`${API}/attendance/today`);

    const d = await r.json();

    const log = document.getElementById('scan-today-log');

    const cnt = document.getElementById('log-count');

    if (!log) return;

    if (cnt) cnt.textContent = `${d.total} entr${d.total === 1 ? 'y' : 'ies'}`;

    if (d.total === 0) { log.innerHTML = '<div class="log-empty">No check-ins yet today</div>'; return; }

    log.innerHTML = d.records.slice().reverse().map(rec => {

      const hasOut = !!rec.check_out;

      return `<div class="log-entry"><div class="log-entry-avatar">${rec.name[0]}</div><div style="flex:1"><div class="log-entry-name">${rec.name}</div><div class="log-entry-meta">IN ${rec.check_in}${hasOut ? ' . OUT ' + rec.check_out : ''}</div></div><span class="log-entry-badge ${hasOut ? 'out' : 'in'}">${hasOut ? 'Complete' : 'In'}</span></div>`;

    }).join('');

  } catch (e) { console.error('loadScanLog:', e); }

}



let autoOn = false;

function toggleAutoScan() {

  autoOn = !autoOn;

  const btn = document.getElementById('auto-scan-btn');

  if (autoOn) {

    autoScanInterval = setInterval(adminScan, 3000);

    if (btn) btn.classList.add('active');

    setScanStatus('ready', 'Auto scan active - scanning every 3 seconds');

    toast('Auto Scan ON', 'success');

  } else {

    clearInterval(autoScanInterval);

    if (btn) btn.classList.remove('active');

    setScanStatus('ready', 'Position your face inside the guide');

    toast('Auto Scan OFF');

  }

}



/* Registration */

function capturePhoto() {

  const img = captureFrame('reg-video', 'reg-canvas');

  if (!img) { toast('Camera not ready', 'error'); return; }

  capturedPhotos.push(img);

  const strip = document.getElementById('photo-strip');

  const thumb = document.createElement('img');

  thumb.src = img; thumb.className = 'photo-thumb'; strip.appendChild(thumb);

  document.getElementById('capture-count').textContent = `${capturedPhotos.length} photo${capturedPhotos.length > 1 ? 's' : ''} captured`;

  toast(`Photo ${capturedPhotos.length} captured`);

}



function clearCaptures() {

  capturedPhotos = [];

  document.getElementById('photo-strip').innerHTML = '';

  document.getElementById('capture-count').textContent = '0 photos captured';

}



async function registerEmployee(e) {

  e.preventDefault();

  if (capturedPhotos.length < 2) { toast('Capture at least 2 face photos', 'error'); return; }

  const btn = document.getElementById('reg-submit-btn');

  const status = document.getElementById('reg-status');

  btn.disabled = true; btn.textContent = 'Registering...';

  const payload = {

    name: document.getElementById('reg-name').value,

    employee_id: document.getElementById('reg-empid').value,

    department: document.getElementById('reg-dept').value,

    role: document.getElementById('reg-role').value,

    email: document.getElementById('reg-email').value,

    phone: document.getElementById('reg-phone').value,

    shift_start: document.getElementById('reg-shift-start').value,

    shift_end: document.getElementById('reg-shift-end').value,

    lunch_break_start: document.getElementById('reg-lunch-start').value,

    lunch_break_end: document.getElementById('reg-lunch-end').value,

    break_start: document.getElementById('reg-break-start').value,

    break_end: document.getElementById('reg-break-end').value,

    monthly_salary: parseFloat(document.getElementById('reg-salary').value) || 0,

    password: document.getElementById('reg-password').value || 'emp123',

    images: capturedPhotos

  };

  try {

    const r = await fetch(`${API}/employees/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });

    const d = await r.json();

    status.classList.remove('hidden', 'error', 'success');

    if (d.success) {

      status.className = 'reg-status success'; status.textContent = d.message;

      document.getElementById('reg-form').reset(); clearCaptures();

      toast('Employee registered!', 'success');

    } else { status.className = 'reg-status error'; status.textContent = d.detail || 'Registration failed'; }

  } catch (ex) { status.className = 'reg-status error'; status.textContent = 'Server error: ' + ex.message; status.classList.remove('hidden'); }

  btn.disabled = false; btn.textContent = 'Register Employee';

}



/* Role Selection */

const ROLE_CONFIG = {

  admin:    { label: 'Username',      hint: 'Full system access',                        user: '',  pass: '',  placeholder: 'Enter username' },

  manager:  { label: 'Username',      hint: 'Attendance & reports',                      user: '',  pass: '',  placeholder: 'Enter username' },

  employee: { label: 'Email Address', hint: '📸 Face scan kiosk will open after login',  user: '',  pass: '',  placeholder: 'your@email.com' }

};

let selectedRole = 'admin';

function selectRole(role) {

  selectedRole = role;

  document.querySelectorAll('.role-tab').forEach(t => t.classList.remove('active'));

  document.getElementById(`tab-${role}-btn`).classList.add('active');

  const cfg = ROLE_CONFIG[role];
  const userInput = document.getElementById('login-username');
  const loginBtnText = document.getElementById('login-btn-text');
  const kioskEntry = document.getElementById('kiosk-entry-btn');

  document.getElementById('username-label').textContent = cfg.label;
  userInput.placeholder = cfg.placeholder;
  userInput.value = cfg.user;
  // Switch input type for email keyboard on mobile
  userInput.type = (role === 'employee') ? 'email' : 'text';

  document.getElementById('login-password').value = cfg.pass;
  document.getElementById('role-hint-text').textContent = cfg.hint;

  // Update login button label
  if (loginBtnText) loginBtnText.textContent = (role === 'employee') ? 'Open Kiosk' : 'Access System';

  // Show/hide kiosk shortcut button
  if (kioskEntry) kioskEntry.parentElement.style.display = (role === 'employee') ? 'none' : '';

  const box = document.getElementById('creds-box');
  const credUser = document.getElementById('cred-user');
  const credPass = document.getElementById('cred-pass');

  if (role === 'employee') {
    box.style.display = 'none';
  } else {
    box.style.display = '';
    credUser.textContent = cfg.user;
    credPass.textContent = cfg.pass;
  }

  // Clear previous error
  const err = document.getElementById('login-error');
  if (err) err.classList.add('hidden');

}



/* Dashboard */

async function loadDashboard() {

  try {

    const r = await fetch(`${API}/dashboard/stats`);

    const d = await r.json();

    document.getElementById('stat-total').textContent = d.total_employees;

    document.getElementById('stat-present').textContent = d.present_today;

    document.getElementById('stat-absent').textContent = d.absent_today;

    document.getElementById('stat-rate').textContent = d.attendance_rate + '%';

    const list = document.getElementById('today-list');

    list.innerHTML = d.today_records.length === 0 ? '<div style="color:var(--text2);font-size:.85rem;text-align:center;padding:20px">No check-ins yet today</div>' :

      d.today_records.map(r => `<div class="today-item"><div class="today-avatar">${r.name[0]}</div><div><div class="today-name">${r.name}</div><div class="today-time">${r.check_in}${r.check_out ? '  ' + r.check_out : ''}</div></div><span class="badge badge-${r.check_out ? 'out' : 'in'}">${r.check_out ? 'Complete' : 'In'}</span></div>`).join('');

    renderWeeklyChart(d.weekly_stats);

    loadCalendar();

  } catch (e) { console.error('Dashboard error:', e); }

}



function renderWeeklyChart(stats) {

  const canvas = document.getElementById('weekly-chart');

  if (!canvas) return;

  const ctx = canvas.getContext('2d');

  const labels = Object.keys(stats).reverse();

  const values = labels.map(k => stats[k]);

  const W = canvas.offsetWidth || 400; const H = 200;

  canvas.width = W; canvas.height = H;

  const max = Math.max(...values, 1);

  const pad = { t: 20, b: 30, l: 30, r: 10 };

  const chartW = W - pad.l - pad.r; const chartH = H - pad.t - pad.b;

  ctx.clearRect(0, 0, W, H);

  // Grid

  ctx.strokeStyle = 'rgba(14,165,233,0.1)'; ctx.lineWidth = 1;

  for (let i = 0; i <= 4; i++) { const y = pad.t + (chartH / 4) * i; ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke(); }

  // Bars

  const bw = (chartW / labels.length) * 0.6;

  const gap = chartW / labels.length;

  const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);

  grad.addColorStop(0, 'rgba(0,212,255,0.9)'); grad.addColorStop(1, 'rgba(59,130,246,0.3)');

  labels.forEach((label, i) => {

    const bh = (values[i] / max) * chartH;

    const x = pad.l + gap * i + (gap - bw) / 2;

    const y = pad.t + chartH - bh;

    ctx.fillStyle = grad; ctx.beginPath();

    ctx.roundRect ? ctx.roundRect(x, y, bw, bh, 4) : ctx.rect(x, y, bw, bh);

    ctx.fill();

    ctx.fillStyle = 'rgba(148,163,184,0.7)'; ctx.font = '10px Inter'; ctx.textAlign = 'center';

    ctx.fillText(label.slice(5), pad.l + gap * i + gap / 2, H - 6);

    ctx.fillStyle = 'rgba(0,212,255,0.9)';

    ctx.fillText(values[i], pad.l + gap * i + gap / 2, y - 4);

  });

}



/* Employees */

let allEmployees = [];

async function loadEmployees() {

  try {

    const r = await fetch(`${API}/employees`);

    const d = await r.json();

    allEmployees = d.employees;

    renderEmployees(allEmployees);

    populateEmpDropdowns(allEmployees);

  } catch (e) { console.error(e); }

}



function renderEmployees(emps) {
  const grid = document.getElementById('employees-grid');
  if (!grid) return;
  grid.innerHTML = emps.length === 0
    ? '<div style="color:var(--text2);padding:40px;text-align:center;grid-column:1/-1">No employees registered yet.</div>'
    : emps.map(function(e) {
        var salary = e.monthly_salary > 0
          ? '<div class="emp-salary-badge">Rs.' + Number(e.monthly_salary).toLocaleString('en-IN') + '/mo</div>'
          : '';
        var shiftInfo = 'Shift: ' + (e.shift_start || '09:00') + ' - ' + (e.shift_end || '18:00');
        var lunchInfo = e.lunch_break_start
          ? ' | Lunch: ' + e.lunch_break_start + '-' + (e.lunch_break_end || '14:00')
          : '';
        var breakInfo = e.break_start
          ? ' | Break: ' + e.break_start + '-' + (e.break_end || '17:00')
          : ' | Break: 16:30-17:00';
        return '<div class="emp-card glass-card">' +
          '<div class="emp-avatar">' + e.name[0] + '</div>' +
          '<div class="emp-name">' + e.name + '</div>' +
          '<div class="emp-id">' + e.id + '</div>' +
          '<div class="emp-dept">' + e.department + '</div>' +
          '<div class="emp-role">' + e.role + '</div>' +
          '<div style="font-size:.75rem;color:var(--text2)">' + e.email + '</div>' +
          '<div style="font-size:.73rem;color:var(--text2);margin-top:2px">' + shiftInfo + lunchInfo + breakInfo + '</div>' +
          salary +
          '<div class="emp-actions">' +
          '<button class="btn-edit" onclick="editEmployee(\'' + e.id + '\')">&#9998; Edit</button>' +
          '<button style="padding:6px 10px;font-size:.73rem;background:linear-gradient(135deg,#0ea5e9,#0284c7);border:none;border-radius:8px;color:#fff;cursor:pointer;font-weight:600" onclick="openReregisterModal(\'' + e.id + '\',\'' + e.name + '\')">&#128247; Re-register Face</button>' +
          '<button class="btn-danger" style="padding:6px 12px;font-size:.75rem" onclick="deleteEmployee(\'' + e.id + '\')">&#128465; Remove</button>' +
          '</div></div>';
      }).join('');
}




function filterEmployees() {

  const q = document.getElementById('emp-search').value.toLowerCase();

  renderEmployees(allEmployees.filter(e => e.name.toLowerCase().includes(q) || e.id.toLowerCase().includes(q) || e.department.toLowerCase().includes(q)));

}




/* ── Re-register Face Modal ── */

let reregStream = null;
let reregEmpId  = null;
let reregCaptures = [];

function openReregisterModal(empId, empName) {
  reregEmpId = empId;
  reregCaptures = [];

  // Build modal HTML
  const existingModal = document.getElementById('rereg-modal');
  if (existingModal) existingModal.remove();

  const modal = document.createElement('div');
  modal.id = 'rereg-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(6px)';
  modal.innerHTML = `
    <div style="background:linear-gradient(135deg,#0f172a,#1e293b);border:1px solid rgba(0,212,255,.25);border-radius:20px;padding:28px;max-width:480px;width:95%;text-align:center">
      <h3 style="color:#00d4ff;margin-bottom:4px;font-size:1.1rem">📷 Re-register Face</h3>
      <p style="color:rgba(255,255,255,.55);font-size:.82rem;margin-bottom:16px">Capturing new face data for <strong style="color:#fff">${empName}</strong><br>Stand in good lighting and look at the camera. Capture 5 photos.</p>
      <div style="position:relative;border-radius:12px;overflow:hidden;background:#000;margin-bottom:14px;aspect-ratio:4/3">
        <video id="rereg-video" autoplay playsinline muted style="width:100%;height:100%;object-fit:cover"></video>
        <canvas id="rereg-canvas" style="display:none"></canvas>
        <div id="rereg-count-badge" style="position:absolute;top:10px;right:10px;background:rgba(0,212,255,.85);color:#000;font-weight:700;font-size:.85rem;padding:4px 10px;border-radius:20px">0 / 5</div>
      </div>
      <div id="rereg-thumbs" style="display:flex;gap:6px;justify-content:center;flex-wrap:wrap;margin-bottom:14px"></div>
      <div style="display:flex;gap:10px;justify-content:center">
        <button onclick="captureRereg()" style="padding:10px 22px;background:linear-gradient(135deg,#0ea5e9,#0284c7);border:none;border-radius:10px;color:#fff;font-weight:700;cursor:pointer;font-size:.9rem">📸 Capture</button>
        <button id="rereg-submit-btn" onclick="submitRereg()" disabled style="padding:10px 22px;background:linear-gradient(135deg,#10b981,#059669);border:none;border-radius:10px;color:#fff;font-weight:700;cursor:pointer;font-size:.9rem;opacity:.4">✅ Save (0/5)</button>
        <button onclick="closeReregModal()" style="padding:10px 18px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:10px;color:#fff;cursor:pointer;font-size:.9rem">✕ Cancel</button>
      </div>
      <p id="rereg-status" style="margin-top:12px;font-size:.82rem;color:rgba(255,255,255,.5)">Position your face clearly in the frame</p>
    </div>`;
  document.body.appendChild(modal);

  // Start camera
  navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 } })
    .then(s => {
      reregStream = s;
      document.getElementById('rereg-video').srcObject = s;
    })
    .catch(e => { document.getElementById('rereg-status').textContent = 'Camera error: ' + e.message; });
}

function captureRereg() {
  if (reregCaptures.length >= 8) { toast('Maximum 8 captures reached', 'info'); return; }
  const v = document.getElementById('rereg-video');
  const c = document.getElementById('rereg-canvas');
  c.width = v.videoWidth || 640;
  c.height = v.videoHeight || 480;
  c.getContext('2d').drawImage(v, 0, 0);
  const dataUrl = c.toDataURL('image/jpeg', 0.85);
  reregCaptures.push(dataUrl);

  // Update thumbs
  const thumbs = document.getElementById('rereg-thumbs');
  const img = document.createElement('img');
  img.src = dataUrl;
  img.style.cssText = 'width:52px;height:52px;object-fit:cover;border-radius:8px;border:2px solid #00d4ff';
  thumbs.appendChild(img);

  const count = reregCaptures.length;
  document.getElementById('rereg-count-badge').textContent = count + ' / 5';
  const submitBtn = document.getElementById('rereg-submit-btn');
  submitBtn.textContent = '✅ Save (' + count + '/5)';
  if (count >= 5) {
    submitBtn.disabled = false;
    submitBtn.style.opacity = '1';
    document.getElementById('rereg-status').textContent = '✅ Ready to save! You can capture more for better accuracy.';
  } else {
    document.getElementById('rereg-status').textContent = (5 - count) + ' more capture(s) needed.';
  }
}

async function submitRereg() {
  if (reregCaptures.length < 5) { toast('Please capture at least 5 photos', 'error'); return; }
  const btn = document.getElementById('rereg-submit-btn');
  btn.disabled = true; btn.textContent = '⏳ Processing...';
  document.getElementById('rereg-status').textContent = 'Uploading and processing face data...';

  try {
    const r = await fetch(`${API}/employees/${reregEmpId}/reregister-face`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images: reregCaptures })
    });
    const d = await r.json();
    if (d.success) {
      toast('✅ ' + d.message, 'success');
      closeReregModal();
    } else {
      document.getElementById('rereg-status').textContent = '❌ ' + (d.detail || 'Failed. Try again.');
      btn.disabled = false; btn.textContent = '✅ Save (' + reregCaptures.length + '/5)';
    }
  } catch (e) {
    document.getElementById('rereg-status').textContent = '❌ Server error: ' + e.message;
    btn.disabled = false; btn.textContent = '✅ Save (' + reregCaptures.length + '/5)';
  }
}

function closeReregModal() {
  if (reregStream) reregStream.getTracks().forEach(t => t.stop());
  reregStream = null;
  reregCaptures = [];
  const m = document.getElementById('rereg-modal');
  if (m) m.remove();
}



async function deleteEmployee(id) {

  if (!confirm('Remove this employee and all their face data?')) return;

  try {

    const r = await fetch(`${API}/employees/${id}`, { method: 'DELETE' });

    const d = await r.json();

    if (d.success) { toast('Employee removed', 'success'); loadEmployees(); }

  } catch (e) { toast('Error: ' + e.message, 'error'); }

}



function editEmployee(id) {

  const emp = allEmployees.find(e => e.id === id);

  if (!emp) return;

  document.getElementById('edit-empid').value = emp.id;

  document.getElementById('edit-empid-display').value = emp.id;

  document.getElementById('edit-modal-sub').textContent = `ID: ${emp.id}`;

  document.getElementById('edit-name').value = emp.name || '';

  document.getElementById('edit-dept').value = emp.department || 'AI Automation Engineer';

  document.getElementById('edit-role').value = emp.role || 'AI Automation Engineer';

  document.getElementById('edit-email').value = emp.email || '';

  document.getElementById('edit-phone').value = emp.phone || '';

  document.getElementById('edit-shift-start').value = emp.shift_start || '09:00';

  document.getElementById('edit-shift-end').value = emp.shift_end || '18:00';

  document.getElementById('edit-lunch-start').value = emp.lunch_break_start || '13:00';

  document.getElementById('edit-lunch-end').value = emp.lunch_break_end || '14:00';

  document.getElementById('edit-break-start').value = emp.break_start || '16:30';

  document.getElementById('edit-break-end').value = emp.break_end || '17:00';

  document.getElementById('edit-salary').value = emp.monthly_salary || '';

  document.getElementById('edit-status').classList.add('hidden');

  document.getElementById('edit-modal').classList.remove('hidden');

  document.body.classList.add('modal-open');

}



function handleModalBackdrop(e) {

  if (e.target === document.getElementById('edit-modal')) closeEditModal();

}



function closeEditModal() {

  document.getElementById('edit-modal').classList.add('hidden');

  document.body.classList.remove('modal-open');

}



/* ── Clear Attendance Modal ── */

function openClearModal() {
  const modal = document.getElementById('clear-att-modal');
  if (!modal) return;
  // Set today's date as default
  const today = new Date().toISOString().split('T')[0];
  const dateInput = document.getElementById('clear-date-input');
  if (dateInput) dateInput.value = today;
  // Reset scope
  const scope = document.getElementById('clear-scope');
  if (scope) scope.value = 'date';
  onClearScopeChange();
  modal.classList.remove('hidden');
  document.body.classList.add('modal-open');
}

function closeClearModal() {
  const modal = document.getElementById('clear-att-modal');
  if (modal) modal.classList.add('hidden');
  document.body.classList.remove('modal-open');
}

function handleClearModalBackdrop(e) {
  if (e.target === document.getElementById('clear-att-modal')) closeClearModal();
}

function onClearScopeChange() {
  const scope = document.getElementById('clear-scope').value;
  const dateWrap = document.getElementById('clear-date-wrap');
  const warning = document.getElementById('clear-warning');
  const confirmBtn = document.getElementById('clear-confirm-btn');
  if (scope === 'all') {
    if (dateWrap) dateWrap.style.display = 'none';
    if (warning) warning.style.display = 'block';
    if (confirmBtn) confirmBtn.textContent = '🗑 Delete ALL Records';
  } else {
    if (dateWrap) dateWrap.style.display = '';
    if (warning) warning.style.display = 'none';
    if (confirmBtn) confirmBtn.textContent = '🗑 Confirm & Delete';
  }
}

async function confirmClearAttendance() {
  const scope = document.getElementById('clear-scope').value;
  const date  = document.getElementById('clear-date-input')?.value;
  const btn   = document.getElementById('clear-confirm-btn');

  if (scope === 'date' && !date) { toast('Please select a date to clear', 'error'); return; }

  // Extra safety confirmation for nuke-all
  if (scope === 'all') {
    const confirmed = confirm('⚠️ Are you absolutely sure?\n\nThis will PERMANENTLY DELETE every attendance record across ALL employees and ALL dates from Firebase.\n\nType OK to confirm.');
    if (!confirmed) return;
  }

  btn.disabled = true;
  btn.textContent = '⏳ Deleting...';

  try {
    let url = `${API}/attendance/clear`;
    if (scope === 'date' && date) url += `?date=${date}`;

    const r = await fetch(url, { method: 'DELETE' });
    const d = await r.json();

    if (d.success) {
      toast(`✅ Deleted ${d.deleted} record${d.deleted !== 1 ? 's' : ''} (${d.scope})`, 'success');
      closeClearModal();
      loadAttendance();        // refresh the table
      loadDashboard();         // refresh stats
    } else {
      toast('Error: ' + (d.detail || 'Unknown error'), 'error');
    }
  } catch (e) {
    toast('Server error: ' + e.message, 'error');
  }

  btn.disabled = false;
  onClearScopeChange(); // restore button text
}


async function saveEmployee(e) {

  e.preventDefault();

  const id = document.getElementById('edit-empid').value;

  const btn = document.getElementById('edit-save-btn');

  const status = document.getElementById('edit-status');

  btn.disabled = true; btn.textContent = 'Saving...';

  const payload = {

    name: document.getElementById('edit-name').value,

    department: document.getElementById('edit-dept').value,

    role: document.getElementById('edit-role').value,

    email: document.getElementById('edit-email').value,

    phone: document.getElementById('edit-phone').value,

    shift_start: document.getElementById('edit-shift-start').value,

    shift_end: document.getElementById('edit-shift-end').value,

    lunch_break_start: document.getElementById('edit-lunch-start').value,

    lunch_break_end: document.getElementById('edit-lunch-end').value,

    break_start: document.getElementById('edit-break-start').value,

    break_end: document.getElementById('edit-break-end').value,

    monthly_salary: parseFloat(document.getElementById('edit-salary').value) || 0

  };

  try {

    const r = await fetch(`${API}/employees/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });

    const d = await r.json();

    status.classList.remove('hidden', 'error', 'success');

    if (d.success) {

      status.className = 'reg-status success'; status.textContent = '... ' + d.message;

      toast('Employee updated!', 'success');

      loadEmployees();

      setTimeout(closeEditModal, 1200);

    } else {

      status.className = 'reg-status error'; status.textContent = d.detail || 'Update failed';

    }

  } catch (ex) {

    status.classList.remove('hidden'); status.className = 'reg-status error'; status.textContent = 'Server error: ' + ex.message;

  }

  btn.disabled = false; btn.innerHTML = '<span class="btn-glow"></span>&#128190; Save Changes';

}



function populateEmpDropdowns(emps) {

  const selects = ['manual-emp', 'report-emp-select', 'payroll-emp'];

  selects.forEach(sid => {

    const sel = document.getElementById(sid);

    if (!sel) return;

    const isPayroll = sid === 'payroll-emp';

    sel.innerHTML = (isPayroll ? '<option value="">All Employees</option>' : '<option value="">Select Employee</option>')

      + emps.map(e => `<option value="${e.id}">${e.name} (${e.id})</option>`).join('');

  });

}



/* Attendance */

async function loadAttendance(start, end) {

  try {

    let url = `${API}/attendance/history`;

    const params = new URLSearchParams();

    if (start) params.append('start_date', start);

    if (end) params.append('end_date', end);

    if (params.toString()) url += '?' + params.toString();

    const r = await fetch(url);

    const d = await r.json();

    renderAttendanceTable(d.records);

  } catch (e) { console.error(e); }

}



function filterAttendance() {

  const s = document.getElementById('att-start').value;

  const e = document.getElementById('att-end').value;

  loadAttendance(s, e);

}



function renderAttendanceTable(records) {

  const tbody = document.getElementById('att-tbody');

  if (!tbody) return;

  tbody.innerHTML = records.length === 0 ? '<tr><td colspan="9" style="text-align:center;padding:30px;color:var(--text2)">No attendance records found</td></tr>' :

    records.slice().reverse().map(r => {
      const p = [r.check_in, r.check_out, r.check_in_2, r.check_out_2].filter(Boolean).length;
      return `<tr>
        <td><strong>${r.name}</strong><br><span style="font-size:.75rem;color:var(--text2)">${r.employee_id}</span></td>
        <td>${r.department || ''}</td>
        <td>${r.date}</td>
        <td style="color:var(--green);font-family:'Orbitron',sans-serif;font-size:.8rem">${r.check_in || '—'}</td>
        <td style="color:var(--red);font-family:'Orbitron',sans-serif;font-size:.8rem">${r.check_out || '—'}</td>
        <td style="color:var(--green);font-family:'Orbitron',sans-serif;font-size:.8rem">${r.check_in_2 || '—'}</td>
        <td style="color:var(--blue);font-family:'Orbitron',sans-serif;font-size:.8rem">${r.check_out_2 || '—'}</td>
        <td><span class="badge badge-present">${r.status}</span></td>
        <td><span class="badge ${p===4?'badge-out':'badge-in'}">${p}/4</span></td>
      </tr>`;
    }).join('');


}



async function submitManualAttendance() {

  const eid = document.getElementById('manual-emp').value;

  const type = document.getElementById('manual-type').value;

  const date = document.getElementById('manual-date').value;

  if (!eid) { toast('Select an employee', 'error'); return; }

  try {

    const r = await fetch(`${API}/attendance/manual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ employee_id: eid, type, date: date || undefined }) });

    const d = await r.json();

    if (d.success) { toast(d.message, 'success'); loadAttendance(); loadDashboard(); }

    else toast(d.detail || 'Error', 'error');

  } catch (e) { toast('Server error', 'error'); }

}



function exportAttendance() {

  const rows = document.querySelectorAll('#att-tbody tr');

  let csv = 'Name,Employee ID,Department,Date,Check In,Check Out,Status,Confidence\n';

  rows.forEach(r => {

    const cells = r.querySelectorAll('td');

    if (cells.length < 2) return;

    csv += Array.from(cells).map(c => `"${c.innerText.replace(/\n/g, ', ')}"`).join(', ') + '\n';

  });

  downloadCSV(csv, `attendance_${new Date().toISOString().slice(0, 10)}.csv`);

}



/* Reports */

async function generateMonthlyReport() {

  const r = await fetch(`${API}/attendance/history`);

  const d = await r.json();

  const out = document.getElementById('report-output');

  out.classList.remove('hidden');

  const byDate = {};

  d.records.forEach(rec => { if (!byDate[rec.date]) byDate[rec.date] = 0; byDate[rec.date]++; });

  out.innerHTML = '<h3 style="margin-bottom:16px">Monthly Attendance Summary</h3><table><thead><tr><th>Date</th><th>Present</th></tr></thead><tbody>' + Object.entries(byDate).sort((a, b) => b[0].localeCompare(a[0])).map(([date, count]) => `<tr><td>${date}</td><td>${count}</td></tr>`).join('') + '</tbody></table>';

}



async function generateEmployeeReport() {

  const eid = document.getElementById('report-emp-select').value;

  if (!eid) { toast('Select an employee', 'error'); return; }

  const r = await fetch(`${API}/attendance/history?employee_id=${eid}`);

  const d = await r.json();

  const out = document.getElementById('report-output');

  out.classList.remove('hidden');

  const emp = allEmployees.find(e => e.id === eid);

  out.innerHTML = `<h3 style="margin-bottom:8px">${emp?.name || eid}  Attendance Report</h3><p style="color:var(--text2);font-size:.85rem;margin-bottom:16px">Total: ${d.total} records</p><table><thead><tr><th>Date</th><th>Check In</th><th>Check Out</th><th>Status</th></tr></thead><tbody>` + d.records.map(r => `<tr><td>${r.date}</td><td>${r.check_in || ', '}</td><td>${r.check_out || ', '}</td><td>${r.status}</td></tr>`).join('') + '</tbody></table>';

}



async function exportAllData() {

  const r = await fetch(`${API}/attendance/history`);

  const d = await r.json();

  let csv = 'Name,Employee ID,Department,Date,Check In,Check Out,Status,Confidence\n';

  d.records.forEach(r => { csv += `"${r.name}","${r.employee_id}","${r.department || ''}","${r.date}","${r.check_in || ''}","${r.check_out || ''}","${r.status}","${r.confidence || 'Manual'}"\n`; });

  downloadCSV(csv, `bioattend_all_${new Date().toISOString().slice(0, 10)}.csv`);

}



function downloadCSV(csv, filename) {

  const a = document.createElement('a');

  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));

  a.download = filename; a.click();

}



/* Helpers */

function toast(msg, type = 'info') {

  const t = document.getElementById('toast');

  t.textContent = msg;

  t.className = `toast`;

  t.style.background = type === 'error' ? 'linear-gradient(135deg,#f43f5e,#be123c)' : type === 'success' ? 'linear-gradient(135deg,#0ea5e9,#1d4ed8)' : 'linear-gradient(135deg,#3b82f6,#1d4ed8)';

  t.classList.remove('hidden');

  setTimeout(() => t.classList.add('hidden'), 3000);

}



function showError(id, msg) { const el = document.getElementById(id); if (el) { el.textContent = msg; el.classList.remove('hidden'); } }



// Set default date for manual attendance

document.getElementById('manual-date').value = new Date().toISOString().slice(0, 10);

document.getElementById('att-start').value = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);

document.getElementById('att-end').value = new Date().toISOString().slice(0, 10);



/* Payroll Report */

let lastPayrollData = [];



function fmt(n) {

  return '' + Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

}



async function generatePayrollReport() {

  const start = document.getElementById('payroll-start').value;

  const end   = document.getElementById('payroll-end').value;

  const eid   = document.getElementById('payroll-emp').value;

  let url = `${API}/payroll/calculate`;

  const p = new URLSearchParams();

  if (start) p.append('start_date', start);

  if (end)   p.append('end_date', end);

  if (eid)   p.append('employee_id', eid);

  if (p.toString()) url += '?' + p.toString();

  try {

    const r = await fetch(url);

    const d = await r.json();

    lastPayrollData = d.payroll || [];

    renderPayrollReport(lastPayrollData, d.period);

  } catch (e) { toast('Error fetching payroll: ' + e.message, 'error'); }

}



function renderPayrollReport(payroll, period) {

  const out = document.getElementById('payroll-output');

  out.classList.remove('hidden');

  if (payroll.length === 0) {

    out.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text2)">No payroll data found for the selected period.</div>';

    return;

  }

  const totalGross  = payroll.reduce((s, p) => s + p.gross_earned, 0);

  const totalPenalty = payroll.reduce((s, p) => s + p.total_penalty, 0);

  const totalNet    = payroll.reduce((s, p) => s + p.net_salary, 0);

  const periodLabel = (period?.start && period?.end) ? `${period.start} to ${period.end}` : 'All time';



  out.innerHTML = `

    <div class="payroll-summary-bar">

      <div class="payroll-sum-item"><div class="payroll-sum-label">Period</div><div class="payroll-sum-value" style="font-size:.85rem;font-family:Inter,sans-serif">${periodLabel}</div></div>

      <div class="payroll-sum-item"><div class="payroll-sum-label">Employees</div><div class="payroll-sum-value">${payroll.length}</div></div>

      <div class="payroll-sum-item"><div class="payroll-sum-label">Total Gross</div><div class="payroll-sum-value">${fmt(totalGross)}</div></div>

      <div class="payroll-sum-item"><div class="payroll-sum-label">Total Deductions</div><div class="payroll-sum-value red">${fmt(totalPenalty)}</div></div>

      <div class="payroll-sum-item"><div class="payroll-sum-label">Total Net Pay</div><div class="payroll-sum-value green">${fmt(totalNet)}</div></div>

    </div>

    <table class="payroll-table">

      <thead><tr>

        <th>Employee</th>

        <th>Dept</th>

        <th>Monthly Salary</th>

        <th>Daily Rate</th>

        <th>Days Worked</th>

        <th>Gross Earned</th>

        <th>Late Days</th>

        <th>Deductions</th>

        <th>Net Salary</th>

      </tr></thead>

      <tbody>

        ${payroll.map(p => `

          <tr>

            <td class="name-cell">${p.name}<br><span style="font-size:.72rem;color:var(--text2);font-weight:400">${p.employee_id}</span></td>

            <td>${p.department || ''}</td>

            <td class="salary-cell">${fmt(p.monthly_salary)}</td>

            <td>${fmt(p.daily_rate)}</td>

            <td><strong>${p.working_days}</strong></td>

            <td class="salary-cell">${fmt(p.gross_earned)}</td>

            <td>${p.late_days > 0 ? `<span class="payroll-late-chip"> ${p.late_days}d</span>` : '<span style="opacity:.4"></span>'}</td>

            <td class="${p.total_penalty > 0 ? 'penalty-cell' : 'zero-cell'}">${p.total_penalty > 0 ? '-' + fmt(p.total_penalty) : ''}</td>

            <td class="net-cell">${fmt(p.net_salary)}</td>

          </tr>`).join('')}

      </tbody>

    </table>`;

}



function exportPayrollCSV() {

  if (!lastPayrollData.length) { toast('Generate a payroll report first', 'error'); return; }

  let csv = 'Employee,Employee ID,Department,Monthly Salary,Daily Rate,Days Worked,Gross Earned,Late Days,Deductions,Net Salary\n';

  lastPayrollData.forEach(p => {

    csv += `"${p.name}","${p.employee_id}","${p.department || ''}","${p.monthly_salary}","${p.daily_rate}","${p.working_days}","${p.gross_earned}","${p.late_days}","${p.total_penalty}","${p.net_salary}"\n`;

  });

  downloadCSV(csv, `payroll_${new Date().toISOString().slice(0,10)}.csv`);

}



// Default payroll date range: current month

(function initPayrollDates(){

  const now = new Date();

  const y = now.getFullYear(), m = String(now.getMonth()+1).padStart(2,'0');

  const lastDay = new Date(y, now.getMonth()+1, 0).getDate();

  const s = document.getElementById('payroll-start');

  const e = document.getElementById('payroll-end');

  if (s) s.value = `${y}-${m}-01`;

  if (e) e.value = `${y}-${m}-${String(lastDay).padStart(2,'0')}`;

})();



/* Monthly Attendance Calendar */

let calYear  = new Date().getFullYear();

let calMonth = new Date().getMonth();

let calAttData = {};

let calSelectedDay = null;

let calTotalEmps = 0;



const CAL_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',

                    'July', 'August', 'September', 'October', 'November', 'December'];



async function loadCalendar() {

  const y = calYear;

  const m = String(calMonth + 1).padStart(2, '0');

  const start = `${y}-${m}-01`;

  const lastD = new Date(y, calMonth + 1, 0).getDate();

  const end   = `${y}-${m}-${String(lastD).padStart(2, '0')}`;



  const lbl = document.getElementById('cal-month-label');

  const sub = document.getElementById('cal-subtitle');

  if (lbl) lbl.textContent = `${CAL_MONTHS[calMonth]} ${y}`;

  if (sub) sub.textContent = `Attendance overview - ${CAL_MONTHS[calMonth]} ${y}`;



  try {

    const [attRes, dbRes] = await Promise.all([

      fetch(`${API}/attendance/history?start_date=${start}&end_date=${end}`),

      fetch(`${API}/dashboard/stats`)

    ]);

    const attData = await attRes.json();

    const dbData  = await dbRes.json();

    calTotalEmps  = dbData.total_employees || 0;

    calAttData = {};

    (attData.records || []).forEach(r => {

      if (!calAttData[r.date]) calAttData[r.date] = [];

      calAttData[r.date].push(r);

    });

    renderCalendar();

  } catch(e) { console.error('Calendar load error:', e); }

}



function renderCalendar() {

  const grid = document.getElementById('cal-days');

  if (!grid) return;

  const today    = new Date();

  const todayStr = today.toISOString().slice(0, 10);

  const firstDay = new Date(calYear, calMonth, 1).getDay();

  const daysInM  = new Date(calYear, calMonth + 1, 0).getDate();

  let html = '';

  for (let i = 0; i < firstDay; i++) html += '<div class="cal-day empty"></div>';

  for (let d = 1; d <= daysInM; d++) {

    const mm       = String(calMonth + 1).padStart(2, '0');

    const dd       = String(d).padStart(2, '0');

    const dateStr  = `${calYear}-${mm}-${dd}`;

    const dayDate  = new Date(calYear, calMonth, d);

    const dow      = dayDate.getDay();

    const isWeekend  = dow === 0;  // Only Sunday is off; Saturday is a working day

    const isToday    = dateStr === todayStr;

    const isFuture   = dayDate > today && !isToday;

    const isSelected = dateStr === calSelectedDay;

    const recs    = calAttData[dateStr] || [];

    const present = new Set(recs.map(r => r.employee_id)).size;

    const fullDay = recs.filter(r => r.check_out).length;



    let statusClass = '', dotHtml = '', countHtml = '';

    if (!isWeekend && !isFuture) {

      if (present === 0 && calTotalEmps > 0) {

        statusClass = 'status-absent';

        dotHtml = '<div class="cal-day-dot" style="background:rgba(244,63,94,0.5)"></div>';

      } else if (present > 0) {

        const allFull = fullDay === present;

        statusClass = allFull ? 'status-full' : 'status-half';

        const col = allFull ? 'var(--green)' : '#f59e0b';

        dotHtml   = `<div class="cal-day-dot" style="background:${col}"></div>`;

        countHtml = `<div class="cal-day-count">${present}/${calTotalEmps}</div>`;

      }

    }

    const cls = ['cal-day', isWeekend?'weekend':'', isToday?'today':'',

      isFuture?'future':'', isSelected?'selected':'', statusClass

    ].filter(Boolean).join(' ');



    html += `<div class="${cls}" onclick="calSelectDay('${dateStr}')">

      <div class="cal-day-num">${d}</div>${dotHtml}${countHtml}

      <div class="cal-day-bar"></div></div>`;

  }

  grid.innerHTML = html;

  if (calSelectedDay) renderCalDayDetail(calSelectedDay);

}



function calSelectDay(dateStr) {

  const detail = document.getElementById('cal-day-detail');

  if (calSelectedDay === dateStr) {

    calSelectedDay = null;

    if (detail) detail.classList.add('hidden');

    renderCalendar(); return;

  }

  calSelectedDay = dateStr;

  renderCalendar();

  renderCalDayDetail(dateStr);

}



function renderCalDayDetail(dateStr) {

  const detail = document.getElementById('cal-day-detail');

  if (!detail) return;

  detail.classList.remove('hidden');

  const recs    = calAttData[dateStr] || [];

  const present = new Set(recs.map(r => r.employee_id)).size;

  const fullDay = recs.filter(r => r.check_out).length;

  const d       = new Date(dateStr + 'T00:00:00');

  const label   = d.toLocaleDateString('en-IN', { weekday:'long', day:'numeric', month:'long', year:'numeric' });



  let status, sCls;

  if (recs.length === 0)        { status = 'No Records';                             sCls = 'absent'; }

  else if (fullDay === present) { status = `${present} Present - Full Day`;          sCls = 'full';   }

  else                          { status = `${present} Present - ${fullDay} Full - ${present-fullDay} Partial`; sCls = 'half'; }



  const rows = recs.length === 0

    ? '<div class="cal-detail-empty">No attendance records for this day.</div>'

    : recs.map(r => {

        const hasOut = !!r.check_out;

        return `<div class="cal-detail-row">

          <div class="cal-detail-name">${r.name}

            <span style="font-size:.68rem;color:var(--text2);font-weight:400;margin-left:5px">${r.employee_id}</span>

          </div>

          <div class="cal-detail-time">

            <span style="color:var(--green)">&#9654; ${r.check_in||'&#8212;'}</span>

            ${hasOut ? `<span style="margin:0 4px;opacity:.4">&#183;</span><span style="color:var(--blue)">&#9664; ${r.check_out}</span>` : ''}

          </div>

          <span class="badge ${hasOut?'badge-present':'badge-in'}" style="font-size:.68rem">${hasOut?'Complete':'In'}</span>

        </div>`;

      }).join('');



  detail.innerHTML = `

    <div class="cal-detail-header">

      <div class="cal-detail-date">${label}</div>

      <span class="cal-detail-badge ${sCls}">${status}</span>

    </div>

    <div class="cal-detail-list">${rows}</div>`;

}



function calNavigate(dir) {

  calSelectedDay = null;

  const detail = document.getElementById('cal-day-detail');

  if (detail) detail.classList.add('hidden');

  calMonth += dir;

  if (calMonth > 11) { calMonth = 0;  calYear++; }

  if (calMonth < 0)  { calMonth = 11; calYear--; }

  loadCalendar();

}



function calGoToday() {

  const now = new Date();

  calSelectedDay = null;

  calYear  = now.getFullYear();

  calMonth = now.getMonth();

  const detail = document.getElementById('cal-day-detail');

  if (detail) detail.classList.add('hidden');

  loadCalendar();

}


/* Settings: Change Credentials */

function showSettingStatus(id, msg, ok) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = 'reg-status ' + (ok ? 'success' : 'error');
  el.classList.remove('hidden');
  setTimeout(function() { el.classList.add('hidden'); }, 5000);
}

async function changeAdminCreds() {
  const oldPw  = document.getElementById('adm-old-pw').value.trim();
  const newPw  = document.getElementById('adm-new-pw').value.trim();
  const confPw = document.getElementById('adm-confirm-pw').value.trim();
  if (!oldPw || !newPw) return showSettingStatus('adm-status', 'Please fill in all password fields.', false);
  if (newPw !== confPw) return showSettingStatus('adm-status', 'New passwords do not match.', false);
  try {
    const r = await fetch(API + '/auth/change-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', role: 'admin', old_password: oldPw, new_password: newPw })
    });
    const d = await r.json();
    if (r.ok && d.success) {
      showSettingStatus('adm-status', 'Admin password updated!', true);
      ['adm-old-pw','adm-new-pw','adm-confirm-pw'].forEach(function(id){ document.getElementById(id).value = ''; });
    } else { showSettingStatus('adm-status', d.detail || 'Failed.', false); }
  } catch(e) { showSettingStatus('adm-status', 'Cannot reach server.', false); }
}

async function changeManagerCreds() {
  const oldPw  = document.getElementById('mgr-old-pw').value.trim();
  const newPw  = document.getElementById('mgr-new-pw').value.trim();
  const confPw = document.getElementById('mgr-confirm-pw').value.trim();
  if (!oldPw || !newPw) return showSettingStatus('mgr-status', 'Please fill in all password fields.', false);
  if (newPw !== confPw) return showSettingStatus('mgr-status', 'New passwords do not match.', false);
  try {
    const r = await fetch(API + '/auth/change-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'manager', role: 'manager', old_password: oldPw, new_password: newPw })
    });
    const d = await r.json();
    if (r.ok && d.success) {
      showSettingStatus('mgr-status', 'Manager password updated!', true);
      ['mgr-old-pw','mgr-new-pw','mgr-confirm-pw'].forEach(function(id){ document.getElementById(id).value = ''; });
    } else { showSettingStatus('mgr-status', d.detail || 'Failed.', false); }
  } catch(e) { showSettingStatus('mgr-status', 'Cannot reach server.', false); }
}

async function resetEmployeePassword() {
  const empId  = document.getElementById('emp-reset-id').value.trim();
  const oldPw  = document.getElementById('emp-reset-old').value.trim();
  const newPw  = document.getElementById('emp-reset-new').value.trim();
  const confPw = document.getElementById('emp-reset-confirm').value.trim();
  if (!empId)           return showSettingStatus('emp-reset-status', 'Please enter an Employee ID.', false);
  if (!oldPw || !newPw) return showSettingStatus('emp-reset-status', 'Please fill in all password fields.', false);
  if (newPw !== confPw) return showSettingStatus('emp-reset-status', 'New passwords do not match.', false);
  try {
    const r = await fetch(API + '/auth/change-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: empId, role: 'employee', old_password: oldPw, new_password: newPw })
    });
    const d = await r.json();
    if (r.ok && d.success) {
      showSettingStatus('emp-reset-status', 'Password for ' + empId + ' updated!', true);
      ['emp-reset-id','emp-reset-old','emp-reset-new','emp-reset-confirm'].forEach(function(id){ document.getElementById(id).value = ''; });
    } else { showSettingStatus('emp-reset-status', d.detail || 'Failed.', false); }
  } catch(e) { showSettingStatus('emp-reset-status', 'Cannot reach server.', false); }
}


/* ─── Backup Functions ─── */

let autoBackupInterval = null;
let autoBackupOn = false;

function csvFromRecords(headers, rows) {
  function escape(v) {
    if (v === null || v === undefined) return '';
    v = String(v);
    if (v.includes(',') || v.includes('"') || v.includes('\n')) {
      v = '"' + v.replace(/"/g, '""') + '"';
    }
    return v;
  }
  const lines = [headers.map(escape).join(',')];
  rows.forEach(function(r) {
    lines.push(headers.map(function(h) { return escape(r[h]); }).join(','));
  });
  return lines.join('\n');
}

function downloadCSV(filename, csvContent) {
  const BOM = '\uFEFF';
  const blob = new Blob([BOM + csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  const log = document.getElementById('backup-log');
  if (log) log.innerHTML = '<span style="color:var(--green)">Downloaded: ' + filename + ' at ' + new Date().toLocaleTimeString() + '</span>';
}

async function backupToday() {
  try {
    const today = new Date().toISOString().split('T')[0];
    const r = await fetch(API + '/backup/daily?target_date=' + today);
    const d = await r.json();
    const headers = ['date','employee_id','name','department','role','email','phone','shift_start','shift_end','clock_in','lunch_out','lunch_in','clock_out','status','confidence','manual'];
    const csv = csvFromRecords(headers, d.records);
    downloadCSV('attendance_' + today + '.csv', csv);
    toast('Today backup downloaded (' + d.total + ' records)', 'success');
  } catch(e) { toast('Backup failed: ' + e.message, 'error'); }
}

async function backupRange() {
  const start = document.getElementById('backup-start').value;
  const end   = document.getElementById('backup-end').value;
  if (!start || !end) { toast('Please select both start and end date', 'error'); return; }
  try {
    const r = await fetch(API + '/backup/range?start_date=' + start + '&end_date=' + end);
    const d = await r.json();
    const headers = ['date','employee_id','name','department','role','email','phone','shift_start','shift_end','clock_in','lunch_out','lunch_in','clock_out','status','confidence','manual'];
    const csv = csvFromRecords(headers, d.records);
    downloadCSV('attendance_' + start + '_to_' + end + '.csv', csv);
    toast('Range backup downloaded (' + d.total + ' records)', 'success');
  } catch(e) { toast('Backup failed: ' + e.message, 'error'); }
}

async function backupEmployees() {
  try {
    const r = await fetch(API + '/backup/employees');
    const d = await r.json();
    const headers = ['id','name','department','role','email','phone','shift_start','shift_end','lunch_break_start','lunch_break_end','monthly_salary','registered_at','active'];
    const csv = csvFromRecords(headers, d.employees);
    const today = new Date().toISOString().split('T')[0];
    downloadCSV('employees_' + today + '.csv', csv);
    toast('Employee directory downloaded (' + d.total + ' employees)', 'success');
  } catch(e) { toast('Backup failed: ' + e.message, 'error'); }
}

function toggleAutoBackup() {
  autoBackupOn = !autoBackupOn;
  const btn = document.getElementById('auto-backup-btn');
  const status = document.getElementById('auto-backup-status');
  if (autoBackupOn) {
    if (btn) { btn.textContent = 'Stop Auto'; btn.style.background = 'rgba(239,68,68,.2)'; }
    const timeVal = document.getElementById('auto-backup-time').value || '18:00';
    if (status) status.textContent = 'Active - will backup at ' + timeVal + ' daily';
    checkAutoBackupSchedule(timeVal);
    autoBackupInterval = setInterval(function() { checkAutoBackupSchedule(timeVal); }, 60000);
    toast('Auto-backup enabled at ' + timeVal, 'success');
  } else {
    clearInterval(autoBackupInterval);
    if (btn) { btn.textContent = 'Start Auto'; btn.style.background = ''; }
    if (status) status.textContent = '';
    toast('Auto-backup stopped');
  }
}

function checkAutoBackupSchedule(targetTime) {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2,'0');
  const mm = String(now.getMinutes()).padStart(2,'0');
  if ((hh + ':' + mm) === targetTime) {
    backupToday();
    toast('Auto-backup triggered at ' + targetTime, 'success');
  }
}

/* ─── Email Backup ─── */

async function loadBackupEmail() {
  try {
    const r = await fetch(`${API}/settings/backup-email`);
    const d = await r.json();
    const inp = document.getElementById('backup-email-input');
    if (inp && d.email) inp.value = d.email;
  } catch(e) { /* silent */ }

  // Load SMTP config status
  try {
    const rs = await fetch(`${API}/settings/smtp`);
    const ds = await rs.json();
    const badge = document.getElementById('smtp-configured-badge');
    const userInp = document.getElementById('smtp-user-input');
    if (badge) {
      if (ds.configured) {
        badge.textContent = '✓ Configured';
        badge.style.background = 'rgba(34,211,238,0.15)';
        badge.style.color = '#22d3ee';
        badge.style.borderColor = 'rgba(34,211,238,0.3)';
        if (userInp && ds.smtp_user) userInp.value = ds.smtp_user;
      } else {
        badge.textContent = '● Not Configured';
        badge.style.background = 'rgba(244,63,94,0.15)';
        badge.style.color = '#f43f5e';
        badge.style.borderColor = 'rgba(244,63,94,0.3)';
      }
    }
  } catch(e) { /* silent */ }
}

async function saveSmtpSettings() {
  const smtpUser = document.getElementById('smtp-user-input')?.value.trim();
  const smtpPass = document.getElementById('smtp-pass-input')?.value.trim();

  if (!smtpUser || !smtpUser.includes('@')) {
    showSettingStatus('smtp-save-status', '❌ Please enter a valid Gmail address.', false);
    return;
  }
  if (!smtpPass) {
    showSettingStatus('smtp-save-status', '❌ Please enter your Gmail App Password.', false);
    return;
  }

  try {
    const r = await fetch(`${API}/settings/smtp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ smtp_user: smtpUser, smtp_pass: smtpPass })
    });
    const d = await r.json();
    if (r.ok && d.success) {
      showSettingStatus('smtp-save-status', '✅ SMTP credentials saved! You can now send backup emails.', true);
      // Update badge
      const badge = document.getElementById('smtp-configured-badge');
      if (badge) {
        badge.textContent = '✓ Configured';
        badge.style.background = 'rgba(34,211,238,0.15)';
        badge.style.color = '#22d3ee';
        badge.style.borderColor = 'rgba(34,211,238,0.3)';
      }
      document.getElementById('smtp-pass-input').value = '';
      toast('✅ SMTP credentials saved!', 'success');
    } else {
      showSettingStatus('smtp-save-status', '❌ ' + (d.detail || 'Failed to save.'), false);
    }
  } catch(e) {
    showSettingStatus('smtp-save-status', '❌ Cannot reach server.', false);
  }
}

async function saveBackupEmail() {
  const email = document.getElementById('backup-email-input')?.value.trim();

  const status = document.getElementById('backup-email-status');
  if (!email || !email.includes('@')) {
    showSettingStatus('backup-email-status', 'Please enter a valid email address.', false);
    return;
  }
  try {
    const r = await fetch(`${API}/settings/backup-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recipient: email })
    });
    const d = await r.json();
    if (r.ok && d.success) {
      showSettingStatus('backup-email-status', `✅ Backup email saved: ${d.email}`, true);
    } else {
      showSettingStatus('backup-email-status', d.detail || 'Failed to save.', false);
    }
  } catch(e) {
    showSettingStatus('backup-email-status', 'Cannot reach server.', false);
  }
}

async function sendEmailBackup() {
  const btn     = document.getElementById('send-backup-btn');
  const btnText = document.getElementById('send-backup-text');
  const status  = document.getElementById('send-backup-status');

  if (btn) btn.disabled = true;
  if (btnText) btnText.textContent = '⏳ Sending backup…';
  if (status) { status.className = 'reg-status hidden'; }

  try {
    const r = await fetch(`${API}/backup/send-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})   // uses saved email from Firestore
    });
    const d = await r.json();

    if (r.ok && d.success) {
      showSettingStatus(
        'send-backup-status',
        `✅ Backup sent! ${d.records} attendance records & ${d.employees} employees → ${d.message.replace('Backup sent to ','')}`,
        true
      );
      toast('📧 Backup emailed successfully!', 'success');
    } else {
      showSettingStatus('send-backup-status', '❌ ' + (d.detail || 'Failed to send.'), false);
      toast('Backup failed: ' + (d.detail || 'Unknown error'), 'error');
    }
  } catch(e) {
    showSettingStatus('send-backup-status', '❌ Cannot reach server: ' + e.message, false);
    toast('Server error: ' + e.message, 'error');
  }

  if (btn) btn.disabled = false;
  if (btnText) btnText.textContent = '📤 Send Full Backup Now';
}
