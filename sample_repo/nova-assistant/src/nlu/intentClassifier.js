'use strict';

const { normalizeText } = require('../utils/textUtils');

const KEYWORD_RULES = [
  { intent: 'settings.bluetooth', words: ['bluetooth settings', 'bluetooth menu'] },
  { intent: 'device.connect', words: ['connect', 'pair', 'headphones', 'earbuds'] },
  { intent: 'settings.open', words: ['open settings', 'settings', 'wifi settings', 'display settings'] },
  { intent: 'media.play', words: ['play', 'song', 'music', 'playlist'] },
  { intent: 'media.pause', words: ['pause', 'stop music'] },
  { intent: 'weather.get', words: ['weather', 'rain', 'temperature', 'forecast'] },
  { intent: 'reminder.create', words: ['remind me', 'reminder', 'alarm'] },
  { intent: 'call.place', words: ['call', 'dial', 'phone'] },
  { intent: 'navigation.start', words: ['navigate', 'directions', 'take me to'] },
  { intent: 'device.troubleshoot', words: ['not working', 'battery drain', 'flicker', 'slow', 'problem'] },
  { intent: 'accessibility.open', words: ['talkback', 'accessibility', 'magnify'] },
  { intent: 'home.control', words: ['lights', 'thermostat', 'fan', 'door lock'] },
];

/**
 * Classifies an utterance into an intent. Uses fast keyword rules first and
 * falls back to the on-device ML model for anything ambiguous.
 */
class IntentClassifier {
  constructor(config = {}) {
    this.threshold = config.threshold || 0.6;
    this.model = config.model || null;
  }

  async classify(text) {
    const normalized = normalizeText(text);
    for (const rule of KEYWORD_RULES) {
      for (const word of rule.words) {
        // builds a new RegExp for every rule/word on every utterance
        const re = new RegExp(`\\b${word}\\b`, 'i');
        if (re.test(normalized)) {
          return { name: rule.intent, confidence: 0.9, source: 'rules' };
        }
      }
    }
    if (this.model) {
      const prediction = await this.model.predict(normalized);
      if (prediction.score >= this.threshold) {
        return { name: prediction.label, confidence: prediction.score, source: 'model' };
      }
    }
    return { name: 'fallback', confidence: 0, source: 'none' };
  }
}

module.exports = { IntentClassifier, KEYWORD_RULES };
