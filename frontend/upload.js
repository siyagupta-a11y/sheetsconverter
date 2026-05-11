let downloadB64 = null;
let downloadFilename = null;

async function startUploadConversion() {
  const fileEl = document.getElementById("xlsx-file");
  const file = fileEl?.files?.[0];
  if (!file) {
    showError("Please choose a .xlsx file.");
    return;
  }
  if (!file.name.toLowerCase().endsWith(".xlsx")) {
    showError("Only .xlsx files are supported.");
    return;
  }
  // Vercel Functions have a 4.5 MB request/response payload limit.
  // Because this API currently returns base64 JSON, keep a conservative client-side cap.
  const MAX_UPLOAD_BYTES = 3.2 * 1024 * 1024;
  if (file.size > MAX_UPLOAD_BYTES) {
    showError("File is too large for hosted upload mode (>3.2 MB). Use a smaller workbook or run locally.");
    return;
  }

  hideAll();
  show("progress-card");

  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/convert-file", {
      method: "POST",
      body: form,
    });

    if (!res.ok) {
      const raw = await res.text().catch(() => "");
      let detail = "";
      try {
        const parsed = raw ? JSON.parse(raw) : {};
        detail = parsed.detail || parsed.message || "";
      } catch {
        detail = raw;
      }

      if (res.status === 413) {
        throw new Error("Upload too large for Vercel Function payload limits (413). Try a smaller file or run locally.");
      }
      if (!detail) {
        throw new Error(`Server error ${res.status}`);
      }
      throw new Error(`Server error ${res.status}: ${detail.slice(0, 260)}`);
    }
    const data = await res.json();

    downloadB64 = data.file_b64;
    downloadFilename = data.filename;

    hideAll();
    show("results-card");
    document.getElementById("result-title").textContent = `"${data.title}" patched`;
    document.getElementById("result-subtitle").textContent =
      `${data.warning_count} conversion warning${data.warning_count !== 1 ? "s" : ""}`;

    hide("warnings-block");
    document.getElementById("warnings-list").innerHTML = "";
    document.getElementById("warn-badge").textContent = "";
    if (data.warning_count > 0) {
      document.getElementById("warn-badge").textContent = data.warning_count;
      renderWarnings(data.warnings || []);
      show("warnings-block");
    }
  } catch (err) {
    showError(err.message || "Failed to process workbook.");
  }
}

function renderWarnings(warnings) {
  const list = document.getElementById("warnings-list");
  list.innerHTML = "";
  for (const w of warnings) {
    const div = document.createElement("div");
    div.className = "warning-item" + (w.has_unsupported ? " unsupported" : "");
    div.innerHTML = `
      <div class="loc">${escHtml(`${w.sheet} · ${w.cell}`)}</div>
      <div class="notes">${escHtml((w.warnings || []).join(" — "))}</div>`;
    list.appendChild(div);
  }
}

function downloadFile() {
  if (!downloadB64) return;
  const binary = atob(downloadB64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = downloadFilename || "patched.xlsx";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function resetUploadPage() {
  downloadB64 = null;
  downloadFilename = null;
  const fileEl = document.getElementById("xlsx-file");
  if (fileEl) fileEl.value = "";
  hide("warnings-block");
  hide("results-card");
  hide("error-card");
  hide("progress-card");
  show("uploader-card");
}

function showError(msg) {
  hideAll();
  document.getElementById("error-msg").textContent = msg;
  show("error-card");
}

function show(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "";
}

function hide(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = "none";
}

function hideAll() {
  ["uploader-card", "progress-card", "results-card", "error-card"].forEach(hide);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
