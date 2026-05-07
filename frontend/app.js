let downloadB64 = null;
let downloadFilename = null;

// ── Bootstrap ──────────────────────────────────────────────────────────────

async function init() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('auth_error')) {
    showError(`Google sign-in failed: ${params.get('auth_error')}. Please try again.`);
    history.replaceState({}, '', '/');
  }

  let authenticated = false;
  try {
    const res = await fetch('/api/auth/status');
    const data = await res.json();
    authenticated = data.authenticated;
  } catch {
    authenticated = false;
  }

  renderAuth(authenticated);

  if (authenticated) {
    show('converter-card');
  } else {
    show('auth-card');
  }
}

function renderAuth(authenticated) {
  const el = document.getElementById('header-auth');
  if (authenticated) {
    el.innerHTML = `
      <div class="auth-pill">
        <span class="dot"></span>
        <span>Connected to Google</span>
        <a href="/api/auth/logout" class="btn btn-ghost btn-sm">Sign out</a>
      </div>`;
  }
}

function parseCriticalCells(raw) {
  return (raw || '')
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

// ── Conversion flow ────────────────────────────────────────────────────────

async function startConversion() {
  const url = document.getElementById('sheet-url').value.trim();
  const strict = !!document.getElementById('strict-mode')?.checked;
  const compareValues = !!document.getElementById('compare-values')?.checked;
  const highlightMismatches = !!document.getElementById('highlight-mismatches')?.checked;
  const profile = document.getElementById('profile-mode')?.value || 'balanced';
  const strictPolicy = document.getElementById('strict-policy')?.value || 'off';
  const buildMode = document.getElementById('build-mode')?.value || 'internal';
  const criticalCells = parseCriticalCells(document.getElementById('critical-cells')?.value || '');

  if (!url) {
    document.getElementById('sheet-url').focus();
    return;
  }

  hideAll();
  show('progress-card');
  setProgress('Reading spreadsheet…');

  let data;
  try {
    const res = await fetch('/api/convert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        strict,
        profile,
        strict_policy: strictPolicy,
        build_mode: buildMode,
        critical_cells: criticalCells,
        compare_values: compareValues,
        highlight_mismatches: highlightMismatches,
      }),
    });

    if (res.status === 401) {
      hideAll();
      show('auth-card');
      return;
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      const detail = err?.detail;
      if (detail && typeof detail === 'object') {
        const base = detail.message || `Server error ${res.status}`;
        const count = Number.isFinite(detail.warning_count) ? detail.warning_count : null;
        const suffix = count !== null ? ` (${count} warning${count !== 1 ? 's' : ''})` : '';
        throw new Error(base + suffix);
      }
      throw new Error(detail || `Server error ${res.status}`);
    }

    setProgress('Converting formulas…');
    data = await res.json();
  } catch (err) {
    showError(err.message);
    return;
  }

  downloadB64 = data.file_b64;
  downloadFilename = data.filename;

  hideAll();
  show('results-card');
  show('converter-card');

  document.getElementById('result-title').textContent = `"${data.title}" converted`;
  document.getElementById('result-subtitle').textContent =
    `${data.sheet_count} sheet${data.sheet_count !== 1 ? 's' : ''}: ${data.sheet_names.join(', ')}`;

  renderBuildInfo(data.build);
  renderRisk(data.risk_report);
  renderParity(data.parity_report);
  renderValueParity(data.value_parity);

  hide('warnings-block');
  document.getElementById('warnings-list').innerHTML = '';
  document.getElementById('warn-badge').textContent = '';
  if (data.warning_count > 0) {
    document.getElementById('warn-badge').textContent = data.warning_count;
    renderWarnings(data.warnings);
    show('warnings-block');
  }
}

function renderBuildInfo(build) {
  const el = document.getElementById('build-block');
  if (!el || !build) return;
  const fallback = build.fallback_reason ? ` (fallback: ${escHtml(build.fallback_reason)})` : '';
  el.innerHTML = `
    <strong>Build mode:</strong> ${escHtml(build.mode_used || 'internal')}
    <span class="muted small">requested: ${escHtml(build.mode_requested || 'internal')}${fallback}</span>`;
  show('build-block');
}

function renderRisk(report) {
  const block = document.getElementById('risk-block');
  const summaryEl = document.getElementById('risk-summary');
  if (!block || !summaryEl || !report || !report.summary) return;
  const s = report.summary;
  const sev = s.severity_counts || {};
  summaryEl.textContent =
    `Risk score ${s.risk_score}/100 · formulas ${s.formula_cells} · warnings ${s.conversion_warning_cells} · `
    + `high ${sev.high || 0}, medium ${sev.medium || 0}, low ${sev.low || 0}`;
  show('risk-block');
}

