// Session state management — pure state transitions on plain objects

const RECENT_WORD_LIMIT = 4;

function instantiateQuestions(questions, startIndex = 0) {
  return (questions || []).map((question, offset) => ({
    ...question,
    id: question.id || `q${startIndex + offset + 1}`,
  }));
}

function initialWordState(wordId) {
  return {
    wordId,
    seen: 0,
    correct: 0,
    incorrect: 0,
    streak: 0,
    urgency: 0,
    lastPromptText: null,
    lastSeenAt: null,
  };
}

function getOrCreateWordState(session, wordId) {
  return session.wordStats[wordId] || initialWordState(wordId);
}

function trimRecentWordIds(wordIds) {
  return wordIds.slice(-RECENT_WORD_LIMIT);
}

/**
 * Create a new endless session.
 * @param {Object} config - { questions: [], workId, level, mode }
 */
export function createSession(config) {
  const questions = instantiateQuestions(config.questions || [], 0);
  const now = Date.now();

  return {
    version: 2,
    id: config.id || `${config.workId}-${now}`,
    workId: config.workId,
    level: config.level,
    mode: config.mode,
    questions,
    currentIndex: 0,
    nextQuestionOrdinal: questions.length,
    answersById: {},
    stats: {
      seen: 0,
      correct: 0,
      incorrect: 0,
      streak: 0,
      bestStreak: 0,
    },
    wordStats: {},
    recentWordIds: [],
    startTime: now,
    updatedAt: now,
    endedAt: null,
    ended: false,
  };
}

/**
 * Normalize a saved session to the current schema.
 */
export function restoreSession(savedSession) {
  if (!savedSession || !Array.isArray(savedSession.questions)) {
    return null;
  }

  const questions = instantiateQuestions(savedSession.questions, 0);
  const maxIndex = Math.max(questions.length - 1, 0);
  const currentIndex = Number.isInteger(savedSession.currentIndex)
    ? Math.max(0, Math.min(savedSession.currentIndex, maxIndex))
    : 0;

  return {
    version: 2,
    id: savedSession.id || `${savedSession.workId || 'session'}-${savedSession.startTime || Date.now()}`,
    workId: savedSession.workId,
    level: savedSession.level,
    mode: savedSession.mode,
    questions,
    currentIndex,
    nextQuestionOrdinal: Number.isInteger(savedSession.nextQuestionOrdinal)
      ? savedSession.nextQuestionOrdinal
      : questions.length,
    answersById: savedSession.answersById && typeof savedSession.answersById === 'object'
      ? savedSession.answersById
      : {},
    stats: {
      seen: savedSession.stats?.seen || 0,
      correct: savedSession.stats?.correct || 0,
      incorrect: savedSession.stats?.incorrect || 0,
      streak: savedSession.stats?.streak || 0,
      bestStreak: savedSession.stats?.bestStreak || 0,
    },
    wordStats: savedSession.wordStats && typeof savedSession.wordStats === 'object'
      ? savedSession.wordStats
      : {},
    recentWordIds: Array.isArray(savedSession.recentWordIds)
      ? trimRecentWordIds(savedSession.recentWordIds)
      : [],
    startTime: savedSession.startTime || Date.now(),
    updatedAt: savedSession.updatedAt || savedSession.startTime || Date.now(),
    endedAt: savedSession.endedAt || null,
    ended: Boolean(savedSession.ended),
  };
}

/**
 * Get the current question from the session.
 */
export function currentQuestion(session) {
  if (!session || session.ended || session.currentIndex >= session.questions.length) {
    return null;
  }
  return session.questions[session.currentIndex];
}

export function getAnswerRecord(session, questionId) {
  return session?.answersById?.[questionId] || null;
}

export function isQuestionAnswered(session, questionId) {
  return Boolean(getAnswerRecord(session, questionId));
}

export function canGoPrevious(session) {
  return Boolean(session) && session.currentIndex > 0;
}

export function canGoNext(session) {
  if (!session || session.ended) return false;
  const question = currentQuestion(session);
  if (!question) return false;
  return isQuestionAnswered(session, question.id);
}

