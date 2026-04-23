let state = {
  payload: null,
  diffs: [],
  filtered: [],
  selectedId: null,
  reports: [],
};

function escapeHtml(s) {
  return (s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function summaryCard(label, value) {
  return `<div class="card"><div class="label">${label}</div><div class="value">${value}</div></div>`;
}

function getStatusClass(status) {
  return status || "unchanged";
}

async function fetchDiffs() {
  const res = await fetch("/api/diffs");
  if (!res.ok) throw new Error("Failed to fetch diffs");
  const payload = await res.json();
  state.payload = payload;
  state.diffs = payload.diffs || [];
  if (!state.selectedId && state.diffs.length) {
    state.selectedId = state.diffs[0].diff_id;
  }
  renderSummary();
  applyFilters();
  updateDocMeta();
}

async function fetchReports() {
  const res = await fetch("/api/reports");
  if (!res.ok) throw new Error("Failed to fetch report list");
  const payload = await res.json();
  state.reports = payload.reports || [];
  const select = document.getElementById("reportSelect");
  select.innerHTML = state.reports
    .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
    .join("");
  if (payload.current) {
    select.value = payload.current;
  }
}

function updateDocMeta() {
  document.getElementById("docA").textContent = state.payload?.pdf_a || "";
  document.getElementById("docB").textContent = state.payload?.pdf_b || "";
}

function renderSummary() {
  const statuses = state.diffs.map((d) => d.semantic_status || d.status);
  const count = (name) => statuses.filter((s) => s === name).length;
  const el = document.getElementById("summaryCards");
  el.innerHTML = [
    summaryCard("Modified", count("modified")),
    summaryCard("Unchanged", count("unchanged")),
    summaryCard("Added", count("added")),
    summaryCard("Removed", count("removed")),
    summaryCard("Renumbered", count("renumbering_only")),
    summaryCard("A / B", `${state.payload?.summary?.total_sections_a || 0} / ${state.payload?.summary?.total_sections_b || 0}`),
  ].join("");
}

function applyFilters() {
  const statusFilter = document.getElementById("statusFilter").value;
  const q = document.getElementById("searchInput").value.trim().toLowerCase();

  state.filtered = state.diffs.filter((d) => {
    const effectiveStatus = d.semantic_status || d.status;
    if (statusFilter !== "all" && effectiveStatus !== statusFilter) return false;
    if (!q) return true;
    const hay = `${d.title_a || ""} ${d.title_b || ""} ${(d.semantic_unified_diff || d.unified_diff || "").slice(0, 1000)}`.toLowerCase();
    return hay.includes(q);
  });

  if (!state.filtered.find((d) => d.diff_id === state.selectedId) && state.filtered.length) {
    state.selectedId = state.filtered[0].diff_id;
  }

  renderList();
  renderSelected();
}

function renderList() {
  const list = document.getElementById("diffList");
  list.innerHTML = state.filtered
    .map((d) => {
      const effectiveStatus = d.semantic_status || d.status;
      const active = d.diff_id === state.selectedId ? "active" : "";
      const score = d.match_score != null ? ` | score ${Number(d.match_score).toFixed(3)}` : "";
      const classBadge = d.change_classification ? ` <span class="small">class ${escapeHtml(d.change_classification)}</span>` : "";
      const lowConf = d.low_confidence ? ` <span class="small">low-confidence</span>` : "";
      return `
      <div class="list-item ${active}" data-id="${escapeHtml(d.diff_id)}">
        <div><span class="badge ${getStatusClass(effectiveStatus)}">${escapeHtml(effectiveStatus)}</span>${classBadge}${lowConf}</div>
        <div>${escapeHtml(d.title_b || d.title_a || "(untitled)")}</div>
        <div class="small">${escapeHtml(d.anchor_type || "")} ${score}</div>
      </div>`;
    })
    .join("");

  list.querySelectorAll(".list-item").forEach((el) => {
    el.addEventListener("click", () => {
      state.selectedId = el.getAttribute("data-id");
      renderList();
      renderSelected();
    });
  });
}

function tokenize(line) {
  return (line || "").split(/(\s+)/).filter((t) => t.length > 0);
}

function lcsMatrix(a, b) {
  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  return dp;
}

function inlineDiff(oldLine, newLine) {
  const a = tokenize(oldLine);
  const b = tokenize(newLine);
  const dp = lcsMatrix(a, b);

  let i = 0;
  let j = 0;
  let left = "";
  let right = "";

  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      left += `<span class="inline-same">${escapeHtml(a[i])}</span>`;
      right += `<span class="inline-same">${escapeHtml(b[j])}</span>`;
      i += 1;
      j += 1;
      continue;
    }
    if (dp[i + 1][j] >= dp[i][j + 1]) {
      left += `<span class="inline-del">${escapeHtml(a[i])}</span>`;
      i += 1;
    } else {
      right += `<span class="inline-add">${escapeHtml(b[j])}</span>`;
      j += 1;
    }
  }

  while (i < a.length) {
    left += `<span class="inline-del">${escapeHtml(a[i])}</span>`;
    i += 1;
  }
  while (j < b.length) {
    right += `<span class="inline-add">${escapeHtml(b[j])}</span>`;
    j += 1;
  }

  return { left, right };
}

