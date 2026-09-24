"use strict";

const state = { sessionId: null, file: null, net: null, months: null };

const $ = (id) => document.getElementById(id);
const euro = new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" });
const pct = (v) => `${(v * 100).toFixed(1).replace(".", ",")} %`;

function show(id) { $(id).hidden = false; }

function busy(el, message) {
  el.className = "status";
  el.innerHTML = message ? `<span class="spinner"></span>${message}` : "";
}

function fail(el, message) {
  el.className = "status err";
  el.textContent = message;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `Errore ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch { /* risposta non JSON: resta il codice di stato */ }
    throw new Error(detail);
  }
  return response.json();
}

/* ---------------- caricamento ---------------- */

const drop = $("drop");
const fileInput = $("file");

["dragenter", "dragover"].forEach((evt) =>
  drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("over"); })
);
["dragleave", "drop"].forEach((evt) =>
  drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.remove("over"); })
);
drop.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) selectFile(file);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) selectFile(fileInput.files[0]);
});

function selectFile(file) {
  state.file = file;
  drop.querySelector("strong").textContent = file.name;
  $("btn-analyze").disabled = false;
  busy($("st-upload"), "");
}

$("btn-analyze").addEventListener("click", run);

async function run() {
  const status = $("st-upload");
  $("btn-analyze").disabled = true;
  busy(status, "Leggo il file…");

  try {
    const form = new FormData();
    form.append("file", state.file);
    const uploaded = await api("/api/upload", { method: "POST", body: form });
    state.sessionId = uploaded.session_id;
    state.months = uploaded.period.months;

    busy(status, "Gli agenti stanno lavorando: categorizzo, scelgo i concetti, scrivo e verifico…");
    const result = await api(`/api/session/${state.sessionId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ literacy_level: $("literacy").value }),
    });

    state.net = result.analysis.totals.net;
    renderQuadro(result.analysis, uploaded);
    renderExplanations(result.explanation, result.blocked);
    renderUsage(result.usage);
    busy(status, "");
    show("s-quadro"); show("s-explain"); show("s-sim"); show("s-ask"); show("s-usage");

    loadGaps();
    loadQuiz();
  } catch (error) {
    fail(status, error.message);
    $("btn-analyze").disabled = false;
  }
}

/* ---------------- quadro ---------------- */

function renderQuadro(analysis, uploaded) {
  const { income, expense, net } = analysis.totals;
  const months = uploaded.period.months || 1;

  $("quadro-period").textContent =
    `Dal ${itDate(uploaded.period.from)} al ${itDate(uploaded.period.to)} — ${months} mesi, ` +
    `${uploaded.source.rows_parsed} movimenti letti.`;

  $("totals").innerHTML = [
    tile("Entrate", income, "pos"),
    tile("Uscite", expense, "neg"),
    tile("Differenza", net, net >= 0 ? "pos" : "neg", `${euro.format(net / months)} al mese`),
  ].join("");

  const spending = analysis.categories
    .filter((c) => c.total < 0)
    .sort((a, b) => a.total - b.total);
  const max = Math.abs(spending[0]?.total || 1);

  $("bars").innerHTML = spending.map((c) => `
    <div class="bar-row">
      <span class="name">${esc(c.name)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${(Math.abs(c.total) / max * 100).toFixed(1)}%"></span></span>
      <span class="val">${euro.format(c.total)}</span>
    </div>`).join("");

  const rejected = uploaded.source.rows_rejected;
  const uncategorized = analysis.uncategorized.count;
  const notes = [];
  if (rejected) notes.push(`${rejected} righe non leggibili sono state scartate.`);
  if (uncategorized) notes.push(`${uncategorized} movimenti non erano classificabili dalla descrizione.`);
  $("rejected-note").textContent = notes.join(" ");
}

function tile(label, value, tone, sub = "") {
  return `<div class="tile">
    <div class="k">${label}</div>
    <div class="v ${tone}">${euro.format(value)}</div>
    ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}
  </div>`;
}

function itDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

/* ---------------- perimetro dei dati ---------------- */

