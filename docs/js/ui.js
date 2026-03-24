// UI rendering and event handling module

import {
  getProgress,
  updateProgress,
  getLevelStats,
  isMastered,
  getSettings,
  saveSettings,
  getSavedSession,
  saveSession,
  clearSavedSession
} from './storage.js';
import { fetchVocab, getWordsForLevel, getAllWords } from './data.js';
import { seedQuestionQueue, generateAdaptiveQuestion, countFormIdEligible } from './questions.js';
import {
  createSession,
  restoreSession,
  currentQuestion,
  getAnswerRecord,
  answerCurrentQuestion,
  appendQuestions,
  goToPreviousQuestion,
  goToNextQuestion,
  canGoPrevious,
  getSessionProgress
} from './state.js';
import { renderPwaHomePrompt } from './pwa.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const INITIAL_QUEUE_SIZE = 5;
const MIN_AHEAD_BUFFER = 3;

let currentSession = null;
let currentWorkId = null;
let currentVocab = null;
let selectedLevel = null;
let selectedMode = null;
let studyMenuController = null;

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
  cleanupStudyMenuListeners();
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

  home.onclick = async (e) => {
    const card = e.target.closest('[data-work-id]');
    if (!card) return;
    await selectWork(card.dataset.workId);
  };

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
  cleanupStudyMenuListeners();
  selectedLevel = null;
  selectedMode = null;

  const screen = $('#level-select');
  const levels = [];
  for (let i = 1; i <= 3; i += 1) {
    const stats = getLevelStats(currentWorkId, currentVocab.words, i);
    const wordCount = getWordsForLevel(currentVocab, i).length;
    levels.push({ level: i, name: LEVEL_NAMES[i], wordCount, ...stats });
  }

  const savedSession = loadSavedSessionForCurrentWork();
  const savedProgress = savedSession ? getSessionProgress(savedSession) : null;
  const startButtonLabel = savedSession ? 'Start New Study Session' : 'Start Studying';

  screen.innerHTML = `
    <div class="screen-inner setup-form">
      <div class="setup-header">
        <h2>${escapeHTML(currentVocab.metadata.title)}</h2>
        <p class="text-muted">${escapeHTML(currentVocab.metadata.author)} &middot; ${currentVocab.metadata.unique_lemmas} words</p>
      </div>

      ${savedSession ? `
        <div class="card session-resume-card">
          <h3>Saved Study Session</h3>
          <p class="session-resume-card__meta">${escapeHTML(LEVEL_NAMES[savedSession.level] || `Level ${savedSession.level}`)} &middot; ${escapeHTML(formatModeLabel(savedSession.mode))}</p>
          <div class="session-resume-card__stats">
            <span>Seen ${savedProgress.seen}</span>
            <span>Accuracy ${savedProgress.accuracy}%</span>
            <span>Streak ${savedProgress.streak}</span>
          </div>
          <div class="action-row action-row--compact">
            <button class="btn btn-primary" id="btn-resume-session">Resume Session</button>
            <button class="btn btn-secondary" id="btn-discard-session">Discard Saved</button>
          </div>
          <p class="session-resume-card__note">Starting a new session replaces this saved stream.</p>
        </div>
      ` : ''}

      <div class="form-group">
        <label class="form-label">Difficulty</label>
        <div class="seg-control seg-control--stack-mobile" id="seg-level">
          ${levels.map(l => `
            <button class="seg-option" data-level="${l.level}">
              <span class="seg-option-label">${l.name}</span>
              <span class="seg-option-detail">${l.wordCount} words &middot; ${l.percentage}% mastered</span>
            </button>
          `).join('')}
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">Study Mode</label>
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

      <div class="action-row">
        <button class="btn btn-primary start-btn" id="btn-start-quiz" disabled>${startButtonLabel}</button>
      </div>
      <div class="action-row action-row--secondary">
        <button class="btn btn-secondary" id="btn-progress">Progress</button>
        <button class="btn btn-secondary" id="btn-back-home">Back</button>
      </div>
    </div>
  `;

  screen.querySelector('#seg-level').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-level]');
    if (!btn) return;
    selectedLevel = parseInt(btn.dataset.level, 10);

    screen.querySelectorAll('#seg-level .seg-option').forEach(b => b.classList.remove('seg-option--active'));
    btn.classList.add('seg-option--active');

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

    updateStartButton();
  });

  screen.querySelector('#seg-mode').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-mode]');
    if (!btn || btn.disabled) return;
    selectedMode = btn.dataset.mode;

    screen.querySelectorAll('#seg-mode .seg-option').forEach(b => b.classList.remove('seg-option--active'));
    btn.classList.add('seg-option--active');

    updateStartButton();
  });

  function updateStartButton() {
    $('#btn-start-quiz').disabled = !(selectedLevel && selectedMode);
  }

  $('#btn-start-quiz')?.addEventListener('click', () => {
    if (!selectedLevel || !selectedMode) return;
    startSession(selectedLevel, selectedMode);
  });

  $('#btn-progress')?.addEventListener('click', () => renderProgressDashboard());
  $('#btn-back-home')?.addEventListener('click', () => showScreen('home'));
  $('#btn-resume-session')?.addEventListener('click', () => {
    if (!savedSession) return;
    currentSession = savedSession;
    renderStudyCard();
  });
  $('#btn-discard-session')?.addEventListener('click', () => {
    clearSavedSession(currentWorkId);
    renderLevelSelect();
  });

  showScreen('level-select');
}