function appendRows(rowsLeft, rowsRight, tag, linesA, linesB, changedOnly) {
  const maxLen = Math.max(linesA.length, linesB.length, 1);
  const rowClass = tag === "replace" ? "modified" : tag === "insert" ? "added" : tag === "delete" ? "removed" : "";

  for (let i = 0; i < maxLen; i++) {
    const a = linesA[i] || "";
    const b = linesB[i] || "";

    if (changedOnly && !a && !b) continue;

    if (tag === "replace") {
      const inl = inlineDiff(a, b);
      rowsLeft.push(`<div class="diff-row ${rowClass}"><div class="line">${inl.left}</div></div>`);
      rowsRight.push(`<div class="diff-row ${rowClass}"><div class="line">${inl.right}</div></div>`);
    } else {
      rowsLeft.push(`<div class="diff-row ${rowClass}"><div class="line">${escapeHtml(a)}</div></div>`);
      rowsRight.push(`<div class="diff-row ${rowClass}"><div class="line">${escapeHtml(b)}</div></div>`);
    }
  }
}

function buildContinuousHtml(chunks, side, changedOnly) {
  const out = [];

  for (const chunk of chunks || []) {
    const tag = chunk.tag;
    const linesA = chunk.lines_a || [];
    const linesB = chunk.lines_b || [];

    if (tag === "equal") {
      if (changedOnly) continue;
      const lines = side === "left" ? linesA : linesB;
      for (const line of lines) {
        out.push(`<span class="cont-line">${escapeHtml(line)}</span>`);
      }
      continue;
    }

    if (tag === "delete") {
      if (side === "right") continue;
      for (const line of linesA) {
        out.push(`<span class="cont-line line-del-block">${escapeHtml(line)}</span>`);
      }
      continue;
    }

    if (tag === "insert") {
      if (side === "left") continue;
      for (const line of linesB) {
        out.push(`<span class="cont-line line-add-block">${escapeHtml(line)}</span>`);
      }
      continue;
    }

    if (tag === "replace") {
      const maxLen = Math.max(linesA.length, linesB.length, 1);
      for (let i = 0; i < maxLen; i++) {
        const a = linesA[i] || "";
        const b = linesB[i] || "";
        const inl = inlineDiff(a, b);
        if (side === "left") {
          out.push(`<span class="cont-line line-mod-block">${inl.left || "&nbsp;"}</span>`);
        } else {
          out.push(`<span class="cont-line line-mod-block">${inl.right || "&nbsp;"}</span>`);
        }
      }
    }
  }

  return out.join("<br>");
}