function renderParity(report) {
  const block = document.getElementById('parity-block');
  const summaryEl = document.getElementById('parity-summary');
  const list = document.getElementById('parity-list');
  if (!block || !summaryEl || !list || !report || !report.summary) return;

  const s = report.summary;
  summaryEl.textContent =
    `Status: ${report.overall_status} · critical cells ${s.critical_count} · ok ${s.ok}, warning ${s.warning}, blocked ${s.blocked}, missing ${s.missing}`;
  list.innerHTML = '';
  for (const c of (report.checks || [])) {
    const div = document.createElement('div');
    div.className = 'warning-item' + (c.status === 'blocked' ? ' unsupported' : '');
    div.innerHTML = `
      <div class="loc">${escHtml(c.ref)} — ${escHtml(c.status.toUpperCase())}</div>
      <div class="notes">${escHtml(c.reason || 'No issues detected for this cell.')}</div>`;
    list.appendChild(div);
  }
  show('parity-block');
}

function renderValueParity(report) {
  const block = document.getElementById('value-parity-block');
  const summaryEl = document.getElementById('value-parity-summary');
  const list = document.getElementById('value-parity-list');
  if (!block || !summaryEl || !list || !report) return;

  if (!report.enabled) {
    hide('value-parity-block');
    return;
  }

  summaryEl.textContent =
    `Engine: ${report.engine} · checked ${report.checked_formula_cells} formula cells · `
    + `mismatches ${report.mismatch_count} · highlighted ${report.highlighted ? 'yes' : 'no'}`
    + (report.note ? ` · note: ${report.note}` : '');

  list.innerHTML = '';
  for (const m of (report.mismatches_preview || [])) {
    const div = document.createElement('div');
    div.className = 'warning-item unsupported';
    div.innerHTML = `
      <div class="loc">${escHtml(m.ref)}</div>
      <div class="notes">Sheets=${escHtml(m.source_value)} · Excel=${escHtml(m.excel_value)}</div>`;
    list.appendChild(div);
  }
  show('value-parity-block');
}

function renderWarnings(warnings) {
  const list = document.getElementById('warnings-list');
  list.innerHTML = '';

  for (const w of warnings) {
    const div = document.createElement('div');
    div.className = 'warning-item' + (w.has_unsupported ? ' unsupported' : '');

    const loc = `${w.sheet} · ${w.cell}`;
    const notes = w.warnings.join(' — ');

    div.innerHTML = `
      <div class="loc">${escHtml(loc)}</div>
      <div class="notes">${escHtml(notes)}</div>`;
    list.appendChild(div);
  }
}

// ── Download ───────────────────────────────────────────────────────────────

function downloadFile() {
  if (!downloadB64) return;
  const binary = atob(downloadB64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = downloadFilename || 'converted.xlsx';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Helpers ────────────────────────────────────────────────────────────────

function resetApp() {
  downloadB64 = null;
  downloadFilename = null;
  document.getElementById('sheet-url').value = '';
  document.getElementById('critical-cells').value = '';
  document.getElementById('warnings-list').innerHTML = '';
  document.getElementById('warn-badge').textContent = '';
  document.getElementById('parity-list').innerHTML = '';
  document.getElementById('value-parity-list').innerHTML = '';
  hide('build-block');
  hide('parity-block');
  hide('risk-block');
  hide('value-parity-block');
  const strictEl = document.getElementById('strict-mode');
  if (strictEl) strictEl.checked = false;
  const compareValues = document.getElementById('compare-values');
  if (compareValues) compareValues.checked = true;
  const highlightMismatches = document.getElementById('highlight-mismatches');
  if (highlightMismatches) highlightMismatches.checked = true;
  const strictPolicy = document.getElementById('strict-policy');
  if (strictPolicy) strictPolicy.value = 'off';
  const profileMode = document.getElementById('profile-mode');
  if (profileMode) profileMode.value = 'balanced';
  const buildMode = document.getElementById('build-mode');
  if (buildMode) buildMode.value = 'internal';
  hide('warnings-block');
  hide('results-card');
  hide('error-card');
  hide('progress-card');
  show('converter-card');
  document.getElementById('sheet-url').focus();
}

function showError(msg) {
  hideAll();
  document.getElementById('error-msg').textContent = msg;
  show('error-card');
  show('converter-card');
}

function setProgress(msg) {
  document.getElementById('progress-msg').textContent = msg;
}

function show(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }
function hide(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
function hideAll() {
  ['auth-card', 'converter-card', 'progress-card', 'results-card', 'error-card'].forEach(hide);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

init();
