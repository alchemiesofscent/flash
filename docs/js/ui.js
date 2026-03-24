// UI rendering and event handling module

import { getProgress, updateProgress, recordQuiz, getLevelStats, isMastered, getSettings, saveSettings, resetProgress } from './storage.js';
import { fetchVocab, getWordsForLevel, getAllWords } from './data.js';
import { generateQuestionSet, countFormIdEligible } from './questions.js';
import { createSession, currentQuestion, answerQuestion, getResults } from './state.js';
import { renderPwaHomePrompt } from './pwa.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let currentSession = null;
let currentWorkId = null;
let currentVocab = null;
let selectedLevel = null;
let selectedMode = null;

// ---------------------------------------------------------------------------
// Screen management
// ---------------------------------------------------------------------------

function showScreen(id, { replaceState = false } = {}) {
  $$('.screen').forEach(s => s.classList.remove('active'));
  const screen = $(`#${id}`);
  if (screen) screen.classList.add('active');

  const state = { screen: id };
  const url = `#${id}`;
  if (replaceState) {
    history.replaceState(state, '', url);
  } else {
    history.pushState(state, '', url);
  }
}

// ---------------------------------------------------------------------------
// Home screen
// ---------------------------------------------------------------------------

export function renderHome(works) {
  const home = $('#home');
  home.innerHTML = `
    <div class="screen-inner">
      <div class="card hero-card">
        <h2>Greek Vocabulary</h2>
        <p>Master Ancient Greek vocabulary through flashcards and quizzes.</p>
        <p class="subtitle">Select a text to begin studying.</p>
      </div>
      <div class="works-list">
        ${works.map(w => `
          <button class="card work-card" data-work-id="${w.id}">
            <h3>${w.title}</h3>
            <p class="work-author">${w.author}</p>
            <p class="work-count">${w.lemma_count} words</p>
          </button>
        `).join('')}
      </div>
    </div>
  `;
  renderPwaHomePrompt(home.querySelector('.screen-inner'));

  home.addEventListener('click', async (e) => {
    const card = e.target.closest('[data-work-id]');
    if (!card) return;
    const workId = card.dataset.workId;
    await selectWork(workId);
  });

  showScreen('home', { replaceState: true });
}

async function selectWork(workId) {
  currentWorkId = workId;
  const settings = getSettings();
  settings.lastWorkId = workId;
  saveSettings(settings);

  try {
    currentVocab = await fetchVocab(workId);
    renderLevelSelect();
  } catch (err) {
    console.error('Failed to load vocab:', err);
    alert('Failed to load vocabulary data. Please try again.');
  }
}

// ---------------------------------------------------------------------------
// Combined level + mode select screen
// ---------------------------------------------------------------------------

const LEVEL_NAMES = { 1: 'Beginner', 2: 'Intermediate', 3: 'Advanced' };