async function loadGaps() {
  try {
    const { gaps } = await api(`/api/session/${state.sessionId}/gaps`);
    renderGaps(gaps);
  } catch { /* i gap sono un arricchimento: se falliscono, il percorso resta valido */ }
}

function renderGaps(gaps) {
    if (!gaps || !gaps.gaps.length) return;

    $("coverage-note").textContent = gaps.coverage_note;
    $("gaps").innerHTML = gaps.gaps.map((g) => {
      // I gap `dato_opaco` non sono costi mancanti: quella spesa è già dentro
      // i totali, se ne ignora solo la destinazione. Chiedere un importo qui
      // lo farebbe contare due volte.
      const missing = g.reason !== "dato_opaco";
      const input = missing
        ? `<div class="row">
             <label for="gap-${esc(g.id)}">Quanto spendi all'anno, se lo sai</label>
             <input type="number" id="gap-${esc(g.id)}" data-gap="${esc(g.id)}" min="0" step="10" placeholder="€ / anno" />
           </div>`
        : `<p class="muted">Questa spesa è già conteggiata nelle tue uscite: quello che manca
             è sapere in cosa è finita, non quanto è.</p>`;
      return `<div class="gap">
        <span class="tag">${esc(missing ? g.cadence : "già nelle uscite")}</span>
        <p>${esc(g.question)}</p>
        ${input}
      </div>`;
    }).join("");
    show("s-gaps");
}

$("btn-recalc").addEventListener("click", async () => {
  const status = $("st-gaps");
  const annual = {};
  document.querySelectorAll("[data-gap]").forEach((input) => {
    const value = parseFloat(input.value);
    if (Number.isFinite(value) && value > 0) annual[input.dataset.gap] = value;
  });

  if (!Object.keys(annual).length) {
    fail(status, "Indica almeno un importo annuale per vedere come cambia il quadro.");
    return;
  }

  busy(status, "Ricalcolo…");
  try {
    const { quadro } = await api(`/api/session/${state.sessionId}/gaps`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ annual_costs: annual }),
    });
    busy(status, "");
    renderCompare(quadro);
  } catch (error) {
    fail(status, error.message);
  }
});

function renderCompare(q) {
  const before = q.saldo_mensile_osservato;
  const after = q.saldo_mensile_corretto;
  $("compare").innerHTML = `
    <div class="compare">
      ${tile("Quello che sembrava", before, before >= 0 ? "pos" : "neg", "al mese, guardando solo l'estratto")}
      <span class="arrow">&rarr;</span>
      ${tile("Quello che è", after, after >= 0 ? "pos" : "neg", "al mese, con i costi annuali")}
    </div>
    <p class="muted" style="margin-top:14px">
      I ${euro.format(q.costi_annuali_dichiarati)} che hai indicato pesano
      ${euro.format(q.incidenza_mensile)} al mese. Non comparivano nell'estratto perché
      cadono una o due volte l'anno, fuori dalla finestra che hai caricato.
    </p>`;
  $("compare").hidden = false;
}

/* ---------------- spiegazioni ---------------- */

function renderExplanations(explanation, blocked) {
  $("explain").innerHTML = explanation.sections.map((s) => `
    <div class="explain">
      <h4>${esc(s.title)}</h4>
      <p>${esc(s.plain_text)}</p>
      <div class="numbers">
        ${s.user_numbers.map((n) => `<span class="chip">${esc(n.label)}: ${euro.format(n.value)}</span>`).join("")}
      </div>
    </div>`).join("");

  if (blocked && blocked.length) {
    $("explain-blocked").innerHTML = `
      <div class="blocked">
        <span class="rule">GUARDRAIL</span>
        <p>${blocked.length} sezione/i non sono state mostrate: la verifica non le ha approvate.
           Il sistema preferisce tacere piuttosto che rischiare di darti un consiglio finanziario.</p>
      </div>`;
  }
}

/* ---------------- simulatore ---------------- */

