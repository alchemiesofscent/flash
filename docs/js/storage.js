// localStorage wrapper for progress and settings persistence

const PROGRESS_PREFIX = 'flash_progress_';
const SETTINGS_KEY = 'flash_settings';

const DEFAULT_SETTINGS = {
  lastWorkId: null
};

/**
 * Get progress data for a specific work.
 * Returns: { words: { [wordId]: { correct, incorrect, lastSeen, streak } }, quizHistory: [] }
 */
export function getProgress(workId) {
  try {
    const raw = localStorage.getItem(PROGRESS_PREFIX + workId);
    if (raw) {
      const data = JSON.parse(raw);
      // Validate structure
      if (data && typeof data.words === 'object' && Array.isArray(data.quizHistory)) {
        return data;
      }
    }
  } catch (e) {
    console.warn('Failed to read progress:', e);
  }
  return { words: {}, quizHistory: [] };
}

/**
 * Update progress for a single word after answering.
 */
export function updateProgress(workId, wordId, correct) {
  const progress = getProgress(workId);
  const key = String(wordId);

  if (!progress.words[key]) {
    progress.words[key] = { correct: 0, incorrect: 0, lastSeen: null, streak: 0 };
  }

  const word = progress.words[key];
  if (correct) {
    word.correct++;
    word.streak++;
  } else {
    word.incorrect++;
    word.streak = 0;
  }
  word.lastSeen = new Date().toISOString();

  _saveProgress(workId, progress);
}

/**
 * Record a completed quiz in history.
 */
export function recordQuiz(workId, level, score, total, mode) {
  const progress = getProgress(workId);
  progress.quizHistory.push({
    date: new Date().toISOString(),
    level,
    score,
    total,
    mode: mode || null
  });
  _saveProgress(workId, progress);
}

/**
 * Check if a word is "mastered": correct >= 3 AND accuracy >= 75%
 */
export function isMastered(wordProgress) {
  if (!wordProgress) return false;
  const total = wordProgress.correct + wordProgress.incorrect;
  return wordProgress.correct >= 3 && (total === 0 || wordProgress.correct / total >= 0.75);
}

/**
 * Get mastery stats for a level.
 * Returns: { total, mastered, percentage }
 */
export function getLevelStats(workId, words, level) {
  const progress = getProgress(workId);
  const levelWords = words.filter(w => w.level === level);
  const mastered = levelWords.filter(w => isMastered(progress.words[String(w.id)])).length;
  return {
    total: levelWords.length,
    mastered,
    percentage: levelWords.length > 0 ? Math.round((mastered / levelWords.length) * 100) : 0
  };
}

/**
 * Get user settings.
 */
export function getSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
    }
  } catch (e) {
    console.warn('Failed to read settings:', e);
  }
  return { ...DEFAULT_SETTINGS };
}

/**
 * Save user settings.
 */
export function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (e) {
    console.warn('Failed to save settings:', e);
  }
}

/**
 * Reset all progress for a work.
 */
export function resetProgress(workId) {
  try {
    localStorage.removeItem(PROGRESS_PREFIX + workId);
  } catch (e) {
    console.warn('Failed to reset progress:', e);
  }
}

/**
 * Reset all app data.
 */
export function resetAll() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.startsWith(PROGRESS_PREFIX) || key === SETTINGS_KEY)) {
        keys.push(key);
      }
    }
    keys.forEach(k => localStorage.removeItem(k));
  } catch (e) {
    console.warn('Failed to reset all data:', e);
  }
}

function _saveProgress(workId, progress) {
  try {
    localStorage.setItem(PROGRESS_PREFIX + workId, JSON.stringify(progress));
  } catch (e) {
    console.warn('Failed to save progress:', e);
  }
}
