const API = "https://inspirehep.net/api/literature";
const FIELDS = "control_number,titles,publication_info,preprint_date";
const BUCKETS = 128;
const RECORD_BYTES = 24;
const examples = new Map([
  [1492249, { id: 1492249, title: "Strong coupling constant from Adler function in lattice QCD", year: "2016" }],
  [4180, { id: 4180, title: "The foundation of the general theory of relativity", year: "1916" }],
  [451647, { id: 451647, title: "The Large N Limit of Superconformal Field Theories and Supergravity", year: "1997" }],
]);
const $ = (id) => document.getElementById(id);
const counts = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const percentages = new Intl.NumberFormat(undefined, {
  style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero",
});
const cache = new Map();
let currentRequest = 0;
let selected = null;

function setStatus(message = "") {
  $("status").textContent = message;
  $("status").hidden = !message;
}

function metadata(record) {
  const info = record.metadata || {};
  return {
    id: Number(info.control_number || record.id),
    title: (info.titles?.[0]?.title || "Untitled record").replace(/\$/g, ""),
    year: String(info.preprint_date || info.publication_info?.[0]?.year || "").slice(0, 4),
  };
}

async function json(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" });

function showDate(id, value) {
  const date = new Date(value || "");
  if (Number.isFinite(date.valueOf())) {
    $(id).dateTime = date.toISOString();
    $(id).textContent = dateFormat.format(date);
  } else {
    $(id).textContent = "Unavailable";
  }
}

async function showFreshness() {
  let snapshot;
  try {
    snapshot = await json(new URL("./snapshot.json", import.meta.url));
  } catch {
    return;
  }
  showDate("snapshot-date", snapshot.archive_last_modified);
  showDate("checked-date", snapshot.checked_at);
  $("freshness").hidden = false;

  if (!/^[\w.-]+\/[\w.-]+$/.test(snapshot.repository || "")) return;
  const runsUrl = new URL(`https://api.github.com/repos/${snapshot.repository}/actions/workflows/pages.yml/runs`);
  runsUrl.search = new URLSearchParams({ branch: "main", event: "schedule", status: "success", per_page: "1" });
  try {
    const runs = await json(runsUrl);
    const lastScheduled = runs.workflow_runs?.[0]?.run_started_at;
    if (Date.parse(lastScheduled) > Date.parse(snapshot.checked_at)) showDate("checked-date", lastScheduled);
  } catch {
    // The published check date stays visible if the public API is unavailable.
  }
}

async function bucketData(bucket) {
  const filename = `scores-${String(bucket).padStart(3, "0")}.bin.gz`;
  const response = await fetch(new URL(`./data/${filename}`, import.meta.url));
  if (!response.ok) throw new Error(`Score data unavailable (HTTP ${response.status})`);
  const bytes = await response.arrayBuffer();
  const compressed = new Uint8Array(bytes, 0, Math.min(bytes.byteLength, 2));
  let raw = bytes;
  if (compressed[0] === 31 && compressed[1] === 139) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    raw = await new Response(stream).arrayBuffer();
  }
  if (raw.byteLength % RECORD_BYTES) throw new Error("Invalid score data");
  return new DataView(raw);
}

async function readScore(id) {
  const bucket = id % BUCKETS;
  if (!cache.has(bucket)) {
    cache.set(bucket, bucketData(bucket).catch((error) => {
      cache.delete(bucket);
      throw error;
    }));
  }
  const records = await cache.get(bucket);
  let first = 0;
  let last = records.byteLength / RECORD_BYTES;
  while (first < last) {
    const middle = Math.floor((first + last) / 2);
    const position = middle * RECORD_BYTES;
    const current = records.getUint32(position, true);
    if (id === current) {
      return {
        direct: records.getUint32(position + 4, true),
        half: records.getFloat64(position + 8, true),
        one: records.getFloat64(position + 16, true),
      };
    }
    if (current < id) first = middle + 1;
    else last = middle;
  }
  return null;
}

