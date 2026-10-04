'use strict';

const { DEEPLINKS, SETTINGS_ALIASES } = require('./deeplinkConstants');

/**
 * Turns a logical target ("bluetooth", "BATTERY_SETTINGS" or a raw URI)
 * into a launchable deeplink URI with optional extras.
 */
function resolveDeeplink(target, extras = {}) {
  let uri = DEEPLINKS[target];
  if (!uri && SETTINGS_ALIASES[target]) {
    uri = DEEPLINKS[SETTINGS_ALIASES[target]];
  }
  if (!uri) {
    uri = target;
  }
  const params = Object.keys(extras)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(extras[k])}`)
    .join('&');
  return params ? `${uri}?${params}` : uri;
}

function isSettingsDeeplink(uri) {
  return uri.startsWith('android.settings.') || uri.startsWith('android.intent.action.');
}

module.exports = { resolveDeeplink, isSettingsDeeplink };
