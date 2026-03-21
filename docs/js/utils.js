// Utility functions for the Greek flashcard app

/**
 * Normalize Greek text for comparison: strip diacritics (accents, breathings),
 * lowercase, trim whitespace.
 * Uses Unicode NFD decomposition then removes combining marks (U+0300-U+036F).
 */
export function normalizeGreek(str) {
  return str
    .normalize('NFD')
    .replace(/[\u0300-\u036F]/g, '')
    .toLowerCase()
    .trim();
}

/**
 * Fisher-Yates shuffle (in-place, returns the array).
 */
export function shuffleArray(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

/**
 * Pick n distractor items from pool, excluding the correct answer.
 * Prefers items with the same POS as the correct answer.
 * Falls back to adjacent levels if not enough same-POS items.
 * Returns array of distractor objects (word objects from the vocab).
 */
export function pickDistractors(correct, pool, n = 3) {
  // Exclude the correct answer
  const candidates = pool.filter(w => w.id !== correct.id);

  // Prefer same POS
  const samePOS = candidates.filter(w => w.pos === correct.pos);
  const diffPOS = candidates.filter(w => w.pos !== correct.pos);

  // Shuffle within priority groups to add variety
  shuffleArray(samePOS);
  shuffleArray(diffPOS);

  const shuffledSource = [...samePOS, ...diffPOS];

  // Take from same POS first, then fill with different POS
  const selected = [];

  for (const item of shuffledSource) {
    if (selected.length >= n) break;
    // Avoid substring overlap >50% with correct definition
    if (!hasExcessiveOverlap(item.definition, correct.definition)) {
      selected.push(item);
    }
  }

  // If still not enough, add remaining without overlap check
  if (selected.length < n) {
    for (const item of shuffledSource) {
      if (selected.length >= n) break;
      if (!selected.includes(item)) {
        selected.push(item);
      }
    }
  }

  return selected.slice(0, n);
}

/**
 * Check if two definition strings have >50% word overlap.
 */
function hasExcessiveOverlap(def1, def2) {
  if (!def1 || !def2) return false;
  const words1 = new Set(def1.toLowerCase().split(/[\s,;]+/).filter(Boolean));
  const words2 = new Set(def2.toLowerCase().split(/[\s,;]+/).filter(Boolean));
  if (words1.size === 0 || words2.size === 0) return false;
  let overlap = 0;
  for (const w of words1) {
    if (words2.has(w)) overlap++;
  }
  return overlap / Math.min(words1.size, words2.size) > 0.5;
}
