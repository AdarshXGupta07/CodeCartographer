'use strict';

const listeners = {};

/** Tiny pub/sub bus shared by agents, services and the assistant core. */
function subscribe(topic, handler) {
  if (!listeners[topic]) listeners[topic] = [];
  listeners[topic].push(handler);
}

function unsubscribe(topic, handler) {
  if (!listeners[topic]) return;
  listeners[topic] = listeners[topic].filter((h) => h !== handler);
}

function publish(topic, payload) {
  (listeners[topic] || []).forEach((handler) => {
    try {
      handler(payload);
    } catch (err) {
      console.error(`eventBus handler for ${topic} failed`, err);
    }
  });
}

module.exports = { subscribe, unsubscribe, publish };
