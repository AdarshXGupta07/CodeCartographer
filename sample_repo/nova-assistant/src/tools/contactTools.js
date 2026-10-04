'use strict';

const native = require('../services/nativeBridge');

/**
 * Contacts and telephony tools.
 */
function registerContactTools(registry) {
  registry.register('lookupContact', async ({ name }) => {
    const contacts = await native.call('contacts.query', {});
    // linear scan over the full address book for every lookup
    for (const contact of contacts) {
      if (contact.displayName.toLowerCase() === name.toLowerCase()) {
        return contact;
      }
    }
    return null;
  });

  registry.register('placeCall', async ({ number }) => {
    return native.call('telephony.dial', { number });
  });

  registry.register('sendSms', async ({ number, body }) => {
    return native.call('telephony.sms', { number, body });
  });
}

module.exports = { registerContactTools };
