const $ = (id) => document.getElementById(id);

async function loadPreset(id) {
  if (id === "custom") return;
  const res = await fetch(`/api/scenarios/${id}`);
  if (!res.ok) throw new Error("加载预设失败");
  const data = await res.json();
  $("company").value = data.company || "";
  $("region").value = data.region || "";
  $("business_type").value = data.business_type || "";
  $("service_mode").value = data.service_mode || "";
  $("facts").value = (data.facts_from_source || []).join("\n");
}

function scenarioPayload() {
  const facts = $("facts").value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  return {
    company: $("company").value.trim(),
    region: $("region").value.trim(),
    business_type: $("business_type").value.trim(),
    service_mode: $("service_mode").value.trim(),
    facts_from_source: facts,
    cross_border: true,
  };
}

function renderTrace(trace) {
  const ol = $("trace");
  ol.innerHTML = "";
  (trace || []).forEach((step) => {
    const li = document.createElement("li");
    li.innerHTML = `<div class="node">${step.node}</div>
      <div class="meta">${step.elapsed_ms || 0} ms · ${step.note || ""} · hits=${step.hit_count || 0}</div>`;
    ol.appendChild(li);
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderRisks(risks) {
  const box = $("risks");
  const stats = $("riskStats");
  box.innerHTML = "";
  const list = risks || [];
  if (!list.length) {
    stats.textContent = "无风险条目";
    box.innerHTML = `<p class="empty">本轮没有风险条目（可能因缺字段已 hold）。</p>`;
    return;
  }

  const counts = { supported: 0, assumption: 0, missing: 0, conflict: 0 };
  list.forEach((r) => {
    const key = r.status || "assumption";
    counts[key] = (counts[key] || 0) + 1;
  });
  stats.textContent = [
    `共 ${list.length} 条`,
    counts.supported ? `supported ${counts.supported}` : "",
    counts.conflict ? `conflict ${counts.conflict}` : "",
    counts.assumption ? `assumption ${counts.assumption}` : "",
    counts.missing ? `missing ${counts.missing}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  list.forEach((r, i) => {
    const allowed = ["supported", "assumption", "missing", "conflict"];
    const status = allowed.includes(r.status) ? r.status : "assumption";
    const level = ["low", "medium", "high"].includes(r.level) ? r.level : "medium";
    const ids = (r.evidence_ids || []).filter(Boolean);
    const card = document.createElement("article");
    card.className = `risk-card status-${status}`;
    card.innerHTML = `
      <header class="risk-head">
        <span class="risk-index">#${i + 1}</span>
        <span class="badge status">${escapeHtml(status)}</span>
        <span class="badge level">${escapeHtml(level)}</span>
      </header>
      <p class="risk-text">${escapeHtml(r.text)}</p>
      <footer class="risk-meta">
        <span>证据</span>
        <span class="evidence-ids">${
          ids.length
            ? ids.map((id) => `<code>${escapeHtml(id)}</code>`).join("")
            : "（无）"
        }</span>
      </footer>`;
    box.appendChild(card);
  });
}

function showQuestions(questions) {
  const box = $("questionsBox");
  const ul = $("questions");
  ul.innerHTML = "";
  if (!questions || !questions.length) {
    box.classList.add("hidden");
    $("resume").disabled = true;
    return;
  }
  questions.forEach((q) => {
    const li = document.createElement("li");
    li.textContent = q;
    ul.appendChild(li);
  });
  box.classList.remove("hidden");
  $("resume").disabled = false;
}

async function run(supplements = null) {
  const status = $("status");
  const preset = $("preset").value;
  status.textContent = "运行中（本机模型可能要几十秒）…";
  $("run").disabled = true;
  $("resume").disabled = true;

  const body = {
    save_as: preset === "custom" ? "custom" : preset,
  };
  if (preset !== "custom" && !supplements) {
    body.preset = preset;
    if ($("strip_company").checked) {
      body.supplements = { company: "" };
    }
  } else {
    body.scenario = scenarioPayload();
    if ($("strip_company").checked && !(supplements && supplements.company)) {
      body.scenario.company = "";
    }
  }
  if (supplements) {
    body.scenario = scenarioPayload();
    body.supplements = supplements;
    body.save_as = (preset === "custom" ? "custom" : preset) + "-resumed";
  }

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "运行失败");

    renderTrace(data.trace);
    renderRisks(data.risks);
    $("report").textContent = data.report || "";
    showQuestions(data.questions);

    const dl = $("download");
    if (data.saved_as) {
      dl.href = `/api/reports/${data.saved_as}/download`;
      dl.classList.remove("hidden");
    }
    status.textContent = data.held
      ? `已暂停（held）。缺口 ${data.questions.length} 项。saved=${data.saved_as}`
      : `完成。risks=${data.risks.length} · saved=${data.saved_as}`;
  } catch (err) {
    status.textContent = String(err.message || err);
  } finally {
    $("run").disabled = false;
  }
}

$("preset").addEventListener("change", () => {
  loadPreset($("preset").value).catch((e) => {
    $("status").textContent = String(e.message || e);
  });
});
$("run").addEventListener("click", () => run(null));
$("resume").addEventListener("click", () => {
  const company = $("fix_company").value.trim();
  const supplements = {};
  if (company) supplements.company = company;
  run(supplements);
});

loadPreset("aliyun").catch(() => {});
