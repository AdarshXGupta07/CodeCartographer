'use strict';

const { BaseAgent } = require('./baseAgent');
const { DEEPLINKS } = require('../deeplinks/deeplinkConstants');

/**
 * "Navigate to the airport", "take me home".
 * NOTE: never checks location permission before launching maps.
 */
class NavigationAgent extends BaseAgent {
  async run({ slots }) {
    const origin = await this.tools.invoke('getUserLocation');
    const destination = encodeURIComponent(slots.destination);
    await this.tools.invoke('openDeeplink', {
      target: `${DEEPLINKS.MAPS_NAVIGATION}${destination}`,
      extras: { origin: `${origin.lat},${origin.lon}` },
    });
    return this.respond(`Starting navigation to ${slots.destination}.`);
  }
}

module.exports = { NavigationAgent };
