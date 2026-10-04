'use strict';

const native = require('../services/nativeBridge');
const { isSettingsDeeplink } = require('./deeplinkResolver');
const analytics = require('../services/analytics');
const logger = require('../utils/logger');

/**
 * Fires an Android intent for the given deeplink URI through the native bridge.
 */
async function launchDeeplink(uri) {
  logger.debug(`launching deeplink ${uri}`);
  analytics.trackEvent('deeplink_launch', { uri, settings: isSettingsDeeplink(uri) });
  const ok = await native.call('intent.start', { uri, flags: ['NEW_TASK'] });
  if (!ok) {
    logger.warn(`deeplink ${uri} could not be resolved on this device`);
  }
  return ok;
}

module.exports = { launchDeeplink };
