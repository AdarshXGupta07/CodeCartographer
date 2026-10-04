'use strict';

/**
 * Lower-cases, strips punctuation and collapses whitespace.
 */
function normalizeText(text) {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function tokenize(text) {
  return normalizeText(text).split(' ').filter(Boolean);
}

module.exports = { normalizeText, tokenize };
