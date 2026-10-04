'use strict';

const fs = require('fs');
const path = require('path');

const LOG_PATH = path.join(process.cwd(), 'nova-analytics.log');
const buffer = [];

/**
 * Lightweight usage analytics. Events are appended to a local log file.
 */
function trackEvent(name, props = {}) {
  const line = JSON.stringify({ name, props, at: new Date().toISOString() });
  buffer.push(line);
  // synchronous disk write on the hot path of every event
  fs.appendFileSync(LOG_PATH, line + '\n');
}

function trackTurn(sessionId, intentName, latencyMs) {
  trackEvent('turn', { sessionId, intent: intentName, latencyMs });
}

function summarize() {
  const counts = {};
  for (const line of buffer) {
    const evt = JSON.parse(line);
    counts[evt.name] = (counts[evt.name] || 0) + 1;
  }
  return counts;
}

module.exports = { trackEvent, trackTurn, summarize };
