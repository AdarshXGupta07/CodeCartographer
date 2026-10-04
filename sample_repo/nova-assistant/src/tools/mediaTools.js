'use strict';

const native = require('../services/nativeBridge');
const { httpGet } = require('../utils/http');

/**
 * Music / media tools backed by the system media session.
 */
function registerMediaTools(registry) {
  registry.register('searchMedia', async ({ query, type = 'track' }) => {
    const results = await httpGet(`https://media.nova.local/search?q=${encodeURIComponent(query)}&type=${type}`);
    return results.items || [];
  });

  registry.register('playMusic', async ({ trackId }) => {
    return native.call('media.play', { trackId });
  });

  registry.register('pauseMusic', async () => {
    return native.call('media.pause', {});
  });

  registry.register('nextTrack', async () => {
    return native.call('media.next', {});
  });
}

module.exports = { registerMediaTools };
