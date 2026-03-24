// Core question generation engine

import { shuffleArray, pickDistractors } from './utils.js';

const RECENT_WORD_BLOCK = 3;

/**
 * Determine whether a word is eligible for form-id questions.
 * Requires at least one form with morphology info.
 */
function isFormIdEligible(word) {
  return word.forms && word.forms.length >= 1 && word.forms.some(f => f.morphology);
}

function pickRandom(arr) {
  if (!arr || arr.length === 0) return null;
  return arr[Math.floor(Math.random() * arr.length)];
}

function pickWordForm(word, {
  preferredForm = null,
  excludeForms = [],
  requireMorphology = false
} = {}) {
  const excluded = new Set(excludeForms.filter(Boolean));
  const forms = (word.forms || []).filter(f => !requireMorphology || f.morphology);
  if (forms.length === 0) return null;

  if (preferredForm) {
    const explicit = forms.find(f => f.form === preferredForm && !excluded.has(f.form));
    if (explicit) return explicit;
  }

  const nonLemma = forms.filter(f => f.form !== word.lemma && !excluded.has(f.form));
  if (nonLemma.length > 0) {
    return pickRandom(nonLemma);
  }

  const remaining = forms.filter(f => !excluded.has(f.form));
  if (remaining.length > 0) {
    return pickRandom(remaining);
  }

  return pickRandom(forms);
}

function baseMetadata(word) {
  return {
    lemma: word.lemma,
    definition: word.definition,
    context_definition: word.context_definition,
    etymology: word.etymology,
    forms: word.forms || [],
    contexts: word.contexts || []
  };
}

function buildGreekToEnglish(word, allWords, options = {}) {
  const correct = word.context_definition || word.definition;
  const distractors = pickDistractors(word, allWords, 3);
  const choices = shuffleArray([correct, ...distractors.map(d => d.context_definition || d.definition)]);

  const selectedForm = pickWordForm(word, {
    preferredForm: options.preferredForm,
    excludeForms: options.excludeForms
  });

  return {
    type: 'greek-to-english',
    prompt: { text: selectedForm?.form || word.lemma, subtext: 'What does this word mean?' },
    correctAnswer: correct,
    choices,
    wordId: word.id,
    metadata: baseMetadata(word)
  };
}

function buildEnglishToGreek(word, allWords) {
  const correct = word.lemma;
  const distractors = pickDistractors(word, allWords, 3);
  const choices = shuffleArray([correct, ...distractors.map(d => d.lemma)]);

  return {
    type: 'english-to-greek',
    prompt: { text: word.context_definition || word.definition, subtext: null },
    correctAnswer: correct,
    choices,
    wordId: word.id,
    metadata: baseMetadata(word)
  };
}

function buildFormId(word, allWords, options = {}) {
  const form = pickWordForm(word, {
    preferredForm: options.preferredForm,
    excludeForms: options.excludeForms,
    requireMorphology: true
  });
  const fallbackForm = form || pickWordForm(word, { preferredForm: options.preferredForm, excludeForms: options.excludeForms });
  const selectedForm = form || fallbackForm;
  const correct = selectedForm?.morphology || 'Unknown morphology';

  const otherForms = [];
  for (const other of allWords) {
    if (other.id === word.id || !other.forms) continue;
    for (const candidate of other.forms) {
      if (candidate.morphology && candidate.morphology !== correct) {
        otherForms.push(candidate.morphology);
      }
    }
  }

  const uniqueOtherForms = [...new Set(otherForms)];
  shuffleArray(uniqueOtherForms);
  const distractors = uniqueOtherForms.slice(0, 3);

  while (distractors.length < 3) {
    distractors.push(`morphology option ${distractors.length + 1}`);
  }

  const choices = shuffleArray([correct, ...distractors]);

  return {
    type: 'form-id',
    prompt: { text: selectedForm?.form || word.lemma, subtext: 'Identify this form' },
    correctAnswer: correct,
    choices,
    wordId: word.id,
    metadata: baseMetadata(word)
  };
}

function buildQuestion(word, allWords, mode, options = {}) {
  if (mode === 'english-to-greek') {
    return buildEnglishToGreek(word, allWords);
  }
  if (mode === 'form-id') {
    return buildFormId(word, allWords, options);
  }
  if (mode === 'mixed') {
    const mixedTypes = ['greek-to-english', 'english-to-greek'];
    if (isFormIdEligible(word)) {
      mixedTypes.push('form-id');
    }
    const chosenType = pickRandom(mixedTypes);
    return buildQuestion(word, allWords, chosenType, options);
  }
  return buildGreekToEnglish(word, allWords, options);
}

function recentWordSet(session) {
  return new Set((session?.recentWordIds || []).slice(-RECENT_WORD_BLOCK));
}

function wordWeight(word, session) {
  const stats = session?.wordStats?.[word.id];
  if (!stats) {
    return 1.5;
  }

  let weight = 1 + (stats.urgency || 0) * 0.8;
  if (stats.seen === 0) {
    weight += 0.4;
  }
  if (stats.correct > stats.incorrect) {
    weight *= 0.75;
  }
  if (stats.incorrect > stats.correct) {
    weight *= 1.2;
  }
  if (stats.streak >= 2) {
    weight *= 0.7;
  }

  return Math.max(0.2, weight);
}

function pickWeightedWord(words, session) {
  if (!words || words.length === 0) return null;

  const blockedRecent = recentWordSet(session);
  let pool = words.filter(word => !blockedRecent.has(word.id));
  if (pool.length === 0) {
    pool = words;
  }

  const totalWeight = pool.reduce((sum, word) => sum + wordWeight(word, session), 0);
  if (totalWeight <= 0) {
    return pickRandom(pool);
  }

  let threshold = Math.random() * totalWeight;
  for (const word of pool) {
    threshold -= wordWeight(word, session);
    if (threshold <= 0) {
      return word;
    }
  }

  return pool[pool.length - 1];
}

function questionOptionsFromHistory(word, session) {
  const wordStats = session?.wordStats?.[word.id];
  const excludeForms = wordStats?.lastPromptText ? [wordStats.lastPromptText] : [];
  return { excludeForms };
}

export function generateAdaptiveQuestion(levelWords, allWords, session, mode) {
  const eligibleWords = mode === 'form-id'
    ? levelWords.filter(isFormIdEligible)
    : levelWords;
  if (eligibleWords.length === 0) return null;

  const word = pickWeightedWord(eligibleWords, session);
  if (!word) return null;

  return buildQuestion(word, allWords, mode, questionOptionsFromHistory(word, session));
}

export function seedQuestionQueue(levelWords, allWords, mode, count = 5, session = null) {
  const questions = [];
  let workingSession = session || { wordStats: {}, recentWordIds: [] };

  for (let i = 0; i < count; i += 1) {
    const question = generateAdaptiveQuestion(levelWords, allWords, workingSession, mode);
    if (!question) break;
    questions.push(question);
    workingSession = {
      ...workingSession,
      recentWordIds: [...(workingSession.recentWordIds || []), question.wordId].slice(-RECENT_WORD_BLOCK),
      wordStats: {
        ...(workingSession.wordStats || {}),
        [question.wordId]: {
          ...(workingSession.wordStats?.[question.wordId] || {}),
          lastPromptText: question.prompt?.text || null,
        }
      }
    };
  }

  return questions;
}

export function countFormIdEligible(words) {
  return words.filter(isFormIdEligible).length;
}
