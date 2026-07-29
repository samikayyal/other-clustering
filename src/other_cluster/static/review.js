(() => {
  let review = window.REVIEW;
  let readOnly = Boolean(window.REVIEW_READ_ONLY);
  const root = document.querySelector("#review-root");
  const nav = document.querySelector("#question-nav");
  const saveStatus = document.querySelector("#save-status");
  const analystName = document.querySelector("#analyst-name");
  let pendingSave = Promise.resolve();

  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  const questionById = id => review.questions.find(question => question.question_id === id);
  const answerById = (question, id) => question.answers.find(answer => answer.processing_id === id);
  const selected = (value, expected) => value === expected ? " selected" : "";

  function decisionLabel(decision) {
    if (!decision) return "Not decided";
    if (decision.decision === "existing_choice") return `Existing choice ${decision.selected_choice_value}`;
    if (decision.decision === "new_category") return `New category: ${decision.english_label}`;
    return "Unresolved";
  }

  function render() {
    nav.innerHTML = review.questions.map(question =>
      `<a href="#question-${escapeHtml(question.question_id)}">${escapeHtml(question.question_id)}</a>`
    ).join("");
    root.innerHTML = review.questions.map(renderQuestion).join("");
    bindControls();
    updateCount();
    if (analystName) {
      analystName.value = review.analyst_name || "";
      analystName.disabled = readOnly;
    }
    const status = document.querySelector("#review-status");
    if (status) status.textContent = review.status;
  }

  function renderQuestion(question) {
    const choices = question.existing_choices.map(choice =>
      `<li><strong>${choice.value}</strong> · ${escapeHtml(choice.english_label)} <span class="arabic">${escapeHtml(choice.arabic_label)}</span></li>`
    ).join("") || "<li>None</li>";
    const answers = question.answers.map(answer => {
      const mappings = answer.row_mappings.map(mapping => escapeHtml(mapping.coordinate)).join(", ");
      return `<div class="review-item"><p class="answer-text">${escapeHtml(answer.text)}</p>
        <p class="metadata">${answer.occurrence_count} occurrence${answer.occurrence_count === 1 ? "" : "s"} · ${escapeHtml(answer.processing_id)} · ${mappings}</p>
        ${renderEvidence(answer.discovery_evidence)}</div>`;
    }).join("") || "<p class='metadata'>No answers.</p>";
    const clusters = question.clusters.map(cluster => renderCluster(question, cluster)).join("") || "<p class='metadata'>No proposal-eligible clusters.</p>";
    const unresolved = question.unresolved_answers.map(item => renderUnresolved(question, item)).join("") || "<p class='metadata'>No unresolved discovery evidence.</p>";
    return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
      <header><p class="eyebrow">${escapeHtml(question.question_id)}</p>
        <h2>${escapeHtml(question.question_text.english)}</h2>
        <p class="arabic">${escapeHtml(question.question_text.arabic)}</p></header>
      <section class="subcard"><h3>Existing choices</h3><ul>${choices}</ul></section>
      <section class="subcard"><h3>Canonical answers and evidence</h3>${answers}</section>
      <section class="subcard"><h3>Fixed system clusters</h3>${clusters}</section>
      <section class="subcard"><h3>Noise and rare answers</h3>${unresolved}</section>
    </section>`;
  }

  function renderEvidence(evidence) {
    const probability = evidence.membership_probability === null || evidence.membership_probability === undefined
      ? "none" : Number(evidence.membership_probability).toFixed(3);
    return `<p class="metadata discovery-evidence">${escapeHtml(evidence.status || "none")} · raw label ${escapeHtml(evidence.raw_cluster_label ?? "none")} · probability ${probability} · cluster ${escapeHtml(evidence.cluster_id ?? "none")}</p>`;
  }

  function renderChoiceOptions(question, value) {
    return `<option value="">Choose…</option>` + question.existing_choices.map(choice =>
      `<option value="${choice.value}"${selected(String(value), String(choice.value))}>${choice.value} · ${escapeHtml(choice.english_label)} · ${escapeHtml(choice.arabic_label)}</option>`
    ).join("");
  }

  function renderCluster(question, cluster) {
    const decision = cluster.analyst_decision;
    const current = decision ? decision.decision : "";
    const proposal = cluster.gemini_proposal;
    const members = cluster.members.map(member =>
      `<li><span class="answer-text">${escapeHtml(member.text)}</span> <span class="metadata">${member.occurrence_count} occurrence${member.occurrence_count === 1 ? "" : "s"} · probability ${Number(member.membership_probability).toFixed(3)}</span></li>`
    ).join("");
    const controls = readOnly
      ? `<p class="final-decision"><strong>${escapeHtml(decisionLabel(decision))}</strong>${decision && decision.allocated_value !== null ? ` · allocated value ${decision.allocated_value}` : ""}</p>`
      : `<label>Whole-cluster disposition<select data-cluster-decision="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}">
          <option value=""${selected(current, "")}>Choose…</option>
          <option value="existing_choice"${selected(current, "existing_choice")}>Existing choice</option>
          <option value="new_category"${selected(current, "new_category")}>New bilingual category</option>
          <option value="unresolved"${selected(current, "unresolved")}>Unresolved</option>
        </select></label>
        ${current === "existing_choice" ? `<label>Existing choice<select data-cluster-choice="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}">${renderChoiceOptions(question, decision.selected_choice_value)}</select></label>` : ""}
        ${current === "new_category" ? `<div class="labels"><label>English label<input data-cluster-label="english_label" data-cluster="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(decision.english_label)}"></label><label>Arabic label<input class="arabic" data-cluster-label="arabic_label" data-cluster="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(decision.arabic_label)}"></label></div>` : ""}`;
    return `<article class="review-item cluster-card"><div class="cluster-heading"><strong>${escapeHtml(cluster.cluster_id)}</strong><span class="metadata">raw label ${cluster.raw_cluster_label} · ${cluster.member_processing_ids.length} canonical members</span></div>
      <p class="proposal"><strong>Gemini proposal:</strong> ${escapeHtml(proposal.decision)}${proposal.english_label ? ` · ${escapeHtml(proposal.english_label)} / ${escapeHtml(proposal.arabic_label)}` : ""}${proposal.selected_choice_value !== null ? ` · choice ${proposal.selected_choice_value}` : ""}${proposal.rejection_reason ? ` · ${escapeHtml(proposal.rejection_reason)}` : ""}${proposal.provider_error ? ` · ${escapeHtml(proposal.provider_error)}` : ""}</p>
      <ul class="member-list">${members}</ul><div class="decision-controls">${controls}</div></article>`;
  }

  function renderUnresolved(question, item) {
    const answer = answerById(question, item.processing_id);
    const decision = item.analyst_decision;
    const current = decision ? decision.decision : "";
    const controls = readOnly
      ? `<p class="final-decision"><strong>${escapeHtml(decisionLabel(decision))}</strong></p>`
      : `<label>Disposition<select data-unresolved-decision="${escapeHtml(item.processing_id)}" data-question="${escapeHtml(question.question_id)}">
          <option value=""${selected(current, "")}>Choose…</option><option value="existing_choice"${selected(current, "existing_choice")}>Existing choice</option><option value="unresolved"${selected(current, "unresolved")}>Unresolved</option>
        </select></label>${current === "existing_choice" ? `<label>Existing choice<select data-unresolved-choice="${escapeHtml(item.processing_id)}" data-question="${escapeHtml(question.question_id)}">${renderChoiceOptions(question, decision.selected_choice_value)}</select></label>` : ""}`;
    return `<article class="review-item"><p class="answer-text">${escapeHtml(answer ? answer.text : item.processing_id)}</p><p class="metadata">reason: ${escapeHtml(item.reason)} · ${escapeHtml(item.processing_id)}</p><div class="decision-controls">${controls}</div></article>`;
  }

  function freshDecision(kind, previous = null) {
    if (kind === "new_category") {
      return {decision: kind, selected_choice_value: null, english_label: previous?.english_label || "", arabic_label: previous?.arabic_label || "", allocated_value: null};
    }
    if (kind === "existing_choice") {
      return {decision: kind, selected_choice_value: null, english_label: null, arabic_label: null, allocated_value: null};
    }
    return {decision: "unresolved", selected_choice_value: null, english_label: null, arabic_label: null, allocated_value: null};
  }

  function cluster(questionId, clusterId) {
    return questionById(questionId).clusters.find(item => item.cluster_id === clusterId);
  }

  function unresolved(questionId, processingId) {
    return questionById(questionId).unresolved_answers.find(item => item.processing_id === processingId);
  }

  function bindControls() {
    if (readOnly) return;
    document.querySelectorAll("[data-cluster-decision]").forEach(select => select.addEventListener("change", () => {
      const item = cluster(select.dataset.question, select.dataset.cluster);
      item.analyst_decision = select.value ? freshDecision(select.value, item.analyst_decision) : null;
      render();
      if (select.value === "unresolved") save(false);
    }));
    document.querySelectorAll("[data-cluster-choice]").forEach(select => select.addEventListener("change", () => {
      const item = cluster(select.dataset.question, select.dataset.cluster);
      if (item.analyst_decision) item.analyst_decision.selected_choice_value = select.value ? Number(select.value) : null;
      save(false);
    }));
    document.querySelectorAll("[data-cluster-label]").forEach(input => input.addEventListener("change", () => {
      const item = cluster(input.dataset.question, input.dataset.cluster);
      if (item.analyst_decision) item.analyst_decision[input.dataset.clusterLabel] = input.value;
      save(false);
    }));
    document.querySelectorAll("[data-unresolved-decision]").forEach(select => select.addEventListener("change", () => {
      const item = unresolved(select.dataset.question, select.dataset.unresolvedDecision);
      item.analyst_decision = select.value ? freshDecision(select.value) : null;
      render();
      if (select.value === "unresolved") save(false);
    }));
    document.querySelectorAll("[data-unresolved-choice]").forEach(select => select.addEventListener("change", () => {
      const item = unresolved(select.dataset.question, select.dataset.unresolvedChoice);
      if (item.analyst_decision) item.analyst_decision.selected_choice_value = select.value ? Number(select.value) : null;
      save(false);
    }));
  }

  function payload() {
    return {
      analyst_name: analystName ? analystName.value : review.analyst_name,
      questions: review.questions.map(question => ({
        question_id: question.question_id,
        clusters: question.clusters.map(item => ({cluster_id: item.cluster_id, analyst_decision: item.analyst_decision})),
        unresolved_answers: question.unresolved_answers.map(item => ({processing_id: item.processing_id, analyst_decision: item.analyst_decision}))
      }))
    };
  }

  function save(rerender) {
    if (readOnly) return;
    saveStatus.textContent = "Saving…";
    pendingSave = pendingSave.then(async () => {
      const response = await fetch("/api/review", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload())});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Review edit was not saved");
      review = result.review;
      saveStatus.textContent = "Saved";
      if (rerender) render();
    }).catch(error => {
      saveStatus.textContent = "Edit not saved";
      showMessage(error.message, true);
    });
    updateCount();
  }

  function updateCount() {
    const all = review.questions.flatMap(question => [...question.clusters, ...question.unresolved_answers]);
    const decided = all.filter(item => item.analyst_decision).length;
    const count = document.querySelector("#completion-count");
    if (count) count.textContent = `${decided} / ${all.length} evidence decisions made`;
  }

  function showMessage(message, error) {
    const target = document.querySelector("#completion-message");
    if (!target) { alert(message); return; }
    target.textContent = message;
    target.className = error ? "warning" : "success";
  }

  if (analystName && !readOnly) analystName.addEventListener("change", () => save(false));
  const completeButton = document.querySelector("#complete-review");
  if (completeButton) completeButton.addEventListener("click", async () => {
    await pendingSave;
    showMessage("Validating every cluster and unresolved answer…", false);
    const response = await fetch("/api/complete", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload())});
    const result = await response.json();
    if (!response.ok) { showMessage(result.error || "Review cannot be completed", true); return; }
    review = result.review;
    readOnly = true;
    completeButton.disabled = true;
    render();
    showMessage("Review complete. Allocated values are now read-only.", false);
  });

  render();
})();