function displayScore() {
  if (!selected) return;
  const { direct, half, one } = selected;
  const effective = document.querySelector('input[name="rate"]:checked').value === "1" ? one : half;
  const bonus = effective - direct;
  $("direct").textContent = counts.format(direct);
  $("effective").textContent = counts.format(effective);
  $("bonus").textContent = `+${counts.format(bonus)}`;
  $("increase").textContent = direct ? `${percentages.format(bonus / direct)} vs. direct` : "";
}

function clearMatches() {
  $("matches").replaceChildren();
  $("matches").hidden = true;
}

async function showPaper(id, paper) {
  const request = ++currentRequest;
  clearMatches();
  $("result").hidden = true;
  setStatus("Loading the paper’s scores…");
  try {
    const scores = await readScore(id);
    if (request !== currentRequest) return;
    if (!scores) {
      setStatus(`INSPIRE record ${id} has no score in this snapshot.`);
      return;
    }
    const known = paper || examples.get(id);
    const detail = known || await json(`${API}/${id}?fields=${FIELDS}`)
      .then(metadata).catch(() => ({ id, title: `INSPIRE record ${id}`, year: "" }));
    if (request !== currentRequest) return;

    selected = scores;
    $("paper-title").textContent = detail.title;
    $("paper-label").textContent = [`INSPIRE ${id}`, detail.year].filter(Boolean).join(" · ");
    $("paper-link").href = `https://inspirehep.net/literature/${id}`;
    displayScore();
    $("result").hidden = false;
    setStatus();
    const location = new URL(window.location.href);
    location.searchParams.set("paper", String(id));
    window.history.replaceState(null, "", location);
  } catch {
    if (request === currentRequest) setStatus("Couldn’t load the score data. Try again in a moment.");
  }
}

async function search(term) {
  const id = /^\d{1,10}$/.test(term) ? Number(term) : null;
  if (id && id <= 0xffffffff) return showPaper(id);
  const request = ++currentRequest;
  clearMatches();
  $("result").hidden = true;
  setStatus("Searching INSPIRE…");
  const query = term.replace(/["\\]/g, " ").trim();
  if (!query) {
    setStatus("Enter a paper title or INSPIRE ID.");
    return;
  }

  try {
    const url = new URL(API);
    url.search = new URLSearchParams({ q: `title:"${query}"`, size: "12", fields: FIELDS });
    const response = await json(url);
    if (request !== currentRequest) return;
    const papers = (response.hits?.hits || []).map(metadata)
      .filter((item) => Number.isInteger(item.id) && item.id > 0);
    if (!papers.length) {
      setStatus("No matching titles. Try a shorter phrase or enter the INSPIRE ID.");
      return;
    }
    if (papers.length === 1) return showPaper(papers[0].id, papers[0]);
    setStatus("Choose a matching paper.");
    const rows = papers.map((paper) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      const title = document.createElement("span");
      const year = document.createElement("small");
      button.type = "button";
      title.textContent = paper.title;
      year.textContent = paper.year || `#${paper.id}`;
      button.append(title, year);
      button.addEventListener("click", () => showPaper(paper.id, paper));
      li.append(button);
      return li;
    });
    $("matches").replaceChildren(...rows);
    $("matches").hidden = false;
  } catch {
    if (request === currentRequest) setStatus("INSPIRE title search is unavailable. Try an INSPIRE ID or an example paper.");
  }
}

$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const term = $("query").value.trim();
  if (term) search(term);
});

document.querySelectorAll("[data-paper]").forEach((button) => {
  button.addEventListener("click", () => {
    $("query").value = "";
    showPaper(Number(button.dataset.paper));
  });
});
document.querySelector(".rates").addEventListener("change", displayScore);
showFreshness();

const shared = new URLSearchParams(window.location.search).get("paper");
if (shared && /^\d{1,10}$/.test(shared) && Number(shared) <= 0xffffffff) showPaper(Number(shared));
else showPaper(1492249);
