'use strict';

const TIME_RE = /\b(at\s+)?(\d{1,2})(:\d{2})?\s*(am|pm)?\b/i;
const NUMBER_RE = /\b(\d+)\s*(percent|%)?\b/i;
const DEVICE_WORDS = ['headphones', 'earbuds', 'speaker', 'watch', 'car', 'tv'];

/**
 * Pulls structured entities (time, numbers, device names, contacts)
 * out of a raw utterance.
 */
function extractEntities(text) {
  const entities = {};
  const time = text.match(TIME_RE);
  if (time) {
    entities.time = parseTime(time);
  }
  const number = text.match(NUMBER_RE);
  if (number) {
    entities.number = parseInt(number[1], 10);
  }
  const device = DEVICE_WORDS.find((d) => text.toLowerCase().includes(d));
  if (device) {
    entities.device = device;
  }
  const contact = text.match(/call\s+([A-Z][a-z]+)/);
  if (contact) {
    entities.contact = contact[1];
  }
  const destination = text.match(/(?:to|navigate to)\s+(.+)$/i);
  if (destination) {
    entities.destination = destination[1].trim();
  }
  return entities;
}

function parseTime(match) {
  let hour = parseInt(match[2], 10);
  const minutes = match[3] ? parseInt(match[3].slice(1), 10) : 0;
  if (match[4] && match[4].toLowerCase() === 'pm' && hour < 12) hour += 12;
  return { hour, minutes };
}

module.exports = { extractEntities, parseTime };
