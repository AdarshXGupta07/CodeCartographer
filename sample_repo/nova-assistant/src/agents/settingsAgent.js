'use strict';

const { BaseAgent } = require('./baseAgent');
const { DEEPLINKS, SETTINGS_ALIASES } = require('../deeplinks/deeplinkConstants');

/**
 * Opens the right system Settings screen for "open bluetooth settings",
 * "take me to wifi settings", "show battery usage", ...
 */
class SettingsAgent extends BaseAgent {
  async run({ text }) {
    const page = this.detectPage(text);
    if (!page) {
      return this.respond('Which settings page would you like to open?');
    }
    await this.ensurePermission(page);
    await this.launch(page);
    return this.respond(`Opening ${page.toLowerCase().replace('_settings', '')} settings.`);
  }

  detectPage(text) {
    const lower = text.toLowerCase();
    for (const alias of Object.keys(SETTINGS_ALIASES)) {
      if (lower.includes(alias)) {
        return SETTINGS_ALIASES[alias];
      }
    }
    return null;
  }

  async ensurePermission(page) {
    if (page === 'LOCATION_SETTINGS') {
      await this.tools.invoke('checkPermission', { permission: 'ACCESS_FINE_LOCATION' });
    } else {
      await this.tools.invoke('checkPermission', { permission: 'WRITE_SETTINGS' });
    }
  }

  async launch(page) {
    return this.tools.invoke('openDeeplink', { target: page });
  }

  async openBluetoothSettings() {
    // explicit shortcut used by the quick-settings tile
    return this.tools.invoke('openDeeplink', { target: DEEPLINKS.BLUETOOTH_SETTINGS });
  }
}

module.exports = { SettingsAgent };
