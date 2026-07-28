(() => {
  const pkg = window.REVIEW_PACKAGE;
  let draft = window.REVIEW_DRAFT;
  const root = document.querySelector("#review-root");
  const saveStatus = document.querySelector("#save-status");
  const completionCount = document.querySelector("#completion-count");
  const analystName = document.querySelector("#analyst-name");
  let saving = Promise.resolve();

  const packageQuestion = id => pkg.questions.find(question => question.question_id === id);
  const draftQuestion = id => draft.questions.find(question => question.question_id === id);
  const answerById = (question, id) => question.answers.find(answer => answer.processing_id === id);
  const itemState = id => draft.review_item_dispositions.find(item => item.review_item_id === id);
  const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  function allowedDispositions(id) {
    if (id.startsWith("existing_assignment:")) return ["approved", "rejected", "overridden"];
    if (id.startsWith("proposed_category:")) return ["approved", "rejected", "modified", "merged", "split"];
    if (id.startsWith("merge:")) return ["approved", "rejected"];
    return ["acknowledged", "assigned"];
  }

  function dispositionSelect(id) {
    const current = itemState(id).disposition;
    return `<label>Disposition<select data-disposition="${escapeHtml(id)}">
      <option value="">Choose…</option>
      ${allowedDispositions(id).map(value =>
        `<option value="${value}" ${current === value ? "selected" : ""}>${value.replaceAll("_", " ")}</option>`
      ).join("")}
    </select></label>`;
  }

  function answerText(question, processingId) {
    const answer = answerById(question, processingId);
    return `<span class="answer-text">${escapeHtml(answer.text)}</span>
      <span class="metadata">${answer.occurrence_count} occurrence${answer.occurrence_count === 1 ? "" : "s"}</span>
      ${renderDiscoveryEvidence(answer)}`;
  }

  function renderDiscoveryEvidence(answer) {
    const evidence = answer.discovery_evidence;
    if (evidence.status === null) {
      return `<span class="metadata discovery-evidence">Existing-choice candidate; not sent to discovery.</span>`;
    }
    const details = [
      `status: ${evidence.status}`,
      `cluster: ${evidence.cluster_id === null ? "none" : evidence.cluster_id}`,
      `raw label: ${evidence.raw_cluster_label === null ? "none" : evidence.raw_cluster_label}`
    ];
    if (evidence.membership_probability !== null) {
      details.push(`membership: ${Number(evidence.membership_probability).toFixed(3)}`);
    }
    return `<span class="metadata discovery-evidence">Discovery evidence · ${escapeHtml(details.join(" · "))}</span>`;
  }

  function render() {
    document.querySelector("#question-nav").innerHTML = pkg.questions.map(question =>
      `<a href="#question-${escapeHtml(question.question_id)}">${escapeHtml(question.question_id)}</a>`
    ).join("");
    root.innerHTML = pkg.questions.map(renderQuestion).join("");
    bindControls();
    updateCount();
  }

  function renderQuestion(question) {
    const state = draftQuestion(question.question_id);
    const choices = question.existing_choices.map(choice =>
      `<li><strong>${choice.value}</strong> · ${escapeHtml(choice.english_label)}
       <span class="arabic">${escapeHtml(choice.arabic_label)}</span></li>`
    ).join("");
    const existing = question.existing_choice_assignments.map(item => `
      <div class="review-item">
        <code>${escapeHtml(item.review_item_id)}</code>
        ${answerText(question, item.processing_id)}
        <p>Proposed existing choice: <strong>${item.proposed_choice_value}</strong></p>
        ${dispositionSelect(item.review_item_id)}
      </div>`).join("") || "<p class='metadata'>None</p>";
    const categories = state.categories.map(category => renderCategory(question, state, category)).join("")
      || "<p class='metadata'>No final new categories.</p>";
    const proposals = question.proposed_categories.map(item => `
      <div class="review-item">
        <code>${escapeHtml(item.review_item_id)}</code>
        <p><strong>${item.proposed_value} · ${escapeHtml(item.english_label)}</strong>
        <span class="arabic">${escapeHtml(item.arabic_label)}</span></p>
        <ul class="member-list">${item.member_processing_ids.map(id => `<li>${answerText(question, id)}</li>`).join("")}</ul>
        ${dispositionSelect(item.review_item_id)}
      </div>`).join("") || "<p class='metadata'>None</p>";
    const merges = question.merge_suggestions.map(item => `
      <div class="review-item">
        <code>${escapeHtml(item.review_item_id)}</code>
        <p>${escapeHtml(item.first_cluster_id)} ↔ ${escapeHtml(item.second_cluster_id)}
        · similarity ${Number(item.cosine_similarity).toFixed(3)}</p>
        ${dispositionSelect(item.review_item_id)}
      </div>`).join("") || "<p class='metadata'>None</p>";
    const unresolved = question.unresolved_answers.map(item => `
      <div class="review-item">
        <code>${escapeHtml(item.review_item_id)}</code>
        ${answerText(question, item.processing_id)}
        <p class="metadata">Reason: ${escapeHtml(item.reason)}</p>
        ${dispositionSelect(item.review_item_id)}
      </div>`).join("") || "<p class='metadata'>None</p>";
    const finalAnswers = state.answer_dispositions.map(answer => renderAnswerState(question, state, answer)).join("");
    return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
      <header>
        <p class="eyebrow">${escapeHtml(question.question_id)}</p>
        <h2>${escapeHtml(question.question_text.english)}</h2>
        <p class="arabic">${escapeHtml(question.question_text.arabic)}</p>
      </header>
      <div class="grid">
        <section class="subcard"><h3>Existing choices</h3><ul>${choices || "<li>None</li>"}</ul></section>
        <section class="subcard"><h3>Proposed existing assignments</h3>${existing}</section>
      </div>
      <section class="subcard"><h3>Original proposed categories</h3>${proposals}</section>
      <section class="subcard"><h3>Merge suggestions</h3>${merges}</section>
      <section class="subcard"><h3>Unresolved evidence</h3>${unresolved}</section>
      <section class="subcard">
        <div class="controls"><h3>Authoritative final categories</h3>
          <button type="button" data-create-category="${escapeHtml(question.question_id)}">Create manual category</button>
          <button type="button" data-combine="${escapeHtml(question.question_id)}">Combine two categories</button>
        </div>
        ${categories}
      </section>
      <section class="subcard"><h3>Final state for every answer</h3>${finalAnswers}</section>
    </section>`;
  }

  function renderCategory(question, state, category) {
    return `<article class="category-editor review-item">
      <div class="controls">
        <code>${escapeHtml(category.final_category_id)}</code>
        <span class="metadata">origin: ${escapeHtml(category.origin)} · components: ${escapeHtml(category.component_cluster_ids.join(", ") || "none")}</span>
        <button class="danger" type="button" data-delete-category="${escapeHtml(category.final_category_id)}" data-question="${escapeHtml(question.question_id)}">Delete</button>
      </div>
      <div class="labels">
        <label>English label<input data-category-label="english" data-category="${escapeHtml(category.final_category_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(category.english_label)}"></label>
        <label>Arabic label<input class="arabic" data-category-label="arabic" data-category="${escapeHtml(category.final_category_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(category.arabic_label)}"></label>
      </div>
      <ul class="member-list">${category.member_processing_ids.map(id => `<li>${answerText(question, id)}</li>`).join("")}</ul>
    </article>`;
  }

  function renderAnswerState(question, state, answer) {
    const targets = [
      ...question.existing_choices.map(choice => [`existing:${choice.value}`, `Existing · ${choice.value} · ${choice.english_label}`]),
      ...state.categories.map(category => [`category:${category.final_category_id}`, `New · ${category.english_label}`]),
      ["unresolved", "Explicitly unresolved"]
    ];
    const current = answer.decision === "existing_choice"
      ? `existing:${answer.choice_value}`
      : answer.decision === "new_category"
        ? `category:${answer.final_category_id}` : "unresolved";
    return `<div class="review-item answer-state">
      <div>${answerText(question, answer.processing_id)}<br><code>${escapeHtml(answer.processing_id)}</code></div>
      <div>
        <label>Final decision<select data-answer-target="${escapeHtml(answer.processing_id)}" data-question="${escapeHtml(question.question_id)}">
          ${targets.map(([value, label]) => `<option value="${escapeHtml(value)}" ${current === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
        </select></label>
        ${current === "unresolved" ? `<label>Unresolved reason<input data-unresolved-reason="${escapeHtml(answer.processing_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(answer.unresolved_reason || "")}"></label>` : ""}
        <button type="button" data-split-answer="${escapeHtml(answer.processing_id)}" data-question="${escapeHtml(question.question_id)}">Split into a new category</button>
      </div>
    </div>`;
  }

  function bindControls() {
    document.querySelectorAll("[data-disposition]").forEach(select => {
      select.addEventListener("change", () => {
        itemState(select.dataset.disposition).disposition = select.value || null;
        autosave();
      });
    });
    document.querySelectorAll("[data-category-label]").forEach(input => {
      input.addEventListener("change", () => {
        const state = draftQuestion(input.dataset.question);
        const category = state.categories.find(item => item.final_category_id === input.dataset.category);
        category[input.dataset.categoryLabel === "english" ? "english_label" : "arabic_label"] = input.value;
        if (category.origin === "proposed") category.origin = "modified";
        autosave(true);
      });
    });
    document.querySelectorAll("[data-answer-target]").forEach(select => {
      select.addEventListener("change", () => moveAnswer(select.dataset.question, select.dataset.answerTarget, select.value));
    });
    document.querySelectorAll("[data-unresolved-reason]").forEach(input => {
      input.addEventListener("change", () => {
        const answer = draftQuestion(input.dataset.question).answer_dispositions.find(item => item.processing_id === input.dataset.unresolvedReason);
        answer.unresolved_reason = input.value;
        autosave(true);
      });
    });
    document.querySelectorAll("[data-create-category]").forEach(button =>
      button.addEventListener("click", () => createManualCategory(button.dataset.createCategory)));
    document.querySelectorAll("[data-split-answer]").forEach(button =>
      button.addEventListener("click", () => splitAnswer(button.dataset.question, button.dataset.splitAnswer)));
    document.querySelectorAll("[data-delete-category]").forEach(button =>
      button.addEventListener("click", () => deleteCategory(button.dataset.question, button.dataset.deleteCategory)));
    document.querySelectorAll("[data-combine]").forEach(button =>
      button.addEventListener("click", () => combineCategories(button.dataset.combine)));
  }

  function moveAnswer(questionId, processingId, target) {
    const state = draftQuestion(questionId);
    const answer = state.answer_dispositions.find(item => item.processing_id === processingId);
    state.categories.forEach(category => {
      category.member_processing_ids = category.member_processing_ids.filter(id => id !== processingId);
      if (category.origin === "proposed") category.origin = "modified";
    });
    if (target.startsWith("existing:")) {
      Object.assign(answer, {decision: "existing_choice", choice_value: Number(target.slice(9)), final_category_id: null, unresolved_reason: null});
    } else if (target.startsWith("category:")) {
      const categoryId = target.slice(9);
      const category = state.categories.find(item => item.final_category_id === categoryId);
      category.member_processing_ids.push(processingId);
      category.member_processing_ids.sort();
      Object.assign(answer, {decision: "new_category", choice_value: null, final_category_id: categoryId, unresolved_reason: null});
    } else {
      Object.assign(answer, {decision: "unresolved", choice_value: null, final_category_id: null, unresolved_reason: "analyst acknowledged unresolved"});
    }
    state.categories = state.categories.filter(category => category.member_processing_ids.length);
    normalizeOrigins(questionId);
    autosave(true);
  }

  async function createCategory(questionId, origin, components, processingIds) {
    const english = prompt("English label (1–6 words):");
    if (!english) return;
    const arabic = prompt("Arabic label (1–6 words, Arabic script):");
    if (!arabic) return;
    saveStatus.textContent = "Creating category…";
    await saving;
    const response = await fetch("/api/categories", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        draft,
        question_id: questionId,
        english_label: english,
        arabic_label: arabic,
        origin,
        component_cluster_ids: components,
        member_processing_ids: processingIds
      })
    });
    const payload = await response.json();
    if (!response.ok) return showError(payload.error);
    draft = payload.draft;
    saveStatus.textContent = "Draft saved";
    render();
  }

  function createManualCategory(questionId) {
    const question = packageQuestion(questionId);
    const answerId = prompt(`Processing ID to place in the new category:\n${question.answers.map(item => item.processing_id).join("\n")}`);
    if (!question.answers.some(item => item.processing_id === answerId)) return showError("Choose an exact processing ID from this question.");
    createCategory(questionId, "manual", [], [answerId]);
  }

  function splitAnswer(questionId, processingId) {
    const state = draftQuestion(questionId);
    const answer = state.answer_dispositions.find(item => item.processing_id === processingId);
    const source = state.categories.find(item => item.final_category_id === answer.final_category_id);
    if (!source || source.component_cluster_ids.length !== 1) return showError("Split is available for an answer currently in one proposed category.");
    createCategory(questionId, "split", [...source.component_cluster_ids], [processingId]);
  }

  function deleteCategory(questionId, categoryId) {
    const state = draftQuestion(questionId);
    const category = state.categories.find(item => item.final_category_id === categoryId);
    if (!category || !confirm(`Delete ${category.english_label} and mark its answers unresolved?`)) return;
    category.member_processing_ids.forEach(processingId => {
      const answer = state.answer_dispositions.find(item => item.processing_id === processingId);
      Object.assign(answer, {decision: "unresolved", choice_value: null, final_category_id: null, unresolved_reason: "analyst rejected category"});
    });
    state.categories = state.categories.filter(item => item.final_category_id !== categoryId);
    normalizeOrigins(questionId);
    autosave(true);
  }

  function combineCategories(questionId) {
    const state = draftQuestion(questionId);
    const ids = prompt(`Enter two category IDs separated by a comma:\n${state.categories.map(item => item.final_category_id).join("\n")}`);
    if (!ids) return;
    const selected = ids.split(",").map(value => value.trim());
    const categories = selected.map(id => state.categories.find(item => item.final_category_id === id));
    if (categories.length !== 2 || categories.some(item => !item)) return showError("Choose exactly two valid category IDs.");
    const components = [...new Set(categories.flatMap(item => item.component_cluster_ids))].sort();
    const members = [...new Set(categories.flatMap(item => item.member_processing_ids))].sort();
    createCategory(questionId, "merged", components, members);
  }

  function normalizeOrigins(questionId) {
    const question = packageQuestion(questionId);
    const state = draftQuestion(questionId);
    const proposalByCluster = new Map(question.proposed_categories.map(item => [item.cluster_id, item]));
    const componentCount = new Map();
    state.categories.forEach(category => category.component_cluster_ids.forEach(id => componentCount.set(id, (componentCount.get(id) || 0) + 1)));
    state.categories.forEach(category => {
      if (!category.component_cluster_ids.length) category.origin = "manual";
      else if (category.component_cluster_ids.length > 1) category.origin = "merged";
      else if (componentCount.get(category.component_cluster_ids[0]) > 1) category.origin = "split";
      else {
        const proposal = proposalByCluster.get(category.component_cluster_ids[0]);
        const exactMembers = proposal && [...category.member_processing_ids].sort().join("|") === [...proposal.member_processing_ids].sort().join("|");
        const exactLabels = proposal && category.english_label === proposal.english_label && category.arabic_label === proposal.arabic_label;
        category.origin = exactMembers && exactLabels ? "proposed" : "modified";
      }
    });
  }

  function autosave(rerender = false) {
    draft.analyst_name = analystName.value;
    saveStatus.textContent = "Saving…";
    saving = saving.then(async () => {
      const response = await fetch("/api/draft", {
        method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(draft)
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error);
      draft = payload.draft;
      saveStatus.textContent = "Draft saved";
      if (rerender) render();
    }).catch(error => {
      saveStatus.textContent = "Edit not saved";
      showError(error.message);
    });
    updateCount();
  }

  function updateCount() {
    const decided = draft.review_item_dispositions.filter(item => item.disposition).length;
    completionCount.textContent = `${decided} / ${draft.review_item_dispositions.length} review items decided`;
  }

  function showError(message) {
    alert(message);
  }

  analystName.addEventListener("change", () => autosave());
  document.querySelector("#complete-review").addEventListener("click", async () => {
    draft.analyst_name = analystName.value;
    const message = document.querySelector("#completion-message");
    message.className = "";
    message.textContent = "Validating complete review…";
    await saving;
    const response = await fetch("/api/complete", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(draft)
    });
    const payload = await response.json();
    if (!response.ok) {
      message.className = "warning";
      message.textContent = payload.error;
      return;
    }
    message.className = "success";
    message.textContent = `Approval written: ${payload.approval_path}`;
  });

  render();
})();
