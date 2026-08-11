(() => {
  let review = window.REVIEW;
  let reviewProgress = window.REVIEW_PROGRESS;
  let reviewChanges = window.REVIEW_CHANGES;
  let readOnly = window.REVIEW_READ_ONLY;
  const legacy = window.REVIEW_LEGACY;
  let draft = null;
  let selection = null;
  let moveDestination = "";
  let undoQuestionId = null;
  let editingStopped = false;
  let currentQuestionId = review.questions[0]?.question_id ?? null;
  let answerSearch = "";
  let lastUndecidedTarget = null;
  const filters = {status: "all", modified: false, exclusions: false, providerWarning: false};
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

  function providerWarningIds(question) {
    return new Set(questionProjection(question.question_id).provider_warning_processing_ids);
  }

  function questionMetrics(question) {
    const projected = questionProjection(question.question_id);
    return {
      confirmedGroups: projected.confirmed_group_count,
      activeGroups: projected.active_group_count,
      needsReviewGroups: projected.needs_review_group_count,
      needsAttentionAnswers: projected.needs_attention.unique_answer_count,
      excludedAnswers: projected.excluded.unique_answer_count,
      complete: projected.status === "complete",
      resolved: projected.resolved_item_count,
      remaining: projected.remaining_item_count,
      totalAnswers: projected.total_unique_answer_count,
      totalResponses: projected.total_response_count,
      needsAttentionResponses: projected.needs_attention.response_count,
      excludedResponses: projected.excluded.response_count,
      status: projected.status,
      modified: projected.modified,
      hasExclusions: projected.has_exclusions,
      hasProviderWarning: projected.has_provider_warning,
    };
  }

  function questionProjection(questionId) {
    return reviewProgress.questions.find(item => item.question_id === questionId);
  }

  function filteredQuestions() {
    return review.questions.filter(question => {
      const metrics = questionMetrics(question);
      return (filters.status === "all" || metrics.status === filters.status)
        && (!filters.modified || metrics.modified)
        && (!filters.exclusions || metrics.hasExclusions)
        && (!filters.providerWarning || metrics.hasProviderWarning);
    });
  }

  function answerMatches(answer) {
    return !answerSearch || matchSpan(answer.text) !== null;
  }

  function highlightedAnswer(text) {
    if (!answerSearch) return escapeHtml(text);
    const match = matchSpan(text);
    if (!match) return escapeHtml(text);
    const {start, end} = match;
    return `${escapeHtml(text.slice(0, start))}<mark>${escapeHtml(text.slice(start, end))}</mark>${escapeHtml(text.slice(end))}`;
  }

  function matchSpan(text) {
    const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const escapedSearch = escapeRegex(answerSearch);
    const simpleMatch = new RegExp(escapedSearch, "iu").exec(text);
    if (simpleMatch) return {start: simpleMatch.index, end: simpleMatch.index + simpleMatch[0].length};
    const expandCaseMapping = character => {
      const uppercase = character.toUpperCase();
      const lowercase = character.toLowerCase();
      if (uppercase.length > character.length) return uppercase.toLowerCase();
      if (lowercase.length > character.length) return lowercase;
      return character;
    };
    const expandCaseMappings = value => [...value].map(expandCaseMapping).join("");
    const expandedSearch = expandCaseMappings(answerSearch);
    const expandedText = expandCaseMappings(text);
    const expandedMatch = new RegExp(escapeRegex(expandedSearch), "iu").exec(expandedText);
    if (!expandedMatch) return null;
    const expandedStart = expandedMatch.index;
    const expandedEnd = expandedStart + expandedMatch[0].length;
    const offsets = [];
    let originalOffset = 0;
    for (const character of text) {
      const start = originalOffset;
      originalOffset += character.length;
      for (let index = 0; index < expandCaseMapping(character).length; index += 1) {
        offsets.push({start, end: originalOffset});
      }
    }
    return {start: offsets[expandedStart].start, end: offsets[expandedEnd - 1].end};
  }

  function groupLabel(question, groupId) {
    const groups = [...question.workspace.active_groups, ...question.workspace.retired_groups];
    const group = groups.find(candidate => candidate.group_id === groupId);
    return group ? `Review group ${group.creation_order + 1}` : groupId;
  }

  function locationLabel(question, location) {
    if (location.location === "active_group") return groupLabel(question, location.group_id);
    if (location.location === "excluded") return "Excluded from coding";
    return "Needs attention";
  }

  function sourceLabels(question, entry) {
    return [...new Set(entry.before.locations.map(location => locationLabel(question, location)))].join(" and ");
  }

  function historyDescription(question, entry) {
    if (entry.operation === "exclude_answers") return `Excluded ${entry.affected_answer_count} answers from coding (from ${sourceLabels(question, entry)})`;
    if (entry.operation === "restore_answers") return `Restored ${entry.affected_answer_count} answers to Needs attention`;
    if (entry.operation === "undo") {
      const labels = {move_answers: "move", create_group: "group creation", split_group: "group split", merge_groups: "merge", exclude_answers: "exclusion", restore_answers: "restoration"};
      return `Undid ${labels[entry.before.operation] || entry.before.operation}`;
    }
    if (entry.operation === "apply_decision") return `Changed the decision for ${groupLabel(question, entry.group_id)} from ${decisionLabel(entry.before.decision)} to ${decisionLabel(entry.after.decision)}`;
    if (entry.operation === "confirm_group") return `Confirmed ${groupLabel(question, entry.group_id)}`;
    if (entry.operation === "move_answers") return `Moved ${entry.affected_answer_count} answers from ${sourceLabels(question, entry)} to ${locationLabel(question, entry.after.destination)}`;
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
    const visibleQuestions = filteredQuestions();
    if (!visibleQuestions.some(question => question.question_id === currentQuestionId)) {
      currentQuestionId = visibleQuestions[0]?.question_id ?? null;
      answerSearch = "";
      clearMoveSelection();
    }
    nav.innerHTML = visibleQuestions.map(question => {
      const index = review.questions.indexOf(question);
      const metrics = questionMetrics(question);
      return `<a class="question-nav-item" data-question-nav="${escapeHtml(question.question_id)}" href="#question-${escapeHtml(question.question_id)}"><span>${index + 1}. ${escapeHtml(question.question_id)}</span><span>Resolved ${metrics.resolved} · Remaining ${metrics.remaining}</span><small>${metrics.totalAnswers} unique · ${metrics.totalResponses} responses</small></a>`;
    }).join("");
    const current = review.questions.find(question => question.question_id === currentQuestionId);
    const detachedDraft = draft && draft.questionId !== currentQuestionId ? renderDraft(draft, true) : "";
    const currentQuestion = current && visibleQuestions.includes(current) ? renderQuestion(current, review.questions.indexOf(current)) : "";
    root.innerHTML = detachedDraft + currentQuestion;
    bindControls();
    updateProgress();
  }

  function renderQuestion(question, index) {
    const groups = question.workspace.active_groups.map(group => renderGroup(question, group)).join("");
    const needsAttention = question.workspace.needs_attention.map(id => answerById(question, id));
    const excluded = question.workspace.excluded_answers.map(id => answerById(question, id));
    const metrics = questionMetrics(question);
    const complete = metrics.complete;
    const latestExclusion = [...question.workspace.history].reverse().find(entry => entry.operation === "exclude_answers");
    const canUndo = !readOnly && !editingStopped && undoQuestionId === question.question_id && question.workspace.undo;
    return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
      <header class="question-header" role="banner" aria-label="Question progress"><p class="eyebrow">Question ${index + 1}</p><h2>${escapeHtml(question.question_text.english)}</h2><p class="arabic">${escapeHtml(question.question_text.arabic)}</p><span class="state-pill ${complete ? "confirmed" : "needs_review"}">${complete ? "Complete" : "Outstanding"}</span>
        <p class="question-counts">${metrics.confirmedGroups}/${metrics.activeGroups} confirmed groups · ${metrics.needsReviewGroups} needs-review group${metrics.needsReviewGroups === 1 ? "" : "s"} · Needs attention: ${metrics.needsAttentionAnswers} unique · ${metrics.needsAttentionResponses} response${metrics.needsAttentionResponses === 1 ? "" : "s"} · Excluded: ${metrics.excludedAnswers} unique · ${metrics.excludedResponses} responses</p>
        <label class="answer-search">Search answers in this question<input type="search" data-answer-search value="${escapeHtml(answerSearch)}"></label>
      </header>
      ${canUndo ? `<button class="secondary-action" type="button" data-undo data-question="${escapeHtml(question.question_id)}">${escapeHtml(undoLabel(question.workspace.undo.operation))}</button>` : ""}
      ${renderSelectionActions(question)}
      ${renderRestoreActions(question)}
      <section class="subcard"><h3>Active groups</h3>${groups || "<p>No active groups.</p>"}</section>
      <section class="subcard"><h3>Needs attention</h3><p class="metadata">${needsAttention.length} unique answers · ${impact(question, question.workspace.needs_attention)} respondent responses</p>
        <ul class="answer-selection-list">${needsAttention.filter(answerMatches).map(answer => `<li>${renderAnswerSelection(question, answer)}</li>`).join("") || "<li>No matching answers</li>"}</ul>
      </section>
      <details class="subcard" aria-label="Excluded from coding" ${answerSearch && excluded.some(answerMatches) ? "open" : ""}><summary>Excluded from coding (${excluded.length} unique answers · ${impact(question, question.workspace.excluded_answers)} respondent responses)</summary>
        <p class="metadata">${latestExclusion ? `Latest exclusion ${escapeHtml(latestExclusion.timestamp_utc)}` : "No exclusions recorded"}</p>
        <ul class="answer-selection-list">${excluded.filter(answerMatches).map(answer => `<li>${renderRestoreSelection(question, answer)}</li>`).join("") || "<li>None</li>"}</ul>
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
    const visibleMembers = members.filter(answerMatches);
    if (answerSearch && !visibleMembers.length) return "";
    const hasProviderWarning = group.member_processing_ids.some(id => providerWarningIds(question).has(id));
    const groupDraft = draft?.questionId === question.question_id && draft?.groupId === group.group_id ? draft : null;
    const anotherDraft = draft && !groupDraft;
    const options = question.existing_choices.map(choice => `<option value="existing_choice:${choice.value}">${choice.value} · ${escapeHtml(choice.english_label)} · ${escapeHtml(choice.arabic_label)}</option>`).join("");
    const savedValue = group.decision?.decision === "existing_choice" ? `existing_choice:${group.decision.selected_choice_value}` : group.decision?.decision || "";
    return `<article class="review-item cluster-card" data-group-card="${escapeHtml(group.group_id)}" data-undecided-target="group:${escapeHtml(group.group_id)}" tabindex="-1" aria-label="Review group ${group.creation_order + 1}">
      <div class="cluster-heading"><strong>Review group</strong><span class="state-pill ${group.review_state}">${group.review_state === "confirmed" ? "Confirmed" : "Needs review"}</span>${hasProviderWarning ? '<span class="warning-badge">Provider warning</span>' : ""}</div>
      <p class="metadata">${members.length} unique answers · ${impact(question, group.member_processing_ids)} respondent responses</p>
      <ul class="answer-selection-list">${visibleMembers.map(answer => `<li>${renderAnswerSelection(question, answer)}</li>`).join("")}</ul>
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
    if (readOnly) return `${highlightedAnswer(answer.text)} <span class="metadata">(${answer.occurrence_count})</span>`;
    const checked = selection?.mode === "active" && selection?.questionId === question.question_id && selection.processingIds.has(answer.processing_id);
    return `<label class="answer-selection"><input type="checkbox" data-answer-selection data-question="${escapeHtml(question.question_id)}" data-processing-id="${escapeHtml(answer.processing_id)}" data-undecided-target="answer:${escapeHtml(answer.processing_id)}" aria-label="Select answer ${escapeHtml(answer.text)}" ${checked ? "checked" : ""} ${editingStopped ? "disabled" : ""}><span>${highlightedAnswer(answer.text)} <span class="metadata">(${answer.occurrence_count})</span></span></label>`;
  }

  function renderRestoreSelection(question, answer) {
    if (readOnly) return `${highlightedAnswer(answer.text)} <span class="metadata">(${answer.occurrence_count})</span>`;
    const checked = selection?.mode === "restore" && selection?.questionId === question.question_id && selection.processingIds.has(answer.processing_id);
    return `<label class="answer-selection"><input type="checkbox" data-restore-selection data-question="${escapeHtml(question.question_id)}" data-processing-id="${escapeHtml(answer.processing_id)}" aria-label="Restore answer ${escapeHtml(answer.text)}" ${checked ? "checked" : ""} ${editingStopped ? "disabled" : ""}><span>${highlightedAnswer(answer.text)} <span class="metadata">(${answer.occurrence_count})</span></span></label>`;
  }

  function renderSelectionActions(question) {
    if (readOnly || selection?.mode !== "active" || selection?.questionId !== question.question_id || !selection.processingIds.size) return "";
    const selectedIds = question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
    const currentLocations = selectedIds.map(processingId => currentLocation(question, processingId));
    const selectionChangesDraftGroup = draft?.questionId === question.question_id && currentLocations.some(location => location.location === "active_group" && location.group_id === draft.groupId);
    const moveChangesDraftGroup = selectionChangesDraftGroup || (draft?.questionId === question.question_id && moveDestination === `group:${draft.groupId}`);
    const hiddenSelected = answerSearch ? selectedIds.filter(id => !answerMatches(answerById(question, id))).length : 0;
    const options = question.workspace.active_groups.filter(group =>
      currentLocations.some(location => location.location !== "active_group" || location.group_id !== group.group_id)
    ).map(group =>
      `<option value="group:${escapeHtml(group.group_id)}" ${moveDestination === `group:${group.group_id}` ? "selected" : ""}>Review group ${group.creation_order + 1}</option>`
    ).join("");
    const needsAttentionOption = currentLocations.some(location => location.location !== "needs_attention")
      ? `<option value="needs_attention" ${moveDestination === "needs_attention" ? "selected" : ""}>Needs attention</option>`
      : "";
    return `<section class="selection-actions" role="region" aria-label="Selection actions">
      <strong>${selectedIds.length} unique answers · ${impact(question, selectedIds)} respondent responses</strong>${hiddenSelected ? `<span>${hiddenSelected} selected answer${hiddenSelected === 1 ? "" : "s"} hidden by search</span>` : ""}
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
    const hiddenSelected = answerSearch ? selectedIds.filter(id => !answerMatches(answerById(question, id))).length : 0;
    const unique = selectedIds.length === 1 ? "1 unique answer" : `${selectedIds.length} unique answers`;
    const responses = impact(question, selectedIds);
    const responseLabel = responses === 1 ? "1 respondent response" : `${responses} respondent responses`;
    return `<section class="selection-actions" role="region" aria-label="Restore actions"><strong>${unique} · ${responseLabel}</strong>${hiddenSelected ? `<span>${hiddenSelected} selected answer${hiddenSelected === 1 ? "" : "s"} hidden by search</span>` : ""}<div class="selection-controls"><button class="primary" type="button" data-restore-answers ${editingStopped ? "disabled" : ""}>Restore selected answers</button><button class="secondary-action" type="button" data-clear-selection>Clear selection</button></div></section>`;
  }

  function renderDraft(value, detached = false) {
    const labels = value.decision.decision === "new_category" ? `<div class="labels">
      <label>English label<input data-draft-label="english_label" value="${escapeHtml(value.decision.english_label)}"></label>
      <label>Arabic label<input class="arabic" data-draft-label="arabic_label" value="${escapeHtml(value.decision.arabic_label)}"></label>
    </div>` : "";
    const returnControl = detached ? '<button class="secondary-action" type="button" data-return-draft>Return to draft</button>' : "";
    return `<section class="draft-panel" aria-label="Unsaved decision draft"><p><strong>Unsaved draft</strong> — saved state is unchanged.</p>${labels}
      ${returnControl}
      <div class="draft-actions"><button class="primary" type="button" data-apply-draft>Apply decision changes</button><button class="secondary-action" type="button" data-discard-draft>Discard draft</button></div></section>`;
  }

  function bindControls() {
    const reviewChangesButton = document.querySelector("[data-review-changes]");
    if (reviewChangesButton) {
      reviewChangesButton.textContent = reviewChanges.can_complete && !readOnly ? "Finish review" : "Review changes";
      reviewChangesButton.onclick = openReviewChanges;
    }
    document.querySelectorAll("[data-question-nav]").forEach(link => link.addEventListener("click", event => {
      event.preventDefault();
      const questionId = link.dataset.questionNav;
      currentQuestionId = questionId; answerSearch = ""; lastUndecidedTarget = null; clearMoveSelection(); render();
      document.querySelector(`#question-${CSS.escape(questionId)}`)?.scrollIntoView();
    }));
    const searchInput = document.querySelector("[data-answer-search]");
    searchInput?.addEventListener("input", event => {
      answerSearch = event.target.value;
      if (event.isComposing) return;
      render();
      const search = document.querySelector("[data-answer-search]");
      search?.focus(); search?.setSelectionRange(search.value.length, search.value.length);
    });
    searchInput?.addEventListener("compositionend", event => {
      answerSearch = event.target.value;
      render();
      const search = document.querySelector("[data-answer-search]");
      search?.focus(); search?.setSelectionRange(search.value.length, search.value.length);
    });
    const statusFilter = document.querySelector("#question-status-filter");
    if (statusFilter) statusFilter.onchange = event => {
      filters.status = event.target.value; lastUndecidedTarget = null; render(); syncFilterControls();
    };
    for (const [selector, key] of [["#modified-filter", "modified"], ["#exclusions-filter", "exclusions"], ["#provider-warning-filter", "providerWarning"]]) {
      const control = document.querySelector(selector);
      if (control) control.onchange = event => {
        filters[key] = event.target.checked; lastUndecidedTarget = null; render(); syncFilterControls();
      };
    }
    const clearFilterButton = document.querySelector("[data-clear-filters]");
    if (clearFilterButton) clearFilterButton.onclick = clearFilters;
    const nextButton = document.querySelector("[data-next-undecided]");
    if (nextButton) nextButton.onclick = nextUndecided;
    bindSelectionControls("[data-answer-selection]", "active");
    bindSelectionControls("[data-restore-selection]", "restore");
    document.querySelector("[data-clear-selection]")?.addEventListener("click", () => {
      clearMoveSelection(); render();
    });
    document.querySelector("[data-move-destination]")?.addEventListener("change", event => {
      moveDestination = event.target.value; render();
      document.querySelector("[data-move-answers]")?.focus();
    });
    document.querySelector("[data-move-answers]")?.addEventListener("click", () => {
      const question = selectedQuestion();
      const processingIds = selectedAnswerIds(question);
      const destination = moveDestination === "needs_attention"
        ? {location: "needs_attention"}
        : {location: "active_group", group_id: moveDestination.slice("group:".length)};
      sendCommand({
        type: "move_answers",
        question_id: question.question_id,
        processing_ids: processingIds,
        source_locations: selectedSourceLocations(question, processingIds),
        destination,
      }, "Selected answers moved.");
    });
    document.querySelector("[data-create-group]")?.addEventListener("click", () => {
      const question = selectedQuestion();
      const processingIds = selectedAnswerIds(question);
      sendCommand({
        type: "create_group",
        question_id: question.question_id,
        processing_ids: processingIds,
        source_locations: selectedSourceLocations(question, processingIds),
      }, "Group created from selected answers.");
    });
    document.querySelector("[data-exclude-answers]")?.addEventListener("click", () => {
      const question = selectedQuestion();
      const processingIds = selectedAnswerIds(question);
      sendCommand({
        type: "exclude_answers",
        question_id: question.question_id,
        processing_ids: processingIds,
        source_locations: selectedSourceLocations(question, processingIds),
      }, "Selected answers excluded.");
    });
    document.querySelector("[data-restore-answers]")?.addEventListener("click", () => {
      const question = selectedQuestion();
      const processingIds = selectedAnswerIds(question);
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
    document.querySelector("[data-return-draft]")?.addEventListener("click", () => {
      Object.assign(filters, {status: "all", modified: false, exclusions: false, providerWarning: false});
      currentQuestionId = draft.questionId; answerSearch = ""; lastUndecidedTarget = null; clearMoveSelection(); render(); syncFilterControls();
      document.querySelector("[data-apply-draft]")?.focus();
    });
    document.querySelector("[data-discard-draft]")?.addEventListener("click", () => {
      const groupId = draft.groupId; draft = null; render();
      document.querySelector(`[data-group-card="${CSS.escape(groupId)}"] [data-decision-select]`)?.focus();
      showMessage("Draft discarded. Saved state was not changed.", false);
    });
    document.querySelector("[data-apply-draft]")?.addEventListener("click", () => sendCommand({type: "apply_decision", question_id: draft.questionId, group_id: draft.groupId, decision: draft.decision}, "Decision changes applied."));
    document.querySelectorAll("[data-confirm-group]").forEach(button => button.addEventListener("click", () => sendCommand({type: "confirm_group", question_id: button.dataset.question, group_id: button.dataset.group}, "Group confirmed.")));
  }

  function openReviewChanges() {
    const dialog = document.querySelector("#review-changes-dialog");
    const content = document.querySelector("#review-changes-content");
    const net = reviewChanges.net_changes;
    const outstanding = reviewChanges.outstanding;
    const failures = reviewChanges.blocking_failures.map(item => `<li>${escapeHtml(item.message)}${item.question_id ? ` · ${escapeHtml(item.question_id)}` : ""}</li>`).join("");
    const cautions = reviewChanges.cautions.map(item => `<li>${escapeHtml(item.message)}${item.question_id ? ` · ${escapeHtml(item.question_id)}` : ""}</li>`).join("");
    const answerSummary = item => {
      const question = review.questions.find(candidate => candidate.question_id === item.question_id);
      const answer = question?.answers.find(candidate => candidate.processing_id === item.processing_id);
      return `${escapeHtml(item.question_id)} · ${escapeHtml(answer?.text || item.processing_id)} · ${item.response_count} responses`;
    };
    const groupSummary = item => `${escapeHtml(item.question_id)} · ${escapeHtml(item.group_id)} · ${item.canonical_answer_count ?? ""} answers · ${item.response_count ?? ""} responses`;
    const outstandingItems = [
      ...outstanding.groups.map(item => `<li>${escapeHtml(item.question_id)} · ${escapeHtml(item.group_id)}</li>`),
      ...outstanding.needs_attention_answers.map(item => `<li>${answerSummary(item)}</li>`),
    ].join("");
    const movedItems = net.moved_answers.map(item => {
      const question = review.questions.find(candidate => candidate.question_id === item.question_id);
      return `<li>${answerSummary(item)} · ${escapeHtml(locationLabel(question, item.from))} → ${escapeHtml(locationLabel(question, item.to))}</li>`;
    }).join("");
    const createdItems = net.reviewer_created_groups.map(item => `<li>${groupSummary(item)}</li>`).join("");
    const retiredItems = net.retired_original_groups.map(item => `<li>${groupSummary(item)}</li>`).join("");
    const excludedItems = net.excluded_answers.map(item => `<li>${answerSummary(item)}</li>`).join("");
    const invalidatedItems = net.confirmation_invalidated_groups.map(item => `<li>${escapeHtml(item.question_id)} · ${escapeHtml(item.group_id)}</li>`).join("");
    const lock = reviewChanges.can_complete && !readOnly
      ? `<button class="primary" type="button" data-complete-review ${draft ? "disabled" : ""}>Complete and lock review</button>${draft ? '<p class="warning">Discard or apply the local decision draft before completion.</p>' : ""}<div data-lock-confirmation></div>`
      : "";
    content.innerHTML = `<h2 id="review-changes-title">Review changes</h2>
      <p>${outstanding.needs_review_group_count} groups need review · ${outstanding.needs_attention_answer_count} answers need attention</p><ul>${outstandingItems || "<li>No outstanding items.</li>"}</ul>
      <h3>Net current changes</h3><ul><li>${net.moved_canonical_answer_count} moved canonical answers · ${net.moved_response_count} respondent responses</li>${movedItems}<li>${net.reviewer_created_group_count} reviewer-created groups</li>${createdItems}<li>${net.retired_original_group_count} retired original groups</li>${retiredItems}<li>${net.excluded_answer_count} excluded answers · ${net.excluded_response_count} respondent responses</li>${excludedItems}<li>${net.confirmation_invalidated_group_count} groups had confirmation invalidated</li>${invalidatedItems}</ul>
      <h3>Blocking validation</h3><ul>${failures || "<li>No blocking failures.</li>"}</ul>
      <h3>Cautions</h3><ul>${cautions || "<li>No cautions.</li>"}</ul>${lock}`;
    content.querySelector("[data-complete-review]")?.addEventListener("click", () => {
      content.querySelector("[data-lock-confirmation]").innerHTML = '<p><strong>This permanently locks the review.</strong></p><button class="primary" type="button" data-confirm-lock>Yes, complete and lock review</button>';
      content.querySelector("[data-confirm-lock]").addEventListener("click", () => sendCommand({type: "complete_review"}, "Review completed and locked."));
    });
    dialog.showModal();
  }

  function syncFilterControls() {
    const status = document.querySelector("#question-status-filter");
    if (status) status.value = filters.status;
    const modified = document.querySelector("#modified-filter");
    if (modified) modified.checked = filters.modified;
    const exclusions = document.querySelector("#exclusions-filter");
    if (exclusions) exclusions.checked = filters.exclusions;
    const providerWarning = document.querySelector("#provider-warning-filter");
    if (providerWarning) providerWarning.checked = filters.providerWarning;
  }

  function clearFilters() {
    Object.assign(filters, {status: "all", modified: false, exclusions: false, providerWarning: false});
    lastUndecidedTarget = null;
    render(); syncFilterControls(); showMessage("Question filters cleared.", false);
  }

  function undecidedTargets() {
    return filteredQuestions().filter(question => !questionMetrics(question).complete).flatMap(question => [
      ...question.workspace.active_groups.filter(group => group.review_state === "needs_review")
        .map(group => ({questionId: question.question_id, key: `group:${group.group_id}`})),
      ...question.workspace.needs_attention.map(id => ({questionId: question.question_id, key: `answer:${id}`})),
    ]);
  }

  function navigationOrder() {
    return filteredQuestions().flatMap(question => [
      ...[...question.workspace.active_groups, ...question.workspace.retired_groups]
        .sort((left, right) => left.creation_order - right.creation_order)
        .map(group => ({questionId: question.question_id, key: `group:${group.group_id}`})),
      ...question.answers.map(answer => ({questionId: question.question_id, key: `answer:${answer.processing_id}`})),
    ]);
  }

  function sameTarget(left, right) {
    return left.questionId === right.questionId && left.key === right.key;
  }

  function nextUndecided() {
    const targets = undecidedTargets();
    if (!targets.length) {
      showMessage("No undecided items in this view.", false);
      return;
    }
    let target = null;
    if (lastUndecidedTarget) {
      const orderedTargets = navigationOrder();
      const previousIndex = orderedTargets.findIndex(candidate => sameTarget(candidate, lastUndecidedTarget));
      if (previousIndex >= 0) {
        target = orderedTargets.slice(previousIndex + 1).find(candidate => targets.some(outstanding => sameTarget(outstanding, candidate)))
          ?? targets[0];
      }
    }
    if (!target) {
      const currentQuestionIndex = review.questions.findIndex(question => question.question_id === currentQuestionId);
      target = targets.find(candidate =>
        review.questions.findIndex(question => question.question_id === candidate.questionId) >= currentQuestionIndex
      ) ?? targets[0];
    }
    if (target.questionId !== currentQuestionId) clearMoveSelection();
    currentQuestionId = target.questionId;
    lastUndecidedTarget = target;
    answerSearch = "";
    render(); syncFilterControls();
    document.querySelector(`[data-undecided-target="${CSS.escape(target.key)}"]`)?.focus();
  }

  function bindSelectionControls(selector, mode) {
    document.querySelectorAll(selector).forEach(input => input.addEventListener("change", () => {
      const processingId = input.dataset.processingId;
      if (!selection || selection.mode !== mode || selection.questionId !== input.dataset.question) {
        selection = {mode, questionId: input.dataset.question, processingIds: new Set()};
      }
      if (input.checked) selection.processingIds.add(processingId);
      else selection.processingIds.delete(processingId);
      if (!selection.processingIds.size) selection = null;
      moveDestination = "";
      render();
      document.querySelector(`${selector}[data-processing-id="${CSS.escape(processingId)}"]`)?.focus();
    }));
  }

  function selectedAnswerIds(question) {
    return question.answers.map(answer => answer.processing_id).filter(id => selection.processingIds.has(id));
  }

  function selectedQuestion() {
    return review.questions.find(question => question.question_id === selection.questionId);
  }

  function selectedSourceLocations(question, processingIds) {
    return processingIds.map(processingId => ({processing_id: processingId, ...currentLocation(question, processingId)}));
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
    reviewProgress = result.progress;
    reviewChanges = result.review_changes;
    if (command.type === "apply_decision") draft = null;
    if (["move_answers", "create_group", "merge_groups", "exclude_answers", "restore_answers"].includes(command.type)) {
      undoQuestionId = command.question_id;
      clearMoveSelection();
    } else {
      undoQuestionId = null;
      if (command.type === "undo") clearMoveSelection();
    }
    if (command.type === "complete_review") {
      readOnly = true;
      editingStopped = true;
      document.querySelector("#review-changes-dialog")?.close();
      document.querySelector("#review-status").textContent = "Completed";
      document.querySelector("[data-workspace-state]").textContent = "Read-only completed review";
      document.querySelector("[data-workspace-guidance]").textContent = "This completed review is locked and can no longer be edited.";
    }
    saveStatus.textContent = command.type === "complete_review" ? "Read only" : "All changes saved"; render(); showMessage(successMessage, false);
  }

  function showMessage(text, error, reload = false) {
    message.className = error ? "workspace-message warning" : "workspace-message success";
    message.innerHTML = `${escapeHtml(text)}${reload ? ' <button type="button" data-reload-latest>Reload latest state</button>' : ""}`;
    document.querySelector("[data-reload-latest]")?.addEventListener("click", () => window.location.reload());
  }

  function updateProgress() {
    const complete = reviewProgress.complete_question_count;
    const total = reviewProgress.total_question_count;
    document.querySelector("#sidebar-completion-count").textContent = `${complete}/${total}`;
    document.querySelector("#progress-bar").style.width = `${total ? complete / total * 100 : 0}%`;
  }

  render(); syncFilterControls();
})();