function renderLevelSelect() {
  selectedLevel = null;
  selectedMode = null;

  const screen = $('#level-select');
  const levels = [];
  for (let i = 1; i <= 3; i++) {
    const stats = getLevelStats(currentWorkId, currentVocab.words, i);
    const wordCount = getWordsForLevel(currentVocab, i).length;
    levels.push({ level: i, name: LEVEL_NAMES[i], wordCount, ...stats });
  }

  screen.innerHTML = `
    <div class="screen-inner setup-form">
      <div class="setup-header">
        <h2>${escapeHTML(currentVocab.metadata.title)}</h2>
        <p class="text-muted">${escapeHTML(currentVocab.metadata.author)} &middot; ${currentVocab.metadata.unique_lemmas} words</p>
      </div>

      <div class="form-group">
        <label class="form-label">Difficulty</label>
        <div class="seg-control seg-control--stack-mobile" id="seg-level">
          ${levels.map(l => `
            <button class="seg-option" data-level="${l.level}">
              <span class="seg-option-label">${l.name}</span>
              <span class="seg-option-detail">${l.wordCount} words &middot; ${l.percentage}%</span>
            </button>
          `).join('')}
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">Quiz Mode</label>
        <div class="seg-control seg-control--vertical" id="seg-mode">
          <button class="seg-option" data-mode="greek-to-english">
            <span class="seg-option-label">Greek &rarr; English</span>
          </button>
          <button class="seg-option" data-mode="english-to-greek">
            <span class="seg-option-label">English &rarr; Greek</span>
          </button>
          <button class="seg-option" data-mode="form-id">
            <span class="seg-option-label">Morphology</span>
          </button>
          <button class="seg-option" data-mode="mixed">
            <span class="seg-option-label">Mixed</span>
          </button>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label" for="question-count">Questions: <span id="count-display">10</span></label>
        <input type="range" id="question-count" class="range-input" min="5" max="50" step="5" value="10">
      </div>

      <div class="action-row">
        <button class="btn btn-primary start-btn" id="btn-start-quiz" disabled>Start Quiz</button>
      </div>
      <div class="action-row action-row--secondary">
        <button class="btn btn-secondary" id="btn-progress">Progress</button>
        <button class="btn btn-secondary" id="btn-back-home">Back</button>
      </div>
    </div>
  `;

  // Level selection
  screen.querySelector('#seg-level').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-level]');
    if (!btn) return;
    selectedLevel = parseInt(btn.dataset.level);

    screen.querySelectorAll('#seg-level .seg-option').forEach(b => b.classList.remove('seg-option--active'));
    btn.classList.add('seg-option--active');

    // Update morphology enabled state
    const words = getWordsForLevel(currentVocab, selectedLevel);
    const formIdCount = countFormIdEligible(words);
    const morphBtn = screen.querySelector('[data-mode="form-id"]');
    if (formIdCount < 4) {
      morphBtn.disabled = true;
      morphBtn.classList.add('seg-option--disabled');
      if (selectedMode === 'form-id') {
        selectedMode = null;
        morphBtn.classList.remove('seg-option--active');
      }
    } else {
      morphBtn.disabled = false;
      morphBtn.classList.remove('seg-option--disabled');
    }

    // Update max question count to match level word count
    const slider = screen.querySelector('#question-count');
    const maxWords = words.length;
    slider.max = maxWords;
    if (parseInt(slider.value) > maxWords) {
      slider.value = maxWords;
    }
    screen.querySelector('#count-display').textContent = slider.value;

    updateStartButton();
  });

  // Mode selection
  screen.querySelector('#seg-mode').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-mode]');
    if (!btn || btn.disabled) return;
    selectedMode = btn.dataset.mode;

    screen.querySelectorAll('#seg-mode .seg-option').forEach(b => b.classList.remove('seg-option--active'));
    btn.classList.add('seg-option--active');

    updateStartButton();
  });

  // Question count slider
  screen.querySelector('#question-count').addEventListener('input', (e) => {
    screen.querySelector('#count-display').textContent = e.target.value;
  });

  function updateStartButton() {
    const startBtn = $('#btn-start-quiz');
    startBtn.disabled = !(selectedLevel && selectedMode);
  }

  $('#btn-start-quiz')?.addEventListener('click', () => {
    if (!selectedLevel || !selectedMode) return;
    const words = getWordsForLevel(currentVocab, selectedLevel);
    const count = parseInt(screen.querySelector('#question-count').value);
    startSession(selectedLevel, words, selectedMode, count);
  });

  $('#btn-progress')?.addEventListener('click', () => renderProgressDashboard());
  $('#btn-back-home')?.addEventListener('click', () => showScreen('home'));

  showScreen('level-select');
}

// ---------------------------------------------------------------------------
// Start a session
// ---------------------------------------------------------------------------

function startSession(level, words, mode, count) {
  if (words.length === 0) {
    alert('No words available for this level.');
    return;
  }

  const allWords = getAllWords(currentVocab);
  count = count || words.length;

  const questions = generateQuestionSet(words, allWords, {
    count,
    mode,
  });

  if (questions.length === 0) {
    alert('Could not generate questions for this level.');
    return;
  }

  currentSession = createSession({
    questions,
    workId: currentWorkId,
    level,
    mode
  });

  renderQuizCard();
}

// ---------------------------------------------------------------------------
// Quiz card rendering
// ---------------------------------------------------------------------------

