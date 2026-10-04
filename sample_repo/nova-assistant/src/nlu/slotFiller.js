'use strict';

/**
 * Merges freshly extracted entities with what the session already knows,
 * so "call him" can reuse the contact from the previous turn.
 */
function fillSlots(intent, entities, context) {
  const slots = { ...entities };
  const previous = context && context.lastSlots ? context.lastSlots : {};
  if (intent.name === 'call.place' && !slots.contact && previous.contact) {
    slots.contact = previous.contact;
  }
  if (intent.name === 'reminder.create') {
    slots.task = slots.task || inferTask(entities);
  }
  if (intent.name === 'device.connect' && !slots.device) {
    slots.device = previous.device || 'last-paired';
  }
  return slots;
}

function inferTask(entities) {
  return entities.raw ? entities.raw.replace(/remind me to/i, '').trim() : undefined;
}

module.exports = { fillSlots };