const sliders = {
  monthly: { el: $("sl-monthly"), out: $("out-monthly"), fmt: (v) => `${v} €` },
  months: { el: $("sl-months"), out: $("out-months"), fmt: (v) => `${v} mesi` },
  rate: { el: $("sl-rate"), out: $("out-rate"), fmt: (v) => `${(v / 10).toFixed(1).replace(".", ",")} %` },
  infl: { el: $("sl-infl"), out: $("out-infl"), fmt: (v) => `${(v / 10).toFixed(1).replace(".", ",")} %` },
};

Object.values(sliders).forEach(({ el, out, fmt }) => {
  const sync = () => { out.textContent = fmt(Number(el.value)); };
  el.addEventListener("input", sync);
  sync();
});

$("btn-sim").addEventListener("click", async () => {
  const status = $("st-sim");
  busy(status, "Calcolo e racconto lo scenario…");
  try {
    const payload = {
      scenario_type: "accantonamento_mensile",
      params: {
        monthly: Number(sliders.monthly.el.value),
        months: Number(sliders.months.el.value),
        annual_rate: Number(sliders.rate.el.value) / 1000,
        inflation_rate: Number(sliders.infl.el.value) / 1000,
      },
    };
    const result = await api(`/api/session/${state.sessionId}/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (result.blocked) {
      $("sim-result").hidden = true;
      fail(status, "Lo scenario non è stato approvato dalla verifica.");
      return;
    }

    busy(status, "");
    renderSimulation(result.simulation);
    renderUsage(result.usage);
  } catch (error) {
    fail(status, error.message);
  }
});

function renderSimulation(simulation) {
  const series = simulation.series;
  lineChart($("chart"), series);

  const last = series[series.length - 1];
  $("sim-narrative").textContent =
    `Dopo ${last.month} mesi avresti versato ${euro.format(last.contributed)}. ` +
    `Il saldo nominale sarebbe ${euro.format(last.value_nominal)}, ` +
    `ma con l'inflazione ipotizzata comprerebbe quanto ${euro.format(last.value_real)} di oggi.`;

  $("sim-assumptions").innerHTML = simulation.assumptions
    .map((a) => `<li>${esc(a)}</li>`).join("");

  const rows = series.filter((_, i) => i % Math.ceil(series.length / 12) === 0 || i === series.length - 1);
  $("sim-table").innerHTML = `
    <table class="data">
      <thead><tr><th>Mese</th><th>Versato</th><th>Nominale</th><th>Potere d'acquisto</th></tr></thead>
      <tbody>${rows.map((p) => `<tr>
        <td>${p.month}</td><td>${euro.format(p.contributed)}</td>
        <td>${euro.format(p.value_nominal)}</td><td>${euro.format(p.value_real)}</td>
      </tr>`).join("")}</tbody>
    </table>`;

  $("sim-result").hidden = false;
}

function lineChart(container, series) {
  const W = 720, H = 280, PAD = { t: 16, r: 64, b: 34, l: 62 };
  const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;

  const xs = series.map((p) => p.month);
  const values = series.flatMap((p) => [p.value_nominal, p.value_real]);
  const yMax = Math.max(...values) * 1.08;
  const yMin = Math.min(0, ...values);

  const x = (m) => PAD.l + ((m - xs[0]) / (xs[xs.length - 1] - xs[0] || 1)) * plotW;
  const y = (v) => PAD.t + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  const path = (key) => series.map((p, i) => `${i ? "L" : "M"}${x(p.month).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(" ");

  const ticks = 4;
  const gridLines = Array.from({ length: ticks + 1 }, (_, i) => {
    const v = yMin + (yMax - yMin) * (i / ticks);
    return `<line class="grid-line" x1="${PAD.l}" y1="${y(v)}" x2="${W - PAD.r}" y2="${y(v)}" />
            <text class="axis-label" x="${PAD.l - 8}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)} €</text>`;
  }).join("");

  const xTicks = [xs[0], xs[Math.floor(xs.length / 2)], xs[xs.length - 1]].map(
    (m) => `<text class="axis-label" x="${x(m)}" y="${H - 12}" text-anchor="middle">mese ${m}</text>`
  ).join("");

  const last = series[series.length - 1];

  container.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Andamento del capitale accantonato nel tempo">
      ${gridLines}${xTicks}
      <path class="series-line" d="${path("value_nominal")}" stroke="var(--purple)" />
      <path class="series-line" d="${path("value_real")}" stroke="var(--teal)" />
      <circle cx="${x(last.month)}" cy="${y(last.value_nominal)}" r="4.5" fill="var(--purple)" stroke="var(--surface)" stroke-width="2" />
      <circle cx="${x(last.month)}" cy="${y(last.value_real)}" r="4.5" fill="var(--teal)" stroke="var(--surface)" stroke-width="2" />
      <text class="axis-label" x="${x(last.month) + 10}" y="${y(last.value_nominal) + 4}" fill="var(--purple-light)">${Math.round(last.value_nominal)} €</text>
      <text class="axis-label" x="${x(last.month) + 10}" y="${y(last.value_real) + 4}" fill="var(--teal)">${Math.round(last.value_real)} €</text>
      <line id="crosshair" class="grid-line" y1="${PAD.t}" y2="${PAD.t + plotH}" stroke="var(--purple-light)" opacity="0" />
      <rect id="hit" x="${PAD.l}" y="${PAD.t}" width="${plotW}" height="${plotH}" fill="transparent" />
    </svg>
    <div class="tooltip" id="tip"></div>`;

  const svg = container.querySelector("svg");
  const tip = container.querySelector("#tip");
  const crosshair = container.querySelector("#crosshair");

  container.querySelector("#hit").addEventListener("mousemove", (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    const ratio = (px - PAD.l) / plotW;
    const index = Math.max(0, Math.min(series.length - 1, Math.round(ratio * (series.length - 1))));
    const point = series[index];

    crosshair.setAttribute("x1", x(point.month));
    crosshair.setAttribute("x2", x(point.month));
    crosshair.setAttribute("opacity", "0.6");

    tip.innerHTML = `
      <div class="t-head">Mese ${point.month}</div>
      <div class="t-row"><span>Versato</span><span>${euro.format(point.contributed)}</span></div>
      <div class="t-row"><span>Nominale</span><span>${euro.format(point.value_nominal)}</span></div>
      <div class="t-row"><span>Potere d'acquisto</span><span>${euro.format(point.value_real)}</span></div>`;
    tip.style.opacity = "1";
    tip.style.left = `${Math.min(box.width - 190, (x(point.month) / W) * box.width + 12)}px`;
    tip.style.top = `${(y(point.value_nominal) / H) * box.height - 10}px`;
  });

  container.querySelector("#hit").addEventListener("mouseleave", () => {
    tip.style.opacity = "0";
    crosshair.setAttribute("opacity", "0");
  });
}

