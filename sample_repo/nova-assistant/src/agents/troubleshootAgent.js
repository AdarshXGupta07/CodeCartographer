'use strict';

const { BaseAgent } = require('./baseAgent');
const { DEEPLINKS } = require('../deeplinks/deeplinkConstants');

const PROBLEM_TO_SETTINGS = [
  { match: /battery|drain|charging/i, page: DEEPLINKS.BATTERY_SETTINGS, tip: 'Check which apps use the most battery.' },
  { match: /bluetooth|earbuds|headphones/i, page: DEEPLINKS.BLUETOOTH_SETTINGS, tip: 'Try forgetting and re-pairing the device.' },
  { match: /wifi|internet|network/i, page: DEEPLINKS.WIFI_SETTINGS, tip: 'Toggle Wi-Fi off and on again.' },
  { match: /flicker|brightness|screen/i, page: DEEPLINKS.DISPLAY_SETTINGS, tip: 'Turn off adaptive brightness.' },
];

/**
 * Turns a vague complaint ("my earbuds keep disconnecting") into a tip and
 * a one-tap jump to the relevant Settings screen.
 */
class TroubleshootAgent extends BaseAgent {
  async run({ text }) {
    const battery = await this.tools.invoke('getBatteryStatus');
    const rule = PROBLEM_TO_SETTINGS.find((r) => r.match.test(text));
    if (!rule) {
      return this.respond('Can you describe the problem in a bit more detail?');
    }
    await this.tools.invoke('checkPermission', { permission: 'WRITE_SETTINGS' });
    await this.tools.invoke('openDeeplink', { target: rule.page });
    const lowBattery = battery.level < 15 ? ' Your battery is also low.' : '';
    return this.respond(`${rule.tip}${lowBattery}`);
  }
}

module.exports = { TroubleshootAgent, PROBLEM_TO_SETTINGS };
