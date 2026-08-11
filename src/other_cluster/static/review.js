(() => {
  let review = window.REVIEW;
  const readOnly = window.REVIEW_READ_ONLY;
  const legacy = window.REVIEW_LEGACY;
  let draft = null;
  let selection = null;
  let moveDestination = "";
  let undoQuestionId = null;
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

  function groupLabel(question, groupId) {
    const groups = [...question.workspace.active_groups, ...question.workspace.retired_groups];
    const group = groups.find(candidate => candidate.group_id === groupId);
    return group ? `Review group ${group.creation_order + 1}` : groupId;
  }

  function historyDescription(question, entry) {
    if (entry.operation === "exclude_answers") return `Excluded ${entry.affected_answer_count} answers from coding`;
    if (entry.operation === "restore_answers") return `Restored ${entry.affected_answer_count} answers to Needs attention`;
    if (entry.operation === "undo") {
      const labels = {move_answers: "move", create_group: "group creation", split_group: "group split", merge_groups: "merge", exclude_answers: "exclusion", restore_answers: "restoration"};
      return `Undid ${labels[entry.before.operation] || entry.before.operation}`;
    }
    if (entry.operation === "apply_decision") return `Changed the decision for ${groupLabel(question, entry.group_id)}`;
    if (entry.operation === "confirm_group") return `Confirmed ${groupLabel(question, entry.group_id)}`;
    if (entry.operation === "move_answers") return `Moved ${entry.affected_answer_count} answers`;
    if (entry.operation === "create_group") return `Created ${groupLabel(question, entry.group_id)}`;
    if (entry.operation === "split_group") {
      const retired = entry.after.groups.filter(group => group.retired).map(group => groupLabel(question, group.group_id));
      const retirement = retired.length ? `; retired ${retired.join(" and ")}` : "";
      return `Split selected answers into ${groupLabel(question, entry.group_id)}${retirement}`;
    }
    if (entry.operation === "merge_groups") {
      const source = groupLabel(question, entry.before.source_group.group_id);
      const destination = groupLabel(question, entry.before.destination_group.group_id);
      return `Merged ${source} into ${destination}; retired ${source}`;
    }
    return entry.operation.replaceAll("_", " ");
  }

  function clearMoveSelection() {
    selection = null;
    moveDestination = "";
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
      return `<a class="question-nav-item" data-question-nav="${escapeHtml(question.question_id)}" href="#question-${escapeHtml(question.question_id)}"><span>${index + 1}. ${escapeHtml(question.question_id)}</span><span>${confirmed}/${groups.length}</span></a>`;
    }).join("");
    root.innerHTML = review.questions.map(renderQuestion).join("");
    bindControls();
    updateProgress();
  }

  function renderQuestion(question, index) {
    const groups = question.workspace.active_groups.map(group => renderGroup(question, group)).join("");
    const needsAttention = question.workspace.needs_attention.map(id => answerById(question, id));
    const excluded = question.workspace.excluded_answers.map(id => answerById(question, id));
    const complete = !needsAttention.length && question.workspace.active_groups.every(group => group.review_state === "confirmed");
    const latestExclusion = [...question.workspace.history].reverse().find(entry => entry.operation === "exclude_answers");
    const canUndo = !readOnly && !editingStopped && undoQuestionId === question.question_id && question.workspace.undo;
    return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
      <header class="question-header"><p class="eyebrow">Question ${index + 1}</p><h2>${escapeHtml(question.question_text.english)}</h2><p class="arabic">${escapeHtml(question.question_text.arabic)}</p><span class="state-pill ${complete ? "confirmed" : "needs_review"}">${complete ? "Complete" : "Outstanding"}</span></header>
      ${canUndo ? `<button class="secondary-action" type="button" data-undo data-question="${escapeHtml(question.question_id)}">${escapeHtml(undoLabel(question.workspace.undo.operation))}</button>` : ""}
      ${renderSelectionActions(question)}
      ${renderRestoreActions(question)}
      <section class="subcard"><h3>Active groups</h3>${groups || "<p>No active groups.</p>"}</section>
      <section class="subcard"><h3>Needs attention</h3><p class="metadata">${needsAttention.length} unique answers · ${impact(question, question.workspace.needs_attention)} respondent responses</p>
        <ul class="answer-selection-list">${needsAttention.map(answer => `<li>${renderAnswerSelection(question, answer)}</li>`).join("") || "<li>None</li>"}</ul>
      </section>
      <details class="subcard" aria-label="Excluded from coding"><summary>Excluded from coding (${excluded.length} unique answers · ${impact(question, question.workspace.excluded_answers)} respondent responses)</summary>
        <p class="metadata">${latestExclusion ? `Latest exclusion ${escapeHtml(latestExclusion.timestamp_utc)}` : "No exclusions recorded"}</p>
        <ul class="answer-selection-list">${excluded.map(answer => `<li>${renderRestoreSelection(question, answer)}</li>`).join("") || "<li>None</li>"}</ul>
      </details>
      <details class="subcard"><summary>History (${question.workspace.history.length})</summary><ol>${question.workspace.history.map(entry => `<li>${escapeHtml(historyDescription(question, entry))} · revision ${entry.revision} · ${entry.affected_answer_count} unique / ${entry.affected_response_count} responses</li>`).join("") || "<li>No saved review actions.</li>"}</ol></details>
    </section>`;
  }

  function undoLabel(operation) {
    const labels = {move_answers: "Undo move", create_group: "Undo group creation", split_group: "Undo group split", merge_groups: "Undo merge", exclude_answers: "Undo exclusion", restore_answers: "Undo restoration"};
    return labels[operation] || "Undo latest change";
  }

  function renderGroup(question, group) {
    const proposal = question.automatic_groups.find(item => item.group_id === group.group_id)?.provider_proposal;
    const members = group.member_processing_ids.map(id => answerById(question, id));
    const groupDraft = draft?.questionId === question.question_id && draft?.groupId === group.group_id ? draft : null;
    const anotherDraft = draft && !groupDraft;
    const options = question.existing_choices.map(choice => `<option value="existing_choice:${choice.value}">${choice.value} · ${escapeHtml(choice.english_label)} · ${escapeHtml(choice.arabic_label)}</option>`).join("");
    const savedValue = group.decision?.decision === "existing_choice" ? `existing_choice:${group.decision.selected_choice_value}` : group.decision?.decision || "";
    return `<article class="review-item cluster-card" data-group-card="${escapeHtml(group.group_id)}" aria-label="Review group ${group.creation_order + 1}">
      <div class="cluster-heading"><strong>Review group</strong><span class="state-pill ${group.review_state}">${group.review_state === "confirmed" ? "Confirmed" : "Needs review"}</span></div>
      <p class="metadata">${members.length} unique answers · ${impact(question, group.member_processing_ids)} respondent responses</p>
      <ul class="answer-selection-list">${members.map(answer => `<li>${renderAnswerSelection(question, answer)}</li>`).join("")}</ul>
      <p><strong>Provider proposal:</strong> ${escapeHtml(proposal ? proposalLabel(proposal) : "Reviewer-created group")}</p>
      <p><strong>Saved decision:</strong> ${escapeHtml(decisionLabel(group.decision))}</p>
      ${readOnly ? "" : `<div class="decision-controls">
        <label for="decision-${escapeHtml(group.group_id)}">Edit coding decision</label>
        <select id="decision-${escapeHtml(group.group_id)}" data-decision-select data-question="${escapeHtml(question.question_id)}" data-group="${escapeHtml(group.group_id)}" ${anotherDraft || editingStopped ? "disabled" : ""}>
          <option value="" ${savedValue === "" ? "selected" : ""}>Choose a decision…</option><optgroup label="Existing choices">${options}</optgroup>
          <option value="new_category" ${savedValue === "new_category" ? "selected" : ""}>Create a new bilingual category</option>
        </select>
        ${groupDraft ? renderDraft(groupDraft) : ""}
        <button class="primary" type="button" data-confirm-group data-question="${escapeHtml(question.question_id)}" data-group="${escapeHtml(group.group_id)}" ${!group.decision || groupDraft || editingStopped || group.review_state === "confirmed" ? "disabled" : ""}>Confirm group</button>
      </div>
      ${renderMergeControls(question, group)}`}
    </article>`;
  }

  function renderMergeControls(question, group) {
    const draftGroupId = draft?.questionId === question.question_id ? draft.groupId : null;
    const sourceHasDraft = draftGroupId === group.group_id;
    const options = question.workspace.active_groups.filter(candidate =>
      candidate.group_id !== group.group_id && candidate.group_id !== draftGroupId
    ).map(candidate =>
      `<option value="${escapeHtml(candidate.group_id)}">Review group ${candidate.creation_order + 1}</option>`
    ).join("");
    if (!options) return "";
    const uniqueCount = group.member_processing_ids.length;
    const responseCount = impact(question, group.member_processing_ids);
    return `<div class="merge-controls">
      <label>Merge this group (${uniqueCount} unique answers · ${responseCount} respondent responses) into
        <select data-merge-destination data-question="${escapeHtml(question.question_id)}" data-source-group="${escapeHtml(group.group_id)}" ${sourceHasDraft || editingStopped ? "disabled" : ""}><option value="">Choose destination…</option>${options}</select>
      </label>
      <button class="secondary-action" type="button" data-merge-groups disabled>Merge group</button>
    </div>`;
  }

  function renderAnswerSelection(question, answer) {
    if (readOnly) return `${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count})</span>`;
    const checked = selection?.mode === "active" && selection?.questionId === question.question_id && selection.processingIds.has(answer.processing_id);
    return `<label class="answer-selection"><input type="checkbox" data-answer-selection data-question="${escapeHtml(question.question_id)}" data-processing-id="${escapeHtml(answer.processing_id)}" aria-label="Select answer ${escapeHtml(answer.text)}" ${checked ? "checked" : ""} ${editingStopped ? "disabled" : ""}><span>${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count})</span></span></label>`;
  }

  function renderRestoreSelection(question, answer) {
    if (readOnly) return `${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count})</span>`;
    const checked = selection?.mode === "restore" && selection?.questionId === question.question_id && selection.processingIds.has(answer.processing_id);
    return `<label class="answer-selection"><input type="checkbox" data-restore-selection data-question="${escapeHtml(question.question_id)}" data-processing-id="${escapeHtml(answer.processing_id)}" aria-label="Restore answer ${escapeHtml(answer.text)}" ${checked ? "checked" : ""} ${editingStopped ? "disabled" : ""}><span>${escapeHtml(answer.text)} <span class="metadata">(${answer.occurrence_count})</span></span></label>`;
  }

  function renderSelectionActions(question) {
    if (readOnly || selection?.mode !== "active" || selection?.questionId !== question.question_id || !selection.processingIds.size) return "";
    const selectedIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
    const currentLocations = selectedIds.map(processingId => currentLocation(question, processingId));
    const selectionChangesDraftGroup = draft?.questionId === question.question_id && currentLocations.some(location => location.location === "active_group" && location.group_id === draft.groupId);
    const moveChangesDraftGroup = selectionChangesDraftGroup || (draft?.questionId === question.question_id && moveDestination === `group:${draft.groupId}`);
    const options = question.workspace.active_groups.filter(group =>
      currentLocations.some(location => location.location !== "active_group" || location.group_id !== group.group_id)
    ).map(group =>
      `<option value="group:${escapeHtml(group.group_id)}" ${moveDestination === `group:${group.group_id}` ? "selected" : ""}>Review group ${group.creation_order + 1}</option>`
    ).join("");
    const needsAttentionOption = currentLocations.some(location => location.location !== "needs_attention")
      ? `<option value="needs_attention" ${moveDestination === "needs_attention" ? "selected" : ""}>Needs attention</option>`
      : "";
    return `<section class="selection-actions" role="region" aria-label="Selection actions">
      <strong>${selectedIds.length} unique answers · ${impact(question, selectedIds)} respondent responses</strong>
      <div class="selection-controls"><label>Move selected answers to<select data-move-destination><option value="">Choose destination…</option>${options}${needsAttentionOption}</select></label>
      <button class="primary" type="button" data-move-answers ${!moveDestination || moveChangesDraftGroup || editingStopped ? "disabled" : ""}>Move selected answers</button>
      <button class="primary" type="button" data-create-group ${selectionChangesDraftGroup || editingStopped ? "disabled" : ""}>Create group from selection</button>
      <button class="primary" type="button" data-exclude-answers ${selectionChangesDraftGroup || editingStopped ? "disabled" : ""}>Exclude selected answers</button>
      <button class="secondary-action" type="button" data-clear-selection>Clear selection</button></div>
    </section>`;
  }

  function renderRestoreActions(question) {
    if (readOnly || selection?.mode !== "restore" || selection?.questionId !== question.question_id || !selection.processingIds.size) return "";
    const selectedIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
    const unique = selectedIds.length === 1 ? "1 unique answer" : `${selectedIds.length} unique answers`;
    const responses = impact(question, selectedIds);
    const responseLabel = responses === 1 ? "1 respondent response" : `${responses} respondent responses`;
    return `<section class="selection-actions" role="region" aria-label="Restore actions"><strong>${unique} · ${responseLabel}</strong><div class="selection-controls"><button class="primary" type="button" data-restore-answers ${editingStopped ? "disabled" : ""}>Restore selected answers</button><button class="secondary-action" type="button" data-clear-selection>Clear selection</button></div></section>`;
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
    document.querySelectorAll("[data-question-nav]").forEach(link => link.addEventListener("click", event => {
      event.preventDefault();
      const questionId = link.dataset.questionNav;
      clearMoveSelection(); render();
      document.querySelector(`#question-${CSS.escape(questionId)}`)?.scrollIntoView();
    }));
    document.querySelectorAll("[data-answer-selection]").forEach(input => input.addEventListener("change", () => {
      const processingId = input.dataset.processingId;
      if (!selection || selection.mode !== "active" || selection.questionId !== input.dataset.question) {
        selection = {mode: "active", questionId: input.dataset.question, processingIds: new Set()};
      }
      if (input.checked) selection.processingIds.add(processingId);
      else selection.processingIds.delete(processingId);
      if (!selection.processingIds.size) selection = null;
      moveDestination = ""; render();
      document.querySelector(`[data-answer-selection][data-processing-id="${CSS.escape(processingId)}"]`)?.focus();
    }));
    document.querySelectorAll("[data-restore-selection]").forEach(input => input.addEventListener("change", () => {
      const processingId = input.dataset.processingId;
      if (!selection || selection.mode !== "restore" || selection.questionId !== input.dataset.question) {
        selection = {mode: "restore", questionId: input.dataset.question, processingIds: new Set()};
      }
      if (input.checked) selection.processingIds.add(processingId);
      else selection.processingIds.delete(processingId);
      if (!selection.processingIds.size) selection = null;
      moveDestination = ""; render();
      document.querySelector(`[data-restore-selection][data-processing-id="${CSS.escape(processingId)}"]`)?.focus();
    }));
    document.querySelector("[data-clear-selection]")?.addEventListener("click", () => {
      clearMoveSelection(); render();
    });
    document.querySelector("[data-move-destination]")?.addEventListener("change", event => {
      moveDestination = event.target.value; render();
      document.querySelector("[data-move-answers]")?.focus();
    });
    document.querySelector("[data-move-answers]")?.addEventListener("click", () => {
      const question = review.questions.find(question => question.question_id === selection.questionId);
      const processingIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
      const destination = moveDestination === "needs_attention"
        ? {location: "needs_attention"}
        : {location: "active_group", group_id: moveDestination.slice("group:".length)};
      sendCommand({
        type: "move_answers",
        question_id: question.question_id,
        processing_ids: processingIds,
        source_locations: processingIds.map(processingId => ({processing_id: processingId, ...currentLocation(question, processingId)})),
        destination,
      }, "Selected answers moved.");
    });
    document.querySelector("[data-create-group]")?.addEventListener("click", () => {
      const question = review.questions.find(question => question.question_id === selection.questionId);
      const processingIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
      sendCommand({
        type: "create_group",
        question_id: question.question_id,
        processing_ids: processingIds,
        source_locations: processingIds.map(processingId => ({processing_id: processingId, ...currentLocation(question, processingId)})),
      }, "Group created from selected answers.");
    });
    document.querySelector("[data-exclude-answers]")?.addEventListener("click", () => {
      const question = review.questions.find(question => question.question_id === selection.questionId);
      const processingIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
      sendCommand({
        type: "exclude_answers",
        question_id: question.question_id,
        processing_ids: processingIds,
        source_locations: processingIds.map(processingId => ({processing_id: processingId, ...currentLocation(question, processingId)})),
      }, "Selected answers excluded.");
    });
    document.querySelector("[data-restore-answers]")?.addEventListener("click", () => {
      const question = review.questions.find(question => question.question_id === selection.questionId);
      const processingIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
      sendCommand({type: "restore_answers", question_id: question.question_id, processing_ids: processingIds}, "Selected answers restored to Needs attention.");
    });
    document.querySelector("[data-undo]")?.addEventListener("click", event => {
      sendCommand({type: "undo", question_id: event.target.dataset.question}, "Latest structural change undone.");
    });
    document.querySelectorAll("[data-merge-destination]").forEach(select => select.addEventListener("change", () => {
      select.closest(".merge-controls").querySelector("[data-merge-groups]").disabled = !select.value;
    }));
    document.querySelectorAll("[data-merge-groups]").forEach(button => button.addEventListener("click", () => {
      const select = button.closest(".merge-controls").querySelector("[data-merge-destination]");
      sendCommand({
        type: "merge_groups",
        question_id: select.dataset.question,
        source_group_id: select.dataset.sourceGroup,
        destination_group_id: select.value,
      }, "Groups merged.");
    }));
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

  function currentLocation(question, processingId) {
    const group = question.workspace.active_groups.find(group => group.member_processing_ids.includes(processingId));
    if (group) return {location: "active_group", group_id: group.group_id};
    if (question.workspace.needs_attention.includes(processingId)) return {location: "needs_attention"};
    throw new Error("Selected answer is not movable.");
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
    review = result.review;
    if (command.type === "apply_decision") draft = null;
    if (["move_answers", "create_group", "merge_groups", "exclude_answers", "restore_answers"].includes(command.type)) {
      undoQuestionId = command.question_id;
      clearMoveSelection();
    } else {
      undoQuestionId = null;
      if (command.type === "undo") clearMoveSelection();
    }
    saveStatus.textContent = "All changes saved"; render(); showMessage(successMessage, false);
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
