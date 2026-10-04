'use strict';

/**
 * Every Android / One UI settings screen the assistant can jump to.
 * Agents must reference these constants instead of raw intent strings.
 */
const DEEPLINKS = Object.freeze({
  BLUETOOTH_SETTINGS: 'android.settings.BLUETOOTH_SETTINGS',
  WIFI_SETTINGS: 'android.settings.WIFI_SETTINGS',
  DISPLAY_SETTINGS: 'android.settings.DISPLAY_SETTINGS',
  BATTERY_SETTINGS: 'android.intent.action.POWER_USAGE_SUMMARY',
  SOUND_SETTINGS: 'android.settings.SOUND_SETTINGS',
  ACCESSIBILITY_SETTINGS: 'android.settings.ACCESSIBILITY_SETTINGS',
  LOCATION_SETTINGS: 'android.settings.LOCATION_SOURCE_SETTINGS',
  APP_NOTIFICATION_SETTINGS: 'android.settings.APP_NOTIFICATION_SETTINGS',
  MAPS_NAVIGATION: 'google.navigation:q=',
  DIALER: 'tel:',
});

const SETTINGS_ALIASES = {
  bluetooth: 'BLUETOOTH_SETTINGS',
  wifi: 'WIFI_SETTINGS',
  'wi-fi': 'WIFI_SETTINGS',
  display: 'DISPLAY_SETTINGS',
  brightness: 'DISPLAY_SETTINGS',
  battery: 'BATTERY_SETTINGS',
  sound: 'SOUND_SETTINGS',
  volume: 'SOUND_SETTINGS',
  accessibility: 'ACCESSIBILITY_SETTINGS',
  location: 'LOCATION_SETTINGS',
  notifications: 'APP_NOTIFICATION_SETTINGS',
};

module.exports = { DEEPLINKS, SETTINGS_ALIASES };
