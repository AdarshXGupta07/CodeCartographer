'use strict';

const { SettingsAgent } = require('../agents/settingsAgent');
const { BluetoothAgent } = require('../agents/bluetoothAgent');
const { MediaAgent } = require('../agents/mediaAgent');
const { WeatherAgent } = require('../agents/weatherAgent');
const { ReminderAgent } = require('../agents/reminderAgent');
const { CallAgent } = require('../agents/callAgent');
const { NavigationAgent } = require('../agents/navigationAgent');
const { TroubleshootAgent } = require('../agents/troubleshootAgent');
const { AccessibilityAgent } = require('../agents/accessibilityAgent');
const { SmartHomeAgent } = require('../agents/smartHomeAgent');
const { FallbackAgent } = require('../agents/fallbackAgent');

const INTENT_TO_AGENT = {
  'settings.open': 'settings',
  'settings.bluetooth': 'bluetooth',
  'device.connect': 'bluetooth',
  'media.play': 'media',
  'media.pause': 'media',
  'weather.get': 'weather',
  'reminder.create': 'reminder',
  'reminder.list': 'reminder',
  'call.place': 'call',
  'navigation.start': 'navigation',
  'device.troubleshoot': 'troubleshoot',
  'accessibility.open': 'accessibility',
  'home.control': 'smarthome',
};

/**
 * Maps a classified intent onto the agent responsible for it.
 * Agents are created lazily and cached for the life of the process.
 */
class AgentRouter {
  constructor(registry, settings) {
    this.registry = registry;
    this.settings = settings;
    this.cache = new Map();
  }

  route(intent) {
    const key = INTENT_TO_AGENT[intent.name] || 'fallback';
    if (!this.cache.has(key)) {
      this.cache.set(key, this.createAgent(key));
    }
    return this.cache.get(key);
  }

  createAgent(key) {
    const deps = { tools: this.registry, settings: this.settings };
    switch (key) {
      case 'settings': return new SettingsAgent(deps);
      case 'bluetooth': return new BluetoothAgent(deps);
      case 'media': return new MediaAgent(deps);
      case 'weather': return new WeatherAgent(deps);
      case 'reminder': return new ReminderAgent(deps);
      case 'call': return new CallAgent(deps);
      case 'navigation': return new NavigationAgent(deps);
      case 'troubleshoot': return new TroubleshootAgent(deps);
      case 'accessibility': return new AccessibilityAgent(deps);
      case 'smarthome': return new SmartHomeAgent(deps);
      default: return new FallbackAgent(deps);
    }
  }
}

module.exports = { AgentRouter, INTENT_TO_AGENT };
