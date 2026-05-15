backup_js = """

/* ─── Backup Functions ─── */

let autoBackupInterval = null;
let autoBackupOn = false;

function csvFromRecords(headers, rows) {
  function escape(v) {
    if (v === null || v === undefined) return '';
    v = String(v);
    if (v.includes(',') || v.includes('"') || v.includes('\\n')) {
      v = '"' + v.replace(/"/g, '""') + '"';
    }
    return v;
  }
  const lines = [headers.map(escape).join(',')];
  rows.forEach(function(r) {
    lines.push(headers.map(function(h) { return escape(r[h]); }).join(','));
  });
  return lines.join('\\n');
}

function downloadCSV(filename, csvContent) {
  const BOM = '\\uFEFF';
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
"""

with open('frontend/app.js', 'a', encoding='utf-8') as f:
    f.write(backup_js)

print('Backup JS appended successfully.')
