'use strict';

const { BaseAgent } = require('./baseAgent');
const { DEEPLINKS } = require('../deeplinks/deeplinkConstants');

/**
 * "Turn on TalkBack", "open accessibility".
 */
class AccessibilityAgent extends BaseAgent {
  async run() {
    // BUG: launches the settings page first and only then checks permission
    await this.tools.invoke('openDeeplink', { target: DEEPLINKS.ACCESSIBILITY_SETTINGS });
    await this.tools.invoke('checkPermission', { permission: 'WRITE_SECURE_SETTINGS' });
    return this.respond('Opening accessibility settings.');
  }
}

module.exports = { AccessibilityAgent };