/**
 * Record an answer for the current question without advancing.
 * Answers are locked once recorded.
 */
export function answerCurrentQuestion(session, userAnswer, evaluation) {
  const question = currentQuestion(session);
  if (!question || isQuestionAnswered(session, question.id)) {
    return session;
  }

  const now = Date.now();
  const correct = Boolean(evaluation.correct);
  const previousWordState = getOrCreateWordState(session, question.wordId);
  const nextWordState = {
    ...previousWordState,
    seen: previousWordState.seen + 1,
    correct: previousWordState.correct + (correct ? 1 : 0),
    incorrect: previousWordState.incorrect + (correct ? 0 : 1),
    streak: correct ? previousWordState.streak + 1 : 0,
    urgency: correct
      ? Math.max(0, previousWordState.urgency - 1)
      : Math.min(12, previousWordState.urgency + 3),
    lastPromptText: question.prompt?.text || null,
    lastSeenAt: now,
  };

  const answersById = {
    ...session.answersById,
    [question.id]: {
      questionId: question.id,
      questionIndex: session.currentIndex,
      wordId: question.wordId,
      userAnswer,
      correct,
      answeredAt: now,
    }
  };

  const stats = {
    seen: session.stats.seen + 1,
    correct: session.stats.correct + (correct ? 1 : 0),
    incorrect: session.stats.incorrect + (correct ? 0 : 1),
    streak: correct ? session.stats.streak + 1 : 0,
    bestStreak: correct
      ? Math.max(session.stats.bestStreak, session.stats.streak + 1)
      : session.stats.bestStreak,
  };

  return {
    ...session,
    answersById,
    stats,
    wordStats: {
      ...session.wordStats,
      [question.wordId]: nextWordState,
    },
    recentWordIds: trimRecentWordIds([...session.recentWordIds, question.wordId]),
    updatedAt: now,
  };
}

export function appendQuestions(session, questions) {
  if (!questions || questions.length === 0) return session;
  const instantiated = instantiateQuestions(questions, session.nextQuestionOrdinal);

  return {
    ...session,
    questions: [...session.questions, ...instantiated],
    nextQuestionOrdinal: session.nextQuestionOrdinal + instantiated.length,
    updatedAt: Date.now(),
  };
}

export function goToPreviousQuestion(session) {
  if (!canGoPrevious(session)) return session;
  return {
    ...session,
    currentIndex: session.currentIndex - 1,
    updatedAt: Date.now(),
  };
}

export function goToNextQuestion(session) {
  if (!canGoNext(session)) return session;
  const nextIndex = Math.min(session.currentIndex + 1, session.questions.length - 1);
  return {
    ...session,
    currentIndex: nextIndex,
    updatedAt: Date.now(),
  };
}

export function endSession(session) {
  return {
    ...session,
    ended: true,
    endedAt: Date.now(),
    updatedAt: Date.now(),
  };
}

export function getSessionProgress(session) {
  const accuracy = session.stats.seen > 0
    ? Math.round((session.stats.correct / session.stats.seen) * 100)
    : 0;

  return {
    seen: session.stats.seen,
    correct: session.stats.correct,
    incorrect: session.stats.incorrect,
    accuracy,
    streak: session.stats.streak,
    bestStreak: session.stats.bestStreak,
    currentNumber: session.currentIndex + 1,
    loadedCount: session.questions.length,
  };
}

export function getStudySummary(session) {
  const duration = (session.endedAt || Date.now()) - session.startTime;
  const accuracy = session.stats.seen > 0
    ? Math.round((session.stats.correct / session.stats.seen) * 100)
    : 0;

  return {
    seen: session.stats.seen,
    correct: session.stats.correct,
    incorrect: session.stats.incorrect,
    accuracy,
    streak: session.stats.streak,
    bestStreak: session.stats.bestStreak,
    duration,
    details: session.questions.map((question) => ({
      question,
      answer: getAnswerRecord(session, question.id),
    })),
  };
}