function loadSavedSessionForCurrentWork() {
  const saved = getSavedSession(currentWorkId);
  if (!saved) return null;

  const restored = restoreSession(saved);
  if (!restored || restored.ended) {
    clearSavedSession(currentWorkId);
    return null;
  }

  return restored;
}

function persistCurrentSession() {
  if (!currentSession) return;

  if (currentSession.ended) {
    clearSavedSession(currentSession.workId);
  } else {
    saveSession(currentSession);
  }
}

function cleanupStudyMenuListeners() {
  if (studyMenuController) {
    studyMenuController.abort();
    studyMenuController = null;
  }
  const navLinks = $('#nav-links');
  if (navLinks) {
    navLinks.innerHTML = '';
  }
}

function restartCurrentSession() {
  if (!currentSession) return;

  const { level, mode } = currentSession;
  const confirmed = window.confirm('Restart this study session? Current progress in this session will be lost.');
  if (!confirmed) return;

  cleanupStudyMenuListeners();
  clearSavedSession(currentWorkId);
  currentSession = null;
  startSession(level, mode);
}

function renderGlobalStudyMenu() {
  const navLinks = $('#nav-links');
  if (!navLinks || !currentSession) return;

  navLinks.innerHTML = `
    <div class="header-session-menu">
      <button
        class="quiz-menu-toggle"
        id="btn-session-menu"
        type="button"
        aria-label="Open session menu"
        aria-expanded="false"
        aria-controls="session-menu"
      >
        <span></span>
        <span></span>
        <span></span>
      </button>
      <div class="quiz-menu" id="session-menu" hidden>
        <button class="quiz-menu__item" id="btn-save-quit" type="button">Save &amp; Quit</button>
        <button class="quiz-menu__item" id="btn-restart-session" type="button">Restart</button>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Start a session
// ---------------------------------------------------------------------------

function startSession(level, mode) {
  const levelWords = getWordsForLevel(currentVocab, level);
  if (levelWords.length === 0) {
    alert('No words available for this level.');
    return;
  }

  const allWords = getAllWords(currentVocab);
  const seedQuestions = seedQuestionQueue(levelWords, allWords, mode, INITIAL_QUEUE_SIZE);
  if (seedQuestions.length === 0) {
    alert('Could not generate study cards for this level.');
    return;
  }

  currentSession = createSession({
    questions: seedQuestions,
    workId: currentWorkId,
    level,
    mode
  });
  persistCurrentSession();
  renderStudyCard();
}

function ensureQuestionBuffer(minAhead = MIN_AHEAD_BUFFER) {
  if (!currentSession || !currentVocab) return;

  const ahead = currentSession.questions.length - currentSession.currentIndex - 1;
  const needed = minAhead - ahead;
  if (needed <= 0) return;

  const levelWords = getWordsForLevel(currentVocab, currentSession.level);
  const allWords = getAllWords(currentVocab);
  const additions = [];
  let workingSession = currentSession;

  for (let i = 0; i < needed; i += 1) {
    const question = generateAdaptiveQuestion(levelWords, allWords, workingSession, currentSession.mode);
    if (!question) break;
    additions.push(question);
    workingSession = appendQuestions(workingSession, [question]);
  }

  if (additions.length > 0) {
    currentSession = appendQuestions(currentSession, additions);
    persistCurrentSession();
  }
}

// ---------------------------------------------------------------------------
// Study card rendering
// ---------------------------------------------------------------------------

function renderStudyCard() {
  cleanupStudyMenuListeners();
  ensureQuestionBuffer();

  const question = currentQuestion(currentSession);
  if (!question) {
    renderLevelSelect();
    return;
  }

  const screen = $('#quiz');
  const progress = getSessionProgress(currentSession);
  const answer = getAnswerRecord(currentSession, question.id);
  const promptIsGreek = question.type === 'greek-to-english' || question.type === 'form-id';

  screen.innerHTML = `
    <div class="screen-inner">
      <div class="quiz-header">
        <div class="quiz-header__main">
          <span class="quiz-progress">Card ${progress.currentNumber}</span>
          <span class="quiz-type">${escapeHTML(formatQuestionType(question.type))}</span>
          <span class="quiz-phase">${escapeHTML(LEVEL_NAMES[currentSession.level] || `Level ${currentSession.level}`)}</span>
        </div>
        <div class="quiz-header__scoreboard">
          <span class="score-chip">Seen ${progress.seen}</span>
          <span class="score-chip">Accuracy ${progress.accuracy}%</span>
          <span class="score-chip score-chip--secondary">Streak ${progress.streak}</span>
        </div>
      </div>
      <div class="flip-card" id="flip-card">
        <div class="flip-card-inner">
          <div class="flip-card-front card quiz-card">
            <div class="quiz-prompt">
              <p class="prompt-text ${promptIsGreek ? 'greek-text' : ''}">${escapeHTML(question.prompt.text)}</p>
              ${question.prompt.subtext ? `<p class="prompt-subtext">${escapeHTML(question.prompt.subtext)}</p>` : ''}
            </div>
            <div class="quiz-answer" id="answer-area"></div>
            <div class="quiz-nav quiz-nav--front" id="front-nav"></div>
          </div>
          <div class="flip-card-back card quiz-card">
            <div id="feedback-area"></div>
          </div>
        </div>
      </div>
    </div>
  `;

  renderMultipleChoice(question);
  renderFrontNav(Boolean(answer));
  renderGlobalStudyMenu();
  setupStudyHeaderMenu();

  if (answer) {
    showFeedback(question, answer.userAnswer, answer.correct, { instant: true });
  }

  showScreen('quiz', { replaceState: true });
}

function setupStudyHeaderMenu() {
  const toggle = $('#btn-session-menu');
  const menu = $('#session-menu');
  if (!toggle || !menu) return;

  const controller = new AbortController();
  const { signal } = controller;
  studyMenuController = controller;

  const closeMenu = () => {
    menu.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  };

  const openMenu = () => {
    menu.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  };

  toggle.addEventListener('click', (event) => {
    event.stopPropagation();
    if (menu.hidden) {
      openMenu();
    } else {
      closeMenu();
    }
  }, { signal });

  menu.addEventListener('click', (event) => {
    event.stopPropagation();
  }, { signal });

  document.addEventListener('click', (event) => {
    if (!event.target.closest('.header-session-menu')) {
      closeMenu();
    }
  }, { signal });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeMenu();
    }
  }, { signal });

  $('#btn-save-quit')?.addEventListener('click', () => {
    closeMenu();
    persistCurrentSession();
    renderLevelSelect();
  }, { signal });

  $('#btn-restart-session')?.addEventListener('click', () => {
    closeMenu();
    restartCurrentSession();
  }, { signal });
}

function renderMultipleChoice(question) {
  const area = $('#answer-area');
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
    handleAnswer(question, btn.dataset.value);
  }, { once: true });
}

function renderFrontNav(answered) {
  const nav = $('#front-nav');
  if (!nav) return;

  nav.innerHTML = `
    <button class="btn btn-secondary" id="btn-prev-front" ${canGoPrevious(currentSession) ? '' : 'disabled'}>Previous</button>
    ${answered ? '<button class="btn btn-primary" id="btn-next-front">Next</button>' : ''}
  `;

  $('#btn-prev-front')?.addEventListener('click', () => {
    currentSession = goToPreviousQuestion(currentSession);
    persistCurrentSession();
    renderStudyCard();
  });
  $('#btn-next-front')?.addEventListener('click', advanceSession);
}

// ---------------------------------------------------------------------------
// Answer handling
// ---------------------------------------------------------------------------

function handleAnswer(question, userAnswer) {
  const correct = userAnswer === question.correctAnswer;
  updateProgress(currentWorkId, question.wordId, correct);

  currentSession = answerCurrentQuestion(currentSession, userAnswer, { correct });
  persistCurrentSession();
  showFeedback(question, userAnswer, correct);
}

function buildContextHTML(question) {
  const contexts = question.metadata.contexts;
  if (!contexts || contexts.length === 0) return '';

  let ctx = contexts[0];
  const promptForm = question.prompt.text;
  const match = contexts.find(candidate => candidate.form === promptForm);
  if (match) ctx = match;

  const sentence = ctx.sentence;
  const before = escapeHTML(sentence.slice(0, ctx.highlight_start));
  const highlighted = escapeHTML(sentence.slice(ctx.highlight_start, ctx.highlight_end));
  const after = escapeHTML(sentence.slice(ctx.highlight_end));

  return `
    <div class="word-context">
      <p class="context-greek greek-text">${before}<mark>${highlighted}</mark>${after}</p>
      ${ctx.translation ? `<p class="context-translation">${highlightTranslation(ctx)}</p>` : ''}
      <p class="context-ref">— ${escapeHTML(ctx.ref)}</p>
    </div>
  `;
}

function showFeedback(question, userAnswer, correct, { instant = false } = {}) {
  const feedback = $('#feedback-area');

  $$('.btn-choice').forEach(btn => {
    btn.disabled = true;
    if (btn.dataset.value === question.correctAnswer) {
      btn.classList.add('choice-correct');
    } else if (btn.dataset.value === userAnswer && !correct) {
      btn.classList.add('choice-incorrect');
    }
  });

  const message = correct
    ? `<div class="feedback-correct"><span>&#10003; Correct!</span></div>`
    : `
      <div class="feedback-incorrect">
        <span>&#10007; The answer is:</span>
        <p class="correct-answer">${escapeHTML(question.correctAnswer)}</p>
      </div>`;

  feedback.innerHTML = `
    ${message}
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
    ${buildContextHTML(question)}
    <div class="feedback-actions">
      <button class="btn btn-secondary" id="btn-prev-review" ${canGoPrevious(currentSession) ? '' : 'disabled'}>Previous</button>
      <button class="btn btn-primary" id="btn-next">Next</button>
    </div>
  `;

  const flipCard = $('#flip-card');
  if (flipCard) {
    const inner = flipCard.querySelector('.flip-card-inner');
    const front = flipCard.querySelector('.flip-card-front');
    const back = flipCard.querySelector('.flip-card-back');

    if (instant) {
      flipCard.classList.add('flipped');
      inner.style.height = back.offsetHeight + 'px';
    } else {
      inner.style.height = front.offsetHeight + 'px';
      flipCard.classList.add('flipped');
      inner.addEventListener('transitionend', function onFlipDone(e) {
        if (e.propertyName !== 'transform') return;
        inner.removeEventListener('transitionend', onFlipDone);
        inner.style.height = back.offsetHeight + 'px';
      });
    }
  }

  $('#btn-prev-review')?.addEventListener('click', () => {
    currentSession = goToPreviousQuestion(currentSession);
    persistCurrentSession();
    renderStudyCard();
  });
  $('#btn-next')?.addEventListener('click', advanceSession);
}