function renderQuizCard() {
  const question = currentQuestion(currentSession);
  if (!question) {
    finishSession();
    return;
  }

  const screen = $('#quiz');
  const qNum = currentSession.currentIndex + 1;
  const qTotal = currentSession.questions.length;

  let typeLabel = '';
  switch (question.type) {
    case 'greek-to-english': typeLabel = 'Greek → English'; break;
    case 'english-to-greek': typeLabel = 'English → Greek'; break;
    case 'form-id': typeLabel = 'Identify the Form'; break;
  }

  // Determine if prompt text is Greek (for font styling)
  const promptIsGreek = question.type === 'greek-to-english' || question.type === 'form-id';

  screen.innerHTML = `
    <div class="screen-inner">
    <div class="quiz-header">
      <span class="quiz-progress">${qNum} / ${qTotal}</span>
      <span class="quiz-type">${typeLabel}</span>
      <button class="quiz-quit" id="btn-quit-quiz" title="Quit quiz">&times;</button>
      <div class="progress-bar quiz-progress-bar">
        <div class="progress-fill" style="width: ${(qNum / qTotal) * 100}%"></div>
      </div>
    </div>
    <div class="flip-card" id="flip-card">
      <div class="flip-card-inner">
        <div class="flip-card-front card quiz-card">
          <div class="quiz-prompt">
            <p class="prompt-text ${promptIsGreek ? 'greek-text' : ''}">${question.prompt.text}</p>
            ${question.prompt.subtext ? `<p class="prompt-subtext">${question.prompt.subtext}</p>` : ''}
          </div>
          <div class="quiz-answer" id="answer-area"></div>
        </div>
        <div class="flip-card-back card quiz-card">
          <div id="feedback-area"></div>
        </div>
      </div>
    </div>
    </div>
  `;

  renderMultipleChoice(question);
  $('#btn-quit-quiz')?.addEventListener('click', () => renderLevelSelect());
  showScreen('quiz', { replaceState: true });
}

function renderMultipleChoice(question) {
  const area = $('#answer-area');
  // Choices are Greek for english-to-greek questions
  const choicesAreGreek = question.type === 'english-to-greek';
  const choicesClass = question.type === 'form-id' ? 'mc-choices mc-choices--morphology' : 'mc-choices';
  area.innerHTML = `
    <div class="${choicesClass}">
      ${question.choices.map((choice, i) => `
        <button class="btn btn-choice ${choicesAreGreek ? 'greek-text' : ''}" data-choice="${i}" data-value="${escapeAttr(choice)}">
          ${escapeHTML(choice)}
        </button>
      `).join('')}
    </div>
  `;

  area.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-choice]');
    if (!btn || btn.disabled) return;

    const userAnswer = btn.dataset.value;
    handleAnswer(question, userAnswer);
  });
}

// ---------------------------------------------------------------------------
// Answer handling
// ---------------------------------------------------------------------------

function handleAnswer(question, userAnswer) {
  const correct = userAnswer === question.correctAnswer;

  // Update progress
  updateProgress(currentWorkId, question.wordId, correct);

  // Record answer in session
  currentSession = answerQuestion(currentSession, userAnswer, { correct });

  // Show feedback
  showFeedback(question, userAnswer, correct);
}

function buildContextHTML(question) {
  const contexts = question.metadata.contexts;
  if (!contexts || contexts.length === 0) return '';

  // Pick context matching the prompt form if possible, else first
  let ctx = contexts[0];
  const promptForm = question.prompt.text;
  const match = contexts.find(c => c.form === promptForm);
  if (match) ctx = match;

  // Build sentence with highlighted word
  const sentence = ctx.sentence;
  const before = escapeHTML(sentence.slice(0, ctx.highlight_start));
  const highlighted = escapeHTML(sentence.slice(ctx.highlight_start, ctx.highlight_end));
  const after = escapeHTML(sentence.slice(ctx.highlight_end));

  return `
    <div class="word-context">
      <p class="context-greek greek-text">${before}<mark>${highlighted}</mark>${after}</p>
      ${ctx.translation ? `<p class="context-translation">${highlightTranslation(ctx, question.metadata.context_definition, question.metadata.definition)}</p>` : ''}
      <p class="context-ref">— ${escapeHTML(ctx.ref)}</p>
    </div>
  `;
}

