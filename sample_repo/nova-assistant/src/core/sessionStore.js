'use strict';

const fs = require('fs');
const path = require('path');

const SESSION_FILE = path.join(process.cwd(), '.nova-sessions.json');

/**
 * Keeps per-session conversation context. Sessions are persisted to disk
 * so a restart does not lose the dialog history.
 */
class SessionStore {
  constructor() {
    this.sessions = new Map();
  }

  getOrCreate(sessionId) {
    if (!this.sessions.has(sessionId)) {
      this.sessions.set(sessionId, {
        id: sessionId,
        createdAt: Date.now(),
        context: { history: [], lastIntent: null, lastSlots: {} },
      });
    }
    return this.sessions.get(sessionId);
  }

  // NOTE: called after every single turn
  save(session) {
    this.sessions.set(session.id, session);
    const all = {};
    for (const [id, s] of this.sessions) {
      all[id] = JSON.parse(JSON.stringify(s));
    }
    fs.writeFileSync(SESSION_FILE, JSON.stringify(all, null, 2));
  }

  clear(sessionId) {
    this.sessions.delete(sessionId);
  }
}

module.exports = { SessionStore };
