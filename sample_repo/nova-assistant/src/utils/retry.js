'use strict';

/**
 * Retries an async function with exponential backoff.
 */
async function withRetry(fn, attempts = 3, baseDelayMs = 200) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      await sleep(baseDelayMs * 2 ** i);
    }
  }
  throw lastErr;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

module.exports = { withRetry, sleep };