function showFeedback(question, userAnswer, correct) {
  const feedback = $('#feedback-area');

  // Disable inputs
  $$('.btn-choice').forEach(b => b.disabled = true);

  // Highlight correct/incorrect MC choices
  $$('.btn-choice').forEach(btn => {
    if (btn.dataset.value === question.correctAnswer) {
      btn.classList.add('choice-correct');
    } else if (btn.dataset.value === userAnswer && !correct) {
      btn.classList.add('choice-incorrect');
    }
  });

  let feedbackHTML;
  if (correct) {
    feedbackHTML = `<div class="feedback-correct"><span>&#10003; Correct!</span></div>`;
  } else {
    feedbackHTML = `
      <div class="feedback-incorrect">
        <span>&#10007; The answer is:</span>
        <p class="correct-answer">${escapeHTML(question.correctAnswer)}</p>
      </div>`;
  }

  // Word details
  feedbackHTML += `
    <div class="word-details">
      <p>${question.type === 'greek-to-english' ? `<span class="feedback-label">Dictionary form</span> ` : ''}<strong class="greek-text">${escapeHTML(question.metadata.lemma)}</strong> — ${escapeHTML(question.metadata.context_definition || question.metadata.definition)}${question.metadata.context_definition && question.metadata.context_definition !== question.metadata.definition ? ` <span class="text-muted">(LSJ: ${escapeHTML(question.metadata.definition)})</span>` : ''}</p>
      ${question.metadata.etymology ? `<p class="word-etymology">${escapeHTML(question.metadata.etymology)}</p>` : ''}
      ${question.metadata.forms.length > 0 ? `
        <details>
          <summary>Forms (${question.metadata.forms.length})</summary>
          <ul class="forms-list">
            ${question.metadata.forms.map(f => `
              <li><span class="form-text greek-text">${escapeHTML(f.form)}</span> <span class="form-morph">${escapeHTML(f.morphology)}</span></li>
            `).join('')}
          </ul>
        </details>
      ` : ''}
    </div>
  `;

  // Context block
  feedbackHTML += buildContextHTML(question);

  feedbackHTML += `
    <div class="feedback-actions">
      <button class="btn btn-primary" id="btn-next">Next</button>
    </div>
  `;

  feedback.innerHTML = feedbackHTML;

  // Trigger flip animation with height management
  const flipCard = $('#flip-card');
  if (flipCard) {
    const inner = flipCard.querySelector('.flip-card-inner');
    const front = flipCard.querySelector('.flip-card-front');
    const back = flipCard.querySelector('.flip-card-back');

    // Lock height to front card's current height before flip
    inner.style.height = front.offsetHeight + 'px';

    flipCard.classList.add('flipped');

    // After flip animation completes, smoothly transition to back card's height
    inner.addEventListener('transitionend', function onFlipDone(e) {
      if (e.propertyName !== 'transform') return;
      inner.removeEventListener('transitionend', onFlipDone);
      inner.style.height = back.offsetHeight + 'px';
    });
  }

  $('#btn-next')?.addEventListener('click', () => renderQuizCard());
}

// ---------------------------------------------------------------------------
// Results screen
// ---------------------------------------------------------------------------

function finishSession() {
  const results = getResults(currentSession);

  // Record quiz history
  recordQuiz(currentWorkId, currentSession.level, results.correct, results.total, currentSession.mode);

  renderResults(results);
}

function renderResults(results) {
  const screen = $('#results');
  const pct = results.score;

  let grade = '';
  if (pct >= 90) grade = 'Excellent!';
  else if (pct >= 70) grade = 'Good job!';
  else if (pct >= 50) grade = 'Keep practicing!';
  else grade = 'Keep at it!';

  screen.innerHTML = `
    <div class="screen-inner">
    <div class="card results-card">
      <h2>Results</h2>
      <div class="score-display">
        <span class="score-number">${results.correct}</span>
        <span class="score-divider">/</span>
        <span class="score-total">${results.total}</span>
      </div>
      <p class="score-pct">${pct}%</p>
      <p class="score-grade">${grade}</p>
      ${results.duration ? `<p class="score-time">${formatDuration(results.duration)}</p>` : ''}
    </div>
    <details class="results-details">
      <summary>Question Review (${results.total} questions)</summary>
      <ul class="results-list">
        ${results.details.map((d, i) => {
          const a = d.answer;
          const q = d.question;
          const icon = a?.correct ? '&#10003;' : '&#10007;';
          const cls = a?.correct ? 'result-correct' : 'result-incorrect';
          return `
            <li class="${cls}">
              <span class="result-icon">${icon}</span>
              <div class="result-content">
                <p class="result-prompt">${escapeHTML(q.prompt.text)}</p>
                <p class="result-answer">Answer: <strong>${escapeHTML(q.correctAnswer)}</strong></p>
                ${a && !a.correct ? `<p class="result-user">Your answer: ${escapeHTML(a.userAnswer)}</p>` : ''}
              </div>
            </li>`;
        }).join('')}
      </ul>
    </details>
    <div class="action-row">
      <button class="btn btn-primary" id="btn-retry">Try Again</button>
      <button class="btn btn-secondary" id="btn-back-to-levels">Back to Levels</button>
    </div>
    </div>
  `;

  $('#btn-retry')?.addEventListener('click', () => {
    const level = currentSession.level;
    const mode = currentSession.mode;
    const words = getWordsForLevel(currentVocab, level);
    startSession(level, words, mode);
  });

  $('#btn-back-to-levels')?.addEventListener('click', () => renderLevelSelect());

  showScreen('results');
}

