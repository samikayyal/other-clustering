(() => {
  let review = window.REVIEW;
  const readOnly = window.REVIEW_READ_ONLY;
  const legacy = window.REVIEW_LEGACY;
  let draft = null;
  let editingStopped = false;
  const root = document.querySelector("#review-root");
  const nav = document.querySelector("#question-nav");
  const saveStatus = document.querySelector("#save-status");
  const message = document.querySelector("#workspace-message");

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function answerById(question, processingId) {
    return question.answers.find(answer => answer.processing_id === processingId);
  }

  function decisionLabel(decision) {
    if (!decision) return "No saved decision";
    if (decision.decision === "existing_choice") return `Existing choice ${decision.selected_choice_value}`;
    return `New category: ${decision.english_label} / ${decision.arabic_label}`;
  }

  function proposalLabel(proposal) {
    if (proposal.decision === "existing_choice") return `Match existing choice ${proposal.selected_choice_value}`;
    if (proposal.decision === "new_category") return `Create ${proposal.english_label} / ${proposal.arabic_label}`;
    if (proposal.provider_error) return "Provider suggestion unavailable";
    return "No accepted provider suggestion";
  }

  function impact(question, members) {
    return members.reduce((total, id) => total + answerById(question, id).occurrence_count, 0);
  }

  function renderLegacy() {
    nav.innerHTML = review.questions.map((question, index) =>
      `<a class="question-nav-item" href="#question-${escapeHtml(question.question_id)}">${index + 1}. ${escapeHtml(question.question_id)}</a>`
    ).join("");
    root.innerHTML = review.questions.map((question, index) => {
      const groups = question.clusters.map(group => {
        const answers = group.member_processing_ids.map(id => answerById(question, id));
        return `<article class="review-item cluster-card">
          <div class="cluster-heading"><strong>Suggested group</strong><span class="state-pill">View only</span></div>
          <p><strong>Saved decision:</strong> ${escapeHtml(decisionLabel(group.analyst_decision))}</p>
          <ul>${answers.map(answer => `<li>${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count} responses)</span></li>`).join("")}</ul>
        </article>`;
      }).join("");
      const unresolved = question.unresolved_answers.map(item => {
        const answer = answerById(question, item.processing_id);
        return `<li>${escapeHtml(answer.text)} <span class="metadata">${escapeHtml(decisionLabel(item.analyst_decision))}</span></li>`;
      }).join("");
      return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
        <header class="question-header"><p class="eyebrow">Question ${index + 1}</p><h2>${escapeHtml(question.question_text.english)}</h2><p class="arabic">${escapeHtml(question.question_text.arabic)}</p></header>
        <section class="subcard"><h3>Saved groups</h3>${groups || "<p>No groups.</p>"}</section>
        <section class="subcard"><h3>Unresolved answers</h3><ul>${unresolved || "<li>None</li>"}</ul></section>
      </section>`;
    }).join("");
  }

  function render() {
    if (legacy) { renderLegacy(); return; }
    nav.innerHTML = review.questions.map((question, index) => {
      const groups = question.workspace.active_groups;
      const confirmed = groups.filter(group => group.review_state === "confirmed").length;
      return `<a class="question-nav-item" href="#question-${escapeHtml(question.question_id)}"><span>${index + 1}. ${escapeHtml(question.question_id)}</span><span>${confirmed}/${groups.length}</span></a>`;
    }).join("");
    root.innerHTML = review.questions.map(renderQuestion).join("");
    bindControls();
    updateProgress();
  }

  function renderQuestion(question, index) {
    const groups = question.workspace.active_groups.map(group => renderGroup(question, group)).join("");
    const needsAttention = question.workspace.needs_attention.map(id => answerById(question, id));
    return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
      <header class="question-header"><p class="eyebrow">Question ${index + 1}</p><h2>${escapeHtml(question.question_text.english)}</h2><p class="arabic">${escapeHtml(question.question_text.arabic)}</p></header>
      <section class="subcard"><h3>Active groups</h3>${groups || "<p>No active groups.</p>"}</section>
      <section class="subcard"><h3>Needs attention</h3><p class="metadata">${needsAttention.length} unique answers · ${impact(question, question.workspace.needs_attention)} respondent responses</p>
        <ul>${needsAttention.map(answer => `<li>${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count})</span></li>`).join("") || "<li>None</li>"}</ul>
      </section>
      <details class="subcard"><summary>History (${question.workspace.history.length})</summary><ol>${question.workspace.history.map(entry => `<li>${escapeHtml(entry.operation.replaceAll("_", " "))} · revision ${entry.revision} · ${entry.affected_answer_count} unique / ${entry.affected_response_count} responses</li>`).join("") || "<li>No saved review actions.</li>"}</ol></details>
    </section>`;
  }

  function renderGroup(question, group) {
    const proposal = question.automatic_groups.find(item => item.group_id === group.group_id)?.provider_proposal;
    const members = group.member_processing_ids.map(id => answerById(question, id));
    const groupDraft = draft?.questionId === question.question_id && draft?.groupId === group.group_id ? draft : null;
    const anotherDraft = draft && !groupDraft;
    const options = question.existing_choices.map(choice => `<option value="existing_choice:${choice.value}">${choice.value} · ${escapeHtml(choice.english_label)} · ${escapeHtml(choice.arabic_label)}</option>`).join("");
    const savedValue = group.decision?.decision === "existing_choice" ? `existing_choice:${group.decision.selected_choice_value}` : group.decision?.decision || "";
    return `<article class="review-item cluster-card" data-group-card="${escapeHtml(group.group_id)}">
      <div class="cluster-heading"><strong>Review group</strong><span class="state-pill ${group.review_state}">${group.review_state === "confirmed" ? "Confirmed" : "Needs review"}</span></div>
      <p class="metadata">${members.length} unique answers · ${impact(question, group.member_processing_ids)} respondent responses</p>
      <ul>${members.map(answer => `<li>${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count})</span></li>`).join("")}</ul>
      <p><strong>Provider proposal:</strong> ${escapeHtml(proposalLabel(proposal))}</p>
      <p><strong>Saved decision:</strong> ${escapeHtml(decisionLabel(group.decision))}</p>
      ${readOnly ? "" : `<div class="decision-controls">
        <label for="decision-${escapeHtml(group.group_id)}">Edit coding decision</label>
        <select id="decision-${escapeHtml(group.group_id)}" data-decision-select data-question="${escapeHtml(question.question_id)}" data-group="${escapeHtml(group.group_id)}" ${anotherDraft || editingStopped ? "disabled" : ""}>
          <option value="" ${savedValue === "" ? "selected" : ""}>Choose a decision…</option><optgroup label="Existing choices">${options}</optgroup>
          <option value="new_category" ${savedValue === "new_category" ? "selected" : ""}>Create a new bilingual category</option>
        </select>
        ${groupDraft ? renderDraft(groupDraft) : ""}
        <button class="primary" type="button" data-confirm-group data-question="${escapeHtml(question.question_id)}" data-group="${escapeHtml(group.group_id)}" ${!group.decision || draft || editingStopped || group.review_state === "confirmed" ? "disabled" : ""}>Confirm group</button>
      </div>`}
    </article>`;
  }

  function renderDraft(value) {
    const labels = value.decision.decision === "new_category" ? `<div class="labels">
      <label>English label<input data-draft-label="english_label" value="${escapeHtml(value.decision.english_label)}"></label>
      <label>Arabic label<input class="arabic" data-draft-label="arabic_label" value="${escapeHtml(value.decision.arabic_label)}"></label>
    </div>` : "";
    return `<section class="draft-panel" aria-label="Unsaved decision draft"><p><strong>Unsaved draft</strong> — saved state is unchanged.</p>${labels}
      <div class="draft-actions"><button class="primary" type="button" data-apply-draft>Apply decision changes</button><button class="secondary-action" type="button" data-discard-draft>Discard draft</button></div></section>`;
  }

  function bindControls() {
    document.querySelectorAll("[data-decision-select]").forEach(select => select.addEventListener("change", () => {
      if (!select.value) return;
      const [kind, selected] = select.value.split(":");
      draft = {questionId: select.dataset.question, groupId: select.dataset.group,
        decision: kind === "existing_choice"
          ? {decision: kind, selected_choice_value: Number(selected), english_label: null, arabic_label: null}
          : {decision: "new_category", selected_choice_value: null, english_label: "", arabic_label: ""}};
      render();
      document.querySelector("[data-apply-draft]")?.focus();
    }));
    document.querySelectorAll("[data-draft-label]").forEach(input => input.addEventListener("input", () => { draft.decision[input.dataset.draftLabel] = input.value; }));
    document.querySelector("[data-discard-draft]")?.addEventListener("click", () => {
      const groupId = draft.groupId; draft = null; render();
      document.querySelector(`[data-group-card="${CSS.escape(groupId)}"] [data-decision-select]`)?.focus();
      showMessage("Draft discarded. Saved state was not changed.", false);
    });
    document.querySelector("[data-apply-draft]")?.addEventListener("click", () => sendCommand({type: "apply_decision", question_id: draft.questionId, group_id: draft.groupId, decision: draft.decision}, "Decision changes applied."));
    document.querySelectorAll("[data-confirm-group]").forEach(button => button.addEventListener("click", () => sendCommand({type: "confirm_group", question_id: button.dataset.question, group_id: button.dataset.group}, "Group confirmed.")));
  }

  async function sendCommand(command, successMessage) {
    saveStatus.textContent = "Saving…";
    const response = await fetch("/api/commands", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({expected_revision: review.revision, command})});
    const result = await response.json();
    if (!response.ok) {
      saveStatus.textContent = "Change not saved";
      if (response.status === 409) {
        editingStopped = true; draft = null;
        showMessage(`${result.error}. Reload latest state to continue.`, true, true); render(); return;
      }
      showMessage(result.error || "Change was not saved.", true); return;
    }
    review = result.review; draft = null; saveStatus.textContent = "All changes saved"; render(); showMessage(successMessage, false);
  }

  function showMessage(text, error, reload = false) {
    message.className = error ? "workspace-message warning" : "workspace-message success";
    message.innerHTML = `${escapeHtml(text)}${reload ? ' <button type="button" data-reload-latest>Reload latest state</button>' : ""}`;
    document.querySelector("[data-reload-latest]")?.addEventListener("click", () => window.location.reload());
  }

  function updateProgress() {
    const groups = review.questions.flatMap(question => question.workspace.active_groups);
    const confirmed = groups.filter(group => group.review_state === "confirmed").length;
    document.querySelector("#sidebar-completion-count").textContent = `${confirmed}/${groups.length}`;
    document.querySelector("#progress-bar").style.width = `${groups.length ? confirmed / groups.length * 100 : 0}%`;
  }

  render();
})();