function renderSelected() {
  const diff = state.filtered.find((d) => d.diff_id === state.selectedId) || state.diffs.find((d) => d.diff_id === state.selectedId);
  const header = document.getElementById("viewerHeader");
  const leftPane = document.getElementById("leftPane");
  const rightPane = document.getElementById("rightPane");

  if (!diff) {
    header.innerHTML = "<div>No diff selected</div>";
    leftPane.innerHTML = "";
    rightPane.innerHTML = "";
    return;
  }
  const effectiveStatus = diff.semantic_status || diff.status;

  header.innerHTML = `
    <div><span class="badge ${getStatusClass(effectiveStatus)}">${escapeHtml(effectiveStatus)}</span>
      <strong>${escapeHtml(diff.title_b || diff.title_a || "(untitled)")}</strong></div>
    <div class="small">anchor ${escapeHtml(diff.anchor_type || "")} | score ${escapeHtml(String(diff.match_score || 0))} (${escapeHtml(diff.match_confidence || "n/a")}) | pages ${escapeHtml(String(diff.page_no_in_a || "-"))} / ${escapeHtml(String(diff.page_no_in_b || "-"))}</div>
    <div class="small">classification: ${escapeHtml(diff.change_classification || "none")} | review: ${escapeHtml(diff.human_review?.validation_status || "needs_review")}</div>
  `;

  document.getElementById("validationStatus").value = diff.human_review?.validation_status || "needs_review";
  document.getElementById("reviewer").value = diff.human_review?.reviewer || "";
  document.getElementById("reviewNote").value = diff.human_review?.note || "";
  document.getElementById("classification").value = diff.change_classification || "";

  const showTitle = document.getElementById("showTitleDiff").checked;
  const changedOnly = document.getElementById("changedOnly").checked;

  const sectionChunks = diff.semantic_structured_diff || diff.section_structured_diff || [];
  let leftHtml = "";
  let rightHtml = "";

  if (showTitle && diff.title_diff) {
    leftHtml += `<div class="small">Title diff (${escapeHtml(diff.title_diff.status || "unchanged")})</div>`;
    rightHtml += `<div class="small">Title diff (${escapeHtml(diff.title_diff.status || "unchanged")})</div>`;
  }

  leftHtml += `<div class="section-block">${buildContinuousHtml(sectionChunks, "left", changedOnly)}</div>`;
  rightHtml += `<div class="section-block">${buildContinuousHtml(sectionChunks, "right", changedOnly)}</div>`;

  if (changedOnly && !leftHtml.includes("cont-line") && !rightHtml.includes("cont-line")) {
    leftHtml += `<div class="small">No changed lines in this section.</div>`;
    rightHtml += `<div class="small">No changed lines in this section.</div>`;
  }

  leftPane.innerHTML = leftHtml;
  rightPane.innerHTML = rightHtml;

  syncScroll(leftPane, rightPane);
}

function syncScroll(left, right) {
  let lock = false;
  const sync = (source, target) => {
    if (lock) return;
    lock = true;
    target.scrollTop = source.scrollTop;
    lock = false;
  };

  left.onscroll = () => sync(left, right);
  right.onscroll = () => sync(right, left);
}

async function saveReview() {
  const diff = state.diffs.find((d) => d.diff_id === state.selectedId);
  if (!diff) return;

  const payload = {
    validation_status: document.getElementById("validationStatus").value,
    reviewer: document.getElementById("reviewer").value || "anonymous",
    note: document.getElementById("reviewNote").value || "",
  };

  const res = await fetch(`/api/diffs/${encodeURIComponent(diff.diff_id)}/human-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to save review");
  await fetchDiffs();
}

async function saveClassification() {
  const diff = state.diffs.find((d) => d.diff_id === state.selectedId);
  if (!diff) return;

  const payload = {
    classification: document.getElementById("classification").value || null,
    source: "manual",
  };

  const res = await fetch(`/api/diffs/${encodeURIComponent(diff.diff_id)}/classify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to save classification");
  await fetchDiffs();
}

function bindEvents() {
  document.getElementById("searchInput").addEventListener("input", applyFilters);
  document.getElementById("statusFilter").addEventListener("change", applyFilters);
  document.getElementById("changedOnly").addEventListener("change", renderSelected);
  document.getElementById("showTitleDiff").addEventListener("change", renderSelected);
  document.getElementById("saveReviewBtn").addEventListener("click", () => saveReview().catch(alert));
  document.getElementById("saveClassBtn").addEventListener("click", () => saveClassification().catch(alert));

  document.getElementById("reloadBtn").addEventListener("click", async () => {
    const selected = document.getElementById("reportSelect").value || null;
    const res = await fetch("/api/reload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: selected }),
    });
    if (!res.ok) {
      alert("Reload failed");
      return;
    }
    await fetchReports();
    await fetchDiffs();
  });

  document.addEventListener("keydown", (ev) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName || "")) return;
    const idx = state.filtered.findIndex((d) => d.diff_id === state.selectedId);
    if (ev.key === "j" && idx < state.filtered.length - 1) {
      state.selectedId = state.filtered[idx + 1].diff_id;
      renderList();
      renderSelected();
    }
    if (ev.key === "k" && idx > 0) {
      state.selectedId = state.filtered[idx - 1].diff_id;
      renderList();
      renderSelected();
    }
    if (ev.key === "f") {
      document.getElementById("searchInput").focus();
    }
  });
}

(async function init() {
  bindEvents();
  try {
    await fetchReports();
    await fetchDiffs();
  } catch (err) {
    console.error(err);
    alert("Unable to load diffs");
  }
})();