// ---------------------------------------------------------------------------
// Progress dashboard
// ---------------------------------------------------------------------------

function renderProgressDashboard() {
  const screen = $('#progress');
  const progress = getProgress(currentWorkId);
  const allWords = getAllWords(currentVocab);

  const totalMastered = allWords.filter(w => isMastered(progress.words[String(w.id)])).length;
  const totalSeen = allWords.filter(w => progress.words[String(w.id)]).length;

  let levelsHTML = '';
  for (let i = 1; i <= 3; i++) {
    const stats = getLevelStats(currentWorkId, allWords, i);
    levelsHTML += `
      <div class="progress-level-row">
        <span class="progress-level-label">${LEVEL_NAMES[i]}</span>
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${stats.percentage}%"></div>
        </div>
        <span class="progress-level-stats">${stats.mastered}/${stats.total}</span>
      </div>
    `;
  }

  screen.innerHTML = `
    <div class="screen-inner">
    <div class="card">
      <h2>Progress — ${currentVocab.metadata.title}</h2>
      <div class="progress-summary">
        <div class="stat-box">
          <span class="stat-number">${totalSeen}</span>
          <span class="stat-label">Words Seen</span>
        </div>
        <div class="stat-box">
          <span class="stat-number">${totalMastered}</span>
          <span class="stat-label">Mastered</span>
        </div>
        <div class="stat-box">
          <span class="stat-number">${allWords.length}</span>
          <span class="stat-label">Total</span>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>By Level</h3>
      ${levelsHTML}
    </div>
    ${progress.quizHistory.length > 0 ? `
      <div class="card">
        <h3>Recent Quizzes</h3>
        <ul class="quiz-history">
          ${progress.quizHistory.slice(-10).reverse().map(q => `
            <li>
              <span>${LEVEL_NAMES[q.level] || 'Level ' + q.level}</span>
              ${q.mode ? `<span>${q.mode}</span>` : ''}
              <span>${q.score}/${q.total}</span>
              <span>${new Date(q.date).toLocaleDateString()}</span>
            </li>
          `).join('')}
        </ul>
      </div>
    ` : ''}
    <div class="action-row">
      <button class="btn btn-secondary" id="btn-back-from-progress">Back to Levels</button>
    </div>
    </div>
  `;

  $('#btn-back-from-progress')?.addEventListener('click', () => renderLevelSelect());
  showScreen('progress');
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function highlightTranslation(ctx, gloss, definition) {
  const translation = ctx.translation;
  const start = ctx.translation_highlight_start;
  const end = ctx.translation_highlight_end;

  if (
    Number.isInteger(start) &&
    Number.isInteger(end) &&
    start >= 0 &&
    end <= translation.length &&
    start < end
  ) {
    const before = escapeHTML(translation.slice(0, start));
    const highlight = escapeHTML(translation.slice(start, end));
    const after = escapeHTML(translation.slice(end));
    return `${before}<mark>${highlight}</mark>${after}`;
  }

  return escapeHTML(translation);
}

function escapeHTML(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatDuration(ms) {
  const secs = Math.floor(ms / 1000);
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  if (mins === 0) return `${remSecs}s`;
  return `${mins}m ${remSecs}s`;
}

export { showScreen, selectWork, renderLevelSelect };
