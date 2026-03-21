// Session state management — pure state transitions on plain objects

/**
 * Create a new session.
 * @param {Object} config - { questions: [], workId: string, level: number }
 * @returns {Object} session state object
 */
export function createSession(config) {
  return {
    workId: config.workId,
    level: config.level,
    mode: config.mode,
    questions: config.questions,
    currentIndex: 0,
    answers: [],       // { questionIndex, userAnswer, correct }
    startTime: Date.now(),
    endTime: null,
    completed: false
  };
}

/**
 * Get the current question from the session.
 * Returns null if session is completed.
 */
export function currentQuestion(session) {
  if (session.completed || session.currentIndex >= session.questions.length) {
    return null;
  }
  return session.questions[session.currentIndex];
}

/**
 * Record an answer for the current question and advance.
 * Returns updated session (new object).
 */
export function answerQuestion(session, userAnswer, evaluation) {
  const newAnswers = [...session.answers, {
    questionIndex: session.currentIndex,
    userAnswer,
    correct: evaluation.correct
  }];

  const nextIndex = session.currentIndex + 1;
  const completed = nextIndex >= session.questions.length;

  return {
    ...session,
    answers: newAnswers,
    currentIndex: nextIndex,
    completed,
    endTime: completed ? Date.now() : null
  };
}

/**
 * Get results summary from a completed session.
 */
export function getResults(session) {
  const total = session.questions.length;
  const correct = session.answers.filter(a => a.correct).length;

  return {
    total,
    answered: total,
    correct,
    incorrect: total - correct,
    score: total > 0 ? Math.round((correct / total) * 100) : 0,
    duration: session.endTime ? session.endTime - session.startTime : null,
    details: session.questions.map((q, i) => ({
      question: q,
      answer: session.answers[i] || null
    }))
  };
}
