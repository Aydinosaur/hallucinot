const config = window.HALLUCINOT_CONFIG || {};
const API_BASE_URL = (config.API_BASE_URL || "").replace(/\/$/, "");

const form = document.getElementById("analyze-form");
const fileInput = document.getElementById("document");
const fileName = document.getElementById("file-name");
const errorBox = document.getElementById("error-box");
const resultsShell = document.getElementById("results-shell");
const statsGrid = document.getElementById("stats-grid");
const resultsBody = document.getElementById("results-body");
const downloadButton = document.getElementById("download-json");
const apiStatus = document.getElementById("api-status");

let latestReportJson = "[]";

if (API_BASE_URL.includes("your-cloud-run-service-url")) {
  apiStatus.textContent = "Set frontend/config.js to your Cloud Run API URL before deploying to Netlify.";
}

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name || "No file selected";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.classList.add("hidden");
  resultsShell.classList.add("hidden");
  resultsBody.innerHTML = "";
  statsGrid.innerHTML = "";

  if (!API_BASE_URL || API_BASE_URL.includes("your-cloud-run-service-url")) {
    errorBox.textContent = "The frontend is not configured yet. Set frontend/config.js to your deployed Cloud Run URL.";
    errorBox.classList.remove("hidden");
    return;
  }

  const formData = new FormData(form);
  formData.append("provider", "CourtListener");

  try {
    const response = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Analysis failed.");
    }

    latestReportJson = payload.report_json;
    renderStats(payload.summary);
    renderRows(payload.results);
    resultsShell.classList.remove("hidden");
    document.querySelector(".report-kicker").textContent = `Results · ${payload.provider}`;
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  }
});

downloadButton.addEventListener("click", () => {
  const blob = new Blob([latestReportJson], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "hallucinot-report.json";
  link.click();
  URL.revokeObjectURL(url);
});

function renderStats(summary) {
  const entries = [
    ["Characters", summary.characters],
    ["Citations", summary.citations_found],
    ["Verified", summary.verified],
    ["Rejected", summary.rejected],
    ["Ambiguous", summary.ambiguous],
    ["Not Found", summary.not_found],
    ["Quoted", summary.quoted_snippets],
    ["Id. Links", summary.id_references],
  ];

  for (const [label, value] of entries) {
    const card = document.createElement("article");
    card.className = "metric-card";
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    statsGrid.appendChild(card);
  }
}

function renderRows(results) {
  results.forEach((item, index) => {
    const card = document.createElement("details");
    card.className = `result-card status-${item.status}`;
    card.open = index < 2;
    card.style.setProperty("--delay", `${index * 40}ms`);

    const topCandidate = item.candidates[0];
    const matchedCitationText = topCandidate?.matched_citations?.join(" · ") || "";

    card.innerHTML = `
      <summary class="card-summary">
        <div class="summary-left">
          <span class="status-pill status-pill-${item.status}">${escapeHtml(formatStatus(item.status))}</span>
          <div class="citation-block">
            <span class="section-label">Citation</span>
            <h3>${escapeHtml(item.citation)}</h3>
            <p class="raw-citation">${escapeHtml(item.extracted_case_name || item.raw_text || "")}</p>
          </div>
        </div>

        <div class="summary-mid">
          <div class="compact-card">
            <span class="section-label">Document Caption</span>
            <p class="case-name">${escapeHtml(item.extracted_case_name || "Not extracted")}</p>
          </div>
          <div class="compact-card">
            <span class="section-label">Matched Case</span>
            <p class="case-name">${escapeHtml(topCandidate?.case_name || "No candidate returned")}</p>
          </div>
        </div>

        <div class="summary-right">
          <div class="decision-snippet">
            <span class="section-label">Decision</span>
            <p>${escapeHtml(item.summary || "")}</p>
          </div>
          <span class="card-index">${String(index + 1).padStart(2, "0")}</span>
        </div>
      </summary>

      <div class="card-content">
        <div class="card-rail">
          <section class="inline-panel checks-panel">
            <span class="section-label">Verification Checks</span>
            ${renderChecks(item.checks || [])}
          </section>

          <section class="inline-panel meta-panel">
            <span class="section-label">Context</span>
            <div class="meta-grid">
              <div class="meta-line"><span>Document year</span><strong>${escapeHtml(item.metadata?.year || "N/A")}</strong></div>
              <div class="meta-line"><span>Filed</span><strong>${escapeHtml(topCandidate?.date_filed || "N/A")}</strong></div>
              <div class="meta-line"><span>Court</span><strong>${escapeHtml(topCandidate?.court || "N/A")}</strong></div>
              <div class="meta-line"><span>Reporter matches</span><strong>${escapeHtml(matchedCitationText || "N/A")}</strong></div>
            </div>
          </section>
        </div>

        <div class="card-footer">
          ${renderOptionalBlocks(item)}
        </div>
      </div>
    `;
    resultsBody.appendChild(card);
  });
}

function renderChecks(checks) {
  if (!checks.length) {
    return `<p class="empty-copy">No check details available.</p>`;
  }

  const items = checks.map((check) => `
    <li class="check-item">
      <div class="check-header">
        <strong>${escapeHtml(check.field)}</strong>
        <span class="mini-pill mini-pill-${escapeHtml(check.status)}">${escapeHtml(formatStatus(check.status))}</span>
      </div>
      ${check.expected ? `<div class="check-copy"><span>Expected</span><p>${escapeHtml(check.expected)}</p></div>` : ""}
      ${check.actual ? `<div class="check-copy"><span>Actual</span><p>${escapeHtml(check.actual)}</p></div>` : ""}
      <p class="check-summary">${escapeHtml(check.summary || "")}</p>
    </li>
  `).join("");
  return `<ul class="check-list">${items}</ul>`;
}

function renderOptionalBlocks(item) {
  const blocks = [];

  if (item.quote_snippet) {
    blocks.push(`
      <div class="footer-block">
        <span class="section-label">Quoted Language</span>
        <blockquote>${escapeHtml(item.quote_snippet)}</blockquote>
      </div>
    `);
  }

  if (item.id_references?.length) {
    const idItems = item.id_references.map((ref) => `
      <li>
        <strong>${escapeHtml(ref.raw_text)}</strong>
        ${ref.pin_cite_page ? `<span class="inline-meta">page ${escapeHtml(ref.pin_cite_page)}</span>` : ""}
        <p>${escapeHtml(ref.summary || "")}</p>
      </li>
    `).join("");
    blocks.push(`
      <div class="footer-block">
        <span class="section-label">Id. References</span>
        <ul class="inline-list">${idItems}</ul>
      </div>
    `);
  }

  if (!blocks.length) {
    blocks.push(`
      <div class="footer-block">
        <span class="section-label">Notes</span>
        <p>No quote snippets or linked Id. references were detected for this citation.</p>
      </div>
    `);
  }

  return blocks.join("");
}

function formatStatus(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
