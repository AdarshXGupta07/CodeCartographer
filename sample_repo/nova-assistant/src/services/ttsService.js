'use strict';

const native = require('./nativeBridge');

/**
 * Text to speech output.
 */
class TtsService {
  constructor(config = {}) {
    this.voice = config.voice || 'nova-female-1';
    this.rate = config.rate || 1.0;
  }

  async speak(text) {
    if (!text) return;
    return native.call('tts.speak', { text, voice: this.voice, rate: this.rate });
  }
}

module.exports = { TtsService };
