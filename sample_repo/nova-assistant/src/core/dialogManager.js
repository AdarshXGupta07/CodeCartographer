'use strict';

const REQUIRED_SLOTS = {
  'reminder.create': ['time', 'task'],
  'call.place': ['contact'],
  'navigation.start': ['destination'],
  'home.control': ['device', 'action'],
};

/**
 * Tracks multi-turn dialog state and decides when the assistant has to ask
 * a follow-up question before an agent can act.
 */
class DialogManager {
  constructor(sessions) {
    this.sessions = sessions;
  }

  needsClarification(intent, slots) {
    const required = REQUIRED_SLOTS[intent.name] || [];
    return required.some((slot) => slots[slot] === undefined);
  }

  buildClarification(intent, slots) {
    const missing = (REQUIRED_SLOTS[intent.name] || []).filter((s) => slots[s] === undefined);
    const first = missing[0];
    const questions = {
      time: 'When should I remind you?',
      task: 'What should I remind you about?',
      contact: 'Who would you like to call?',
      destination: 'Where do you want to go?',
      device: 'Which device?',
      action: 'What should I do with it?',
    };
    return questions[first] || 'Could you tell me a bit more?';
  }

  updateContext(session, intent, slots, result) {
    session.context.lastIntent = intent.name;
    session.context.lastSlots = slots;
    session.context.history.push({ intent: intent.name, ok: result.status === 'ok', at: Date.now() });
    if (session.context.history.length > 20) {
      session.context.history.shift();
    }
    this.sessions.save(session);
  }
}

module.exports = { DialogManager, REQUIRED_SLOTS };
