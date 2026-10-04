'use strict';

const path = require('path');

/**
 * Runtime configuration, overridable via environment variables.
 */
function loadSettings() {
  return {
    version: '0.4.2',
    skillsDir: process.env.NOVA_SKILLS_DIR || path.join(__dirname, '..', 'skills', 'manifests'),
    weatherApi: process.env.NOVA_WEATHER_API || 'https://weather.nova.local',
    hubUrl: process.env.NOVA_HUB_URL || 'http://home-hub.local:8123',
    defaultVolume: 40,
    confirmCalls: process.env.NOVA_CONFIRM_CALLS === '1',
    nlu: { threshold: 0.6 },
    asr: { language: 'en-IN', partials: true },
    tts: { voice: 'nova-female-1', rate: 1.0 },
  };
}

module.exports = { loadSettings };
