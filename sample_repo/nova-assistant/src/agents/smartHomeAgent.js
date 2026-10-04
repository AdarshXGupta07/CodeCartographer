'use strict';

const { BaseAgent } = require('./baseAgent');
const { httpGet } = require('../utils/http');

/**
 * "Turn off the living room lights", "set thermostat to 22".
 */
class SmartHomeAgent extends BaseAgent {
  async run({ slots }) {
    const devices = await this.discoverDevices();
    const device = devices.find((d) => d.name.includes(slots.device));
    if (!device) {
      return this.respond(`I couldn't find ${slots.device}.`);
    }
    await this.tools.invoke('httpFetch', { url: `${this.settings.hubUrl}/devices/${device.id}/${slots.action}` });
    return this.respond(`Done. ${device.name} is now ${slots.action}.`);
  }

  async discoverDevices() {
    const rooms = await httpGet(`${this.settings.hubUrl}/rooms`);
    const devices = [];
    // N+1: one request per room, awaited one after another
    for (const room of rooms) {
      const list = await httpGet(`${this.settings.hubUrl}/rooms/${room.id}/devices`);
      devices.push(...list);
    }
    return devices;
  }
}

module.exports = { SmartHomeAgent };