/* ---------------- domanda libera ---------------- */

$("btn-ask").addEventListener("click", ask);
$("question").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });

async function ask() {
  const question = $("question").value.trim();
  if (question.length < 3) return;

  const status = $("st-ask");
  busy(status, "Preparo la risposta e la faccio verificare…");
  $("ask-result").innerHTML = "";

  try {
    const result = await api(`/api/session/${state.sessionId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    busy(status, "");

    if (result.verdict === "pass") {
      $("ask-result").innerHTML = `
        <div class="explain" style="margin-top:18px">
          <h4>${esc(result.section.title)}</h4>
          <p>${esc(result.section.plain_text)}</p>
        </div>`;
    } else {
      const rules = [...new Set(result.violations.map((v) => v.rule_id))].join(" · ");
      $("ask-result").innerHTML = `
        <div class="blocked" style="margin-top:18px">
          <span class="rule">${esc(rules || "GUARDRAIL")}</span>
          <p>Questa domanda porta verso una scelta finanziaria, e non è una cosa che posso
             fare per te: non posso dirti dove investire, cosa disdire o cosa conviene scegliere.
             Posso però spiegarti i concetti che stanno sotto la domanda — provala a riformulare
             partendo da "cos'è" o "come funziona".</p>
        </div>`;
    }
    refreshUsage();
  } catch (error) {
    fail(status, error.message);
  }
}

/* ---------------- verifica ---------------- */

async function loadQuiz() {
  try {
    const result = await api(`/api/session/${state.sessionId}/quiz`);
    if (result.available) renderQuiz(result.quiz.questions);
  } catch { /* il percorso resta valido anche senza verifica */ }
}

function renderQuiz(questions) {
    if (!questions || !questions.length) return;
    let answered = 0, correct = 0;

    $("quiz").innerHTML = questions.map((q, qi) => `
      <div class="q">
        <div class="prompt">${esc(q.prompt)}</div>
        ${q.options.map((opt, oi) =>
          `<button class="opt" data-q="${qi}" data-o="${oi}">${esc(opt)}</button>`).join("")}
        <div class="feedback" id="fb-${qi}"></div>
      </div>`).join("");

    $("quiz").addEventListener("click", (event) => {
      const button = event.target.closest(".opt");
      if (!button || button.disabled) return;

      const qi = Number(button.dataset.q), oi = Number(button.dataset.o);
      const question = questions[qi];
      const right = oi === question.correct_index;

      document.querySelectorAll(`.opt[data-q="${qi}"]`).forEach((b) => {
        b.disabled = true;
        if (Number(b.dataset.o) === question.correct_index) b.classList.add("right");
      });
      if (!right) button.classList.add("wrong");

      $(`fb-${qi}`).textContent = right ? question.feedback.correct : question.feedback.incorrect;
      answered += 1;
      if (right) correct += 1;
      if (answered === questions.length) {
        $("quiz-score").textContent = `${correct} risposte corrette su ${questions.length}.`;
      }
    });

    show("s-quiz");
}

/* ---------------- replay di una sessione salvata ---------------- */

async function replaySession(sessionId) {
  const status = $("st-upload");
  busy(status, "Riapro la sessione salvata…");
  try {
    const r = await api(`/api/session/${sessionId}/replay`);
    state.sessionId = r.session_id;

    $("replay-banner").hidden = false;
    renderQuadro(r.analysis, r);
    renderGaps(r.gaps);
    if (r.quadro) renderCompare(r.quadro);
    renderExplanations(r.explanation, r.blocked);
    if (r.simulation) {
      renderSimulation(r.simulation);
      syncSliders(r.simulation.scenario.params);
    }
    if (r.quiz) renderQuiz(r.quiz.questions);
    renderUsage(r.usage);

    busy(status, "");
    ["s-quadro", "s-explain", "s-sim", "s-ask", "s-usage"].forEach(show);
    $("s-quadro").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    fail(status, error.message);
  }
}

function syncSliders(params) {
  const map = {
    monthly: ["monthly", (v) => v],
    months: ["months", (v) => v],
    annual_rate: ["rate", (v) => v * 1000],
    inflation_rate: ["infl", (v) => v * 1000],
  };
  for (const [key, [name, scale]] of Object.entries(map)) {
    if (params[key] === undefined) continue;
    const s = sliders[name];
    s.el.value = String(scale(params[key]));
    s.out.textContent = s.fmt(Number(s.el.value));
  }
}

$("btn-demo").addEventListener("click", () => replaySession("demo"));

/* ---------------- trasparenza ---------------- */

function renderUsage(usage) {
  if (!usage) return;
  const rows = Object.entries(usage.per_agent).map(([name, u]) => `
    <tr><td>${esc(name)}</td><td>${u.calls}</td><td>${u.input_tokens.toLocaleString("it-IT")}</td>
        <td>${u.output_tokens.toLocaleString("it-IT")}</td><td>${u.retries}</td></tr>`).join("");

  $("usage").innerHTML = `
    <table>
      <thead><tr><th>Agente</th><th>Chiamate</th><th>Token in</th><th>Token out</th><th>Retry</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td><strong>Totale</strong></td><td>${usage.total.calls}</td>
        <td><strong>${usage.total.input_tokens.toLocaleString("it-IT")}</strong></td>
        <td><strong>${usage.total.output_tokens.toLocaleString("it-IT")}</strong></td><td></td></tr></tfoot>
    </table>`;
}

async function refreshUsage() {
  try { renderUsage(await api(`/api/session/${state.sessionId}/usage`)); } catch { /* pannello non critico */ }
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
