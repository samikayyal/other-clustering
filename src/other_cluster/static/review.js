(() => {
  let review = window.REVIEW;
  let readOnly = Boolean(window.REVIEW_READ_ONLY);
  const groundTruthEvaluation = window.GROUND_TRUTH_EVALUATION;
  const root = document.querySelector("#review-root");
  const nav = document.querySelector("#question-nav");
  const groundTruthFilter = document.querySelector("#coded-ground-truth-only");
  const groundTruthFilterCount = document.querySelector("#question-filter-count");
  const saveStatus = document.querySelector("#save-status");
  const analystName = document.querySelector("#analyst-name");
  const sidebarCompletionCount = document.querySelector("#sidebar-completion-count");
  const progressBar = document.querySelector("#progress-bar");
  const answerDrawer = document.querySelector("#answer-drawer");
  const drawerBackdrop = document.querySelector("#answer-drawer-backdrop");
  const drawerTitle = document.querySelector("#answer-drawer-title");
  const drawerQuestion = document.querySelector("#answer-drawer-question");
  const drawerContent = document.querySelector("#answer-drawer-content");
  const closeDrawerButton = document.querySelector("#close-answer-drawer");
  let drawerTrigger = null;
  let pendingSave = Promise.resolve();
  let showGroundTruthOnly = false;

  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  const questionById = id => review.questions.find(question => question.question_id === id);
  const answerById = (question, id) => question.answers.find(answer => answer.processing_id === id);
  const selected = (value, expected) => value === expected ? " selected" : "";
  const decisionCount = question => [...question.clusters, ...question.unresolved_answers]
    .filter(item => item.analyst_decision).length;
  const metric = value => Number(value ?? 0).toFixed(3);
  const groundTruthQuestionIds = new Set(
    (groundTruthEvaluation?.questions || []).map(item => item.question_id)
  );
  const questionsWithGroundTruth = () => review.questions.filter(question =>
    groundTruthQuestionIds.has(question.question_id)
  );
  const visibleQuestions = () => showGroundTruthOnly
    ? questionsWithGroundTruth()
    : review.questions;

  function renderQuestionEvaluation(questionId) {
    const evaluation = groundTruthEvaluation?.questions?.find(item => item.question_id === questionId);
    if (!evaluation) return "";
    return `<div class="question-evaluation" aria-label="Ground-truth benchmark for ${escapeHtml(questionId)}">
      <div><span>Work-tab benchmark</span><strong>${evaluation.human_cluster_count} human group${evaluation.human_cluster_count === 1 ? "" : "s"}</strong></div>
      <dl><div><dt>Unique F1</dt><dd>${metric(evaluation.canonical.pairwise_f1)}</dd></div><div><dt>Unique ARI</dt><dd>${metric(evaluation.canonical.adjusted_rand_index)}</dd></div><div><dt>Coverage</dt><dd>${Number(evaluation.canonical.clustered_percentage).toFixed(1)}%</dd></div><div><dt>Respondent F1</dt><dd>${metric(evaluation.occurrences.pairwise_f1)}</dd></div></dl>
    </div>`;
  }

  function decisionLabel(decision) {
    if (!decision) return "Not decided";
    if (decision.decision === "existing_choice") return `Existing choice ${decision.selected_choice_value}`;
    if (decision.decision === "new_category") return `New category: ${decision.english_label}`;
    return "Unresolved";
  }

  function render() {
    const questions = visibleQuestions();
    nav.innerHTML = questions.map((question, index) => {
      const total = question.clusters.length + question.unresolved_answers.length;
      const complete = total > 0 && decisionCount(question) === total;
      return `<button class="question-nav-item${index === 0 ? " is-active" : ""}${complete ? " is-complete" : ""}" type="button" data-question-nav="${escapeHtml(question.question_id)}">
        <span class="question-nav-label">${index + 1}. ${escapeHtml(question.question_id)} <span class="question-nav-clusters">${question.clusters.length} group${question.clusters.length === 1 ? "" : "s"}</span></span><span class="question-nav-count">${decisionCount(question)}/${total}</span>
      </button>`;
    }).join("");
    root.innerHTML = questions.length
      ? questions.map(renderQuestion).join("")
      : `<section class="empty-state card" aria-live="polite"><h2>No coded ground-truth questions</h2><p>The attached benchmark has no usable human codes for the review questions.</p></section>`;
    bindControls();
    updateCount();
    updateGroundTruthFilterCount(questions.length);
    if (analystName) {
      analystName.value = review.analyst_name || "";
      analystName.disabled = readOnly;
    }
    const status = document.querySelector("#review-status");
    if (status) status.textContent = readOnly ? "Completed" : "In review";
  }

  function updateGroundTruthFilterCount(visibleCount) {
    if (!groundTruthFilterCount) return;
    const codedCount = questionsWithGroundTruth().length;
    const totalCount = review.questions.length;
    groundTruthFilterCount.textContent = showGroundTruthOnly
      ? `${visibleCount} of ${totalCount} question${totalCount === 1 ? "" : "s"} shown`
      : `${codedCount} of ${totalCount} question${totalCount === 1 ? "" : "s"} have coded ground-truth`;
  }

  function renderQuestion(question, index) {
    const choices = question.existing_choices.map(choice =>
      `<li><strong>${choice.value}</strong> · ${escapeHtml(choice.english_label)} <span class="arabic">${escapeHtml(choice.arabic_label)}</span></li>`
    ).join("") || "<li>No existing answers are available.</li>";
    const clusters = question.clusters.map(cluster => renderCluster(question, cluster)).join("") || "<p class='metadata'>There are no suggested groups for this question.</p>";
    const unresolved = question.unresolved_answers.map(item => renderUnresolved(question, item)).join("") || "<p class='metadata'>No individual answers need a decision.</p>";
    return `<section id="question-${escapeHtml(question.question_id)}" class="question-card card">
      <header class="question-header"><div class="question-kicker"><span class="question-number">${index + 1}</span><span class="question-id">${escapeHtml(question.question_id)}</span></div>
        <div class="question-title-row"><h2>${escapeHtml(question.question_text.english)}</h2><span class="suggested-group-count">${question.clusters.length} suggested group${question.clusters.length === 1 ? "" : "s"}</span></div>
        <p class="arabic">${escapeHtml(question.question_text.arabic)}</p></header>
      ${renderQuestionEvaluation(question.question_id)}
      <div class="question-summary"><p>${question.answers.length} unique answer${question.answers.length === 1 ? "" : "s"} were submitted for this question.</p>
        <button class="secondary-action" type="button" data-show-answers="${escapeHtml(question.question_id)}">See all answers</button></div>
      <div class="question-sections">
        <section class="subcard"><h3>Available answer labels</h3><ul class="choice-list">${choices}</ul></section>
        <section class="subcard"><h3>Suggested groups</h3><p class="metadata">Choose what should happen to each suggested group.</p>${clusters}</section>
        <section class="subcard"><h3>Needs your attention</h3><p class="metadata">These answers were not placed in a suggested group.</p>${unresolved}</section>
      </div>
    </section>`;
  }

  function renderDecisionOptions(question, decision, allowNew) {
    const current = decision?.decision === "existing_choice"
      ? `existing_choice:${decision.selected_choice_value}`
      : decision?.decision || "";
    const choices = question.existing_choices.map(choice =>
      `<option value="existing_choice:${choice.value}"${selected(current, `existing_choice:${choice.value}`)}>${choice.value} · ${escapeHtml(choice.english_label)} · ${escapeHtml(choice.arabic_label)}</option>`
    ).join("");
    return `<option value=""${selected(current, "")}>Choose…</option>
      ${choices ? `<optgroup label="Match an existing answer">${choices}</optgroup>` : ""}
      ${allowNew ? `<option value="new_category"${selected(current, "new_category")}>Create a new answer category</option>` : ""}
      <option value="unresolved"${selected(current, "unresolved")}>Leave unresolved</option>`;
  }

  function decisionFromSelection(value, previous = null) {
    if (value.startsWith("existing_choice:")) {
      const decision = freshDecision("existing_choice", previous);
      decision.selected_choice_value = Number(value.split(":")[1]);
      return decision;
    }
    return value ? freshDecision(value, previous) : null;
  }

  function renderCluster(question, cluster) {
    const decision = cluster.analyst_decision;
    const proposal = cluster.gemini_proposal;
    const controls = readOnly
      ? `<p class="final-decision"><strong>${escapeHtml(decisionLabel(decision))}</strong>${decision && decision.allocated_value !== null ? ` · allocated value ${decision.allocated_value}` : ""}</p>`
      : `<label>Choose what to do<select data-cluster-decision="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}">
          ${renderDecisionOptions(question, decision, true)}
        </select></label>
        ${decision?.decision === "new_category" ? `<div class="labels"><label>New English label<input data-cluster-label="english_label" data-cluster="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(decision.english_label)}"></label><label>New Arabic label<input class="arabic" data-cluster-label="arabic_label" data-cluster="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}" value="${escapeHtml(decision.arabic_label)}"></label></div>` : ""}`;
    return `<article class="review-item cluster-card"><div class="cluster-heading"><strong class="item-title">Suggested group</strong><button class="cluster-answers-action" type="button" data-show-cluster-answers="${escapeHtml(cluster.cluster_id)}" data-question="${escapeHtml(question.question_id)}">View ${cluster.member_processing_ids.length} answer${cluster.member_processing_ids.length === 1 ? "" : "s"}</button></div>
      <p class="proposal"><strong>Suggested by the analysis:</strong> ${proposalSummary(proposal)}</p>
      <div class="decision-controls">${controls}</div></article>`;
  }

  function proposalSummary(proposal) {
    if (proposal.decision === "existing_choice") return `match existing answer ${escapeHtml(proposal.selected_choice_value)}`;
    if (proposal.decision === "new_category") return `create “${escapeHtml(proposal.english_label)}” / “${escapeHtml(proposal.arabic_label)}”`;
    if (proposal.provider_error) return "no suggestion was available";
    return "keep this group unresolved";
  }

  function renderUnresolved(question, item) {
    const answer = answerById(question, item.processing_id);
    const decision = item.analyst_decision;
    const controls = readOnly
      ? `<p class="final-decision"><strong>${escapeHtml(decisionLabel(decision))}</strong></p>`
      : `<label>Choose what to do<select data-unresolved-decision="${escapeHtml(item.processing_id)}" data-question="${escapeHtml(question.question_id)}">
          ${renderDecisionOptions(question, decision, false)}
        </select></label>`;
    return `<article class="review-item"><p class="answer-text">${escapeHtml(answer ? answer.text : item.processing_id)}</p><p class="metadata">This answer needs an individual decision.</p><div class="decision-controls">${controls}</div></article>`;
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
    document.querySelectorAll("[data-question-nav]").forEach(button => button.addEventListener("click", () => {
      const questionId = button.dataset.questionNav;
      document.getElementById(`question-${questionId}`)?.scrollIntoView({behavior: "smooth", block: "start"});
      document.querySelectorAll("[data-question-nav]").forEach(item => item.classList.toggle("is-active", item === button));
    }));
    document.querySelectorAll("[data-show-answers]").forEach(button => button.addEventListener("click", () => {
      openAnswerDrawer(questionById(button.dataset.showAnswers), button);
    }));
    document.querySelectorAll("[data-show-cluster-answers]").forEach(button => button.addEventListener("click", () => {
      const question = questionById(button.dataset.question);
      const item = cluster(button.dataset.question, button.dataset.showClusterAnswers);
      openAnswerDrawer(question, button, item?.member_processing_ids, "Answers in this suggested group");
    }));
    if (readOnly) return;
    document.querySelectorAll("[data-cluster-decision]").forEach(select => select.addEventListener("change", () => {
      const item = cluster(select.dataset.question, select.dataset.cluster);
      item.analyst_decision = decisionFromSelection(select.value, item.analyst_decision);
      render();
      if (item.analyst_decision?.decision !== "new_category") save(false);
    }));
    document.querySelectorAll("[data-cluster-label]").forEach(input => input.addEventListener("change", () => {
      const item = cluster(input.dataset.question, input.dataset.cluster);
      if (item.analyst_decision) item.analyst_decision[input.dataset.clusterLabel] = input.value;
      if (item.analyst_decision?.english_label.trim() && item.analyst_decision.arabic_label.trim()) save(false);
    }));
    document.querySelectorAll("[data-unresolved-decision]").forEach(select => select.addEventListener("change", () => {
      const item = unresolved(select.dataset.question, select.dataset.unresolvedDecision);
      item.analyst_decision = decisionFromSelection(select.value);
      render();
      if (item.analyst_decision) save(false);
    }));
  }

  function openAnswerDrawer(question, trigger, processingIds = null, title = null) {
    if (!question) return;
    drawerTrigger = trigger;
    const answers = processingIds
      ? processingIds.map(id => answerById(question, id)).filter(Boolean)
      : question.answers;
    drawerTitle.textContent = title || `${answers.length} unique answer${answers.length === 1 ? "" : "s"}`;
    drawerQuestion.textContent = question.question_text.english;
    drawerContent.innerHTML = answers.map(answer => {
      const locations = answer.row_mappings.map(mapping => escapeHtml(mapping.coordinate)).join(", ");
      return `<article class="answer-entry"><p class="answer-text">${escapeHtml(answer.text)}</p>
        <p class="metadata">Submitted ${answer.occurrence_count} time${answer.occurrence_count === 1 ? "" : "s"}</p>
        <details><summary>Show source locations</summary><p class="answer-details">${locations}</p></details></article>`;
    }).join("") || "<p class='metadata'>No unique answers were submitted for this question.</p>";
    drawerBackdrop.hidden = false;
    answerDrawer.classList.add("is-open");
    answerDrawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("drawer-open");
    closeDrawerButton.focus();
  }

  function closeAnswerDrawer() {
    if (answerDrawer.getAttribute("aria-hidden") === "true") return;
    answerDrawer.classList.remove("is-open");
    answerDrawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("drawer-open");
    window.setTimeout(() => { drawerBackdrop.hidden = true; }, 200);
    drawerTrigger?.focus();
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
    if (count) count.textContent = `${decided} of ${all.length} decisions made`;
    if (sidebarCompletionCount) sidebarCompletionCount.textContent = `${decided}/${all.length}`;
    if (progressBar) progressBar.style.width = `${all.length ? (decided / all.length) * 100 : 0}%`;
  }

  function showMessage(message, error) {
    const target = document.querySelector("#completion-message");
    if (!target) { alert(message); return; }
    target.textContent = message;
    target.className = error ? "warning" : "success";
  }

  if (analystName && !readOnly) analystName.addEventListener("change", () => save(false));
  if (groundTruthFilter) groundTruthFilter.addEventListener("change", () => {
    showGroundTruthOnly = groundTruthFilter.checked;
    render();
  });
  closeDrawerButton.addEventListener("click", closeAnswerDrawer);
  drawerBackdrop.addEventListener("click", closeAnswerDrawer);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeAnswerDrawer();
  });
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
