// Core question generation engine

import { shuffleArray, pickDistractors } from './utils.js';

/**
 * Determine whether a word is eligible for form-id questions.
 * Requires at least one form with morphology info.
 */
function isFormIdEligible(word) {
  return word.forms && word.forms.length >= 1 && word.forms.some(f => f.morphology);
}

/**
 * Pick a random form from a word. Prefers forms that differ from the lemma
 * (more interesting question), but falls back to any form.
 */
function pickRandomForm(word) {
  const nonLemma = word.forms.filter(f => f.form !== word.lemma && f.morphology);
  const pool = nonLemma.length > 0 ? nonLemma : word.forms.filter(f => f.morphology);
  return pool[Math.floor(Math.random() * pool.length)];
}

/**
 * Build a greek-to-english question object.
 */
function buildGreekToEnglish(word, allWords) {
  const correct = word.context_definition || word.definition;
  const distractors = pickDistractors(word, allWords, 3);
  const choices = shuffleArray([correct, ...distractors.map(d => d.context_definition || d.definition)]);

  // Show a random inflected form; fall back to lemma if forms is empty
  const forms = word.forms || [];
  const selectedForm = forms.length > 0
    ? forms[Math.floor(Math.random() * forms.length)].form
    : word.lemma;

  return {
    type: 'greek-to-english',
    prompt: { text: selectedForm, subtext: 'What does this word mean?' },
    correctAnswer: correct,
    choices,
    wordId: word.id,
    metadata: { lemma: word.lemma, definition: word.definition, context_definition: word.context_definition, etymology: word.etymology, forms: word.forms, contexts: word.contexts || [] }
  };
}

/**
 * Build an english-to-greek question object.
 */
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
    metadata: { lemma: word.lemma, definition: word.definition, context_definition: word.context_definition, etymology: word.etymology, forms: word.forms, contexts: word.contexts || [] }
  };
}

/**
 * Build a form-id question object (MC only — answer is the morphology string).
 */
function buildFormId(word, allWords) {
  const form = pickRandomForm(word);
  const correct = form.morphology;

  // Collect morphology strings from other words' forms as distractors.
  const otherForms = [];
  for (const other of allWords) {
    if (other.id === word.id || !other.forms) continue;
    for (const f of other.forms) {
      if (f.morphology !== form.morphology) {
        otherForms.push(f.morphology);
      }
    }
  }
  // De-duplicate, shuffle, and take 3.
  const uniqueOtherForms = [...new Set(otherForms)];
  shuffleArray(uniqueOtherForms);
  const distractors = uniqueOtherForms.slice(0, 3);

  // Pad with placeholder descriptions if the pool is sparse.
  while (distractors.length < 3) {
    distractors.push(`morphology option ${distractors.length + 1}`);
  }

  const choices = shuffleArray([correct, ...distractors]);

  return {
    type: 'form-id',
    prompt: { text: form.form, subtext: 'Identify this form' },
    correctAnswer: correct,
    choices,
    wordId: word.id,
    metadata: { lemma: word.lemma, definition: word.definition, context_definition: word.context_definition, etymology: word.etymology, forms: word.forms, contexts: word.contexts || [] }
  };
}

/**
 * Pick `n` random items from an array without repetition.
 * If n >= arr.length, returns a shuffled copy of the entire array.
 */
function pickRandom(arr, n) {
  const copy = [...arr];
  shuffleArray(copy);
  return copy.slice(0, n);
}

/**
 * Generate a question set from a word list for a single quiz mode.
 *
 * @param {Array}  words    - The words to draw questions from (already filtered by level).
 * @param {Array}  allWords - The full vocabulary pool (used for distractor picking).
 * @param {Object} config   - { count, mode }
 * @returns {Array} Array of question objects.
 */
export function generateQuestionSet(words, allWords, config = {}) {
  const {
    count = 10,
    mode = 'greek-to-english',
  } = config;

  let pool;
  let builder;

  if (mode === 'mixed') {
    // 40% greek-to-english, 30% english-to-greek, 30% form-id
    const formIdEligible = words.filter(isFormIdEligible);
    let nFormId = Math.round(count * 0.3);
    // Cap form-id by eligible count
    nFormId = Math.min(nFormId, formIdEligible.length);
    const shortfall = Math.round(count * 0.3) - nFormId;
    // Redistribute shortfall proportionally (4:3 ratio for the other two)
    const nGreekToEng = Math.round(count * 0.4) + Math.round(shortfall * 4 / 7);
    const nEngToGreek = count - nGreekToEng - nFormId;

    const questions = [
      ...pickRandom(words, nGreekToEng).map(w => buildGreekToEnglish(w, allWords)),
      ...pickRandom(words, nEngToGreek).map(w => buildEnglishToGreek(w, allWords)),
      ...pickRandom(formIdEligible, nFormId).map(w => buildFormId(w, allWords)),
    ];
    return shuffleArray(questions);
  } else if (mode === 'form-id') {
    pool = pickRandom(words.filter(isFormIdEligible), count);
    builder = buildFormId;
  } else if (mode === 'english-to-greek') {
    pool = pickRandom(words, count);
    builder = buildEnglishToGreek;
  } else {
    pool = pickRandom(words, count);
    builder = buildGreekToEnglish;
  }

  const questions = pool.map(word => builder(word, allWords));
  return shuffleArray(questions);
}

/**
 * Count how many words at a given level are eligible for form-id questions.
 */
export function countFormIdEligible(words) {
  return words.filter(isFormIdEligible).length;
}