function advanceSession() {
  currentSession = goToNextQuestion(currentSession);
  ensureQuestionBuffer();
  persistCurrentSession();
  renderStudyCard();
}

function renderProgressDashboard() {
  cleanupStudyMenuListeners();
  const screen = $('#progress');
  const progress = getProgress(currentWorkId);
  const allWords = getAllWords(currentVocab);

  const totalMastered = allWords.filter(w => isMastered(progress.words[String(w.id)])).length;
  const totalSeen = allWords.filter(w => progress.words[String(w.id)]).length;

  let levelsHTML = '';
  for (let i = 1; i <= 3; i += 1) {
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
        <h2>Progress — ${escapeHTML(currentVocab.metadata.title)}</h2>
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
          <h3>Recent Study Sessions</h3>
          <ul class="quiz-history quiz-history--study">
            ${progress.quizHistory.slice(-10).reverse().map(renderHistoryRow).join('')}
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

function renderHistoryRow(entry) {
  if (entry.type === 'study-session') {
    return `
      <li>
        <span>${LEVEL_NAMES[entry.level] || `Level ${entry.level}`}</span>
        <span>${escapeHTML(formatModeLabel(entry.mode))}</span>
        <span>${entry.correct}/${entry.seen} (${entry.accuracy}%)</span>
        <span>${new Date(entry.date).toLocaleDateString()}</span>
      </li>
    `;
  }

  return `
    <li>
      <span>${LEVEL_NAMES[entry.level] || `Level ${entry.level}`}</span>
      ${entry.mode ? `<span>${escapeHTML(formatModeLabel(entry.mode))}</span>` : ''}
      <span>${entry.score}/${entry.total}</span>
      <span>${new Date(entry.date).toLocaleDateString()}</span>
    </li>
  `;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatQuestionType(type) {
  switch (type) {
    case 'greek-to-english': return 'Greek → English';
    case 'english-to-greek': return 'English → Greek';
    case 'form-id': return 'Identify the Form';
    default: return type || 'Question';
  }
}

function formatModeLabel(mode) {
  switch (mode) {
    case 'greek-to-english': return 'Greek → English';
    case 'english-to-greek': return 'English → Greek';
    case 'form-id': return 'Morphology';
    case 'mixed': return 'Mixed';
    default: return mode || 'Study';
  }
}

function highlightTranslation(ctx) {
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
  div.textContent = str ?? '';
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export { showScreen, selectWork, renderLevelSelect };
