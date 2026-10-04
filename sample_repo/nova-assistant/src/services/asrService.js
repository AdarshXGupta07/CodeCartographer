'use strict';

const { EventEmitter } = require('events');
const native = require('./nativeBridge');

/**
 * Wraps the on-device speech recogniser and emits `transcript` events.
 */
class AsrService extends EventEmitter {
  constructor(config = {}) {
    super();
    this.language = config.language || 'en-IN';
    this.partials = config.partials !== false;
  }

  async startListening() {
    await native.call('asr.start', { language: this.language, partials: this.partials });
    this.pollTimer = setInterval(() => this.poll(), 250);
  }

  async poll() {
    const evt = await native.call('asr.poll', {});
    if (evt && evt.final) {
      this.emit('transcript', { sessionId: evt.sessionId, text: evt.text });
    }
  }

  stopListening() {
    clearInterval(this.pollTimer);
    return native.call('asr.stop', {});
  }
}

module.exports = { AsrService };
