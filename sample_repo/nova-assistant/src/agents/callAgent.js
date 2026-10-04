'use strict';

const { BaseAgent } = require('./baseAgent');
const { DEEPLINKS } = require('../deeplinks/deeplinkConstants');

/**
 * "Call mom", "dial 911".
 */
class CallAgent extends BaseAgent {
  async run({ slots }) {
    await this.tools.invoke('checkPermission', { permission: 'CALL_PHONE' });
    const contact = await this.tools.invoke('lookupContact', { name: slots.contact });
    if (!contact) {
      return this.respond(`I couldn't find ${slots.contact} in your contacts.`);
    }
    if (this.settings.confirmCalls) {
      // hand the number to the dialer instead of calling directly
      await this.tools.invoke('openDeeplink', { target: `${DEEPLINKS.DIALER}${contact.phone}` });
    } else {
      await this.tools.invoke('placeCall', { number: contact.phone });
    }
    return this.respond(`Calling ${contact.displayName}.`);
  }
}

module.exports = { CallAgent };
