// Data fetching and caching module

let worksCache = null;
let vocabCache = {};

/**
 * Fetch the works index (docs/data/works.json).
 * Caches result in memory.
 */
export async function fetchWorks() {
  if (worksCache) return worksCache;
  const res = await fetch('data/works.json');
  if (!res.ok) throw new Error(`Failed to fetch works: ${res.status}`);
  worksCache = await res.json();
  return worksCache;
}

/**
 * Fetch vocabulary data for a specific work.
 * Caches result in memory.
 */
export async function fetchVocab(workId) {
  if (vocabCache[workId]) return vocabCache[workId];
  const res = await fetch(`data/${workId}.json`);
  if (!res.ok) throw new Error(`Failed to fetch vocab for ${workId}: ${res.status}`);
  vocabCache[workId] = await res.json();
  return vocabCache[workId];
}

/**
 * Get words for a specific level from vocab data.
 */
export function getWordsForLevel(vocab, level) {
  return vocab.words.filter(w => w.level === level);
}

/**
 * Get all words from vocab data.
 */
export function getAllWords(vocab) {
  return vocab.words;
}
