'use strict';

const { BaseAgent } = require('./baseAgent');
const { DEEPLINKS } = require('../deeplinks/deeplinkConstants');

/**
 * Handles "connect my earbuds", "pair the speaker", "turn on bluetooth".
 */
class BluetoothAgent extends BaseAgent {
  async run({ slots }) {
    await this.tools.invoke('checkPermission', { permission: 'BLUETOOTH_CONNECT' });
    await this.tools.invoke('toggleBluetooth', { enabled: true });

    const devices = await this.tools.invoke('scanBluetoothDevices', { timeoutMs: 6000 });
    const target = this.pickDevice(devices, slots.device);
    if (!target) {
      // nothing found nearby: send the user to the bluetooth settings page
      await this.tools.invoke('openDeeplink', { target: DEEPLINKS.BLUETOOTH_SETTINGS });
      return this.respond("I couldn't find it. I've opened Bluetooth settings for you.");
    }
    await this.tools.invoke('pairBluetoothDevice', { address: target.address });
    return this.respond(`Connected to ${target.name}.`);
  }

  pickDevice(devices, wanted) {
    if (!devices || devices.length === 0) return null;
    if (!wanted || wanted === 'last-paired') {
      return devices.sort((a, b) => b.lastSeen - a.lastSeen)[0];
    }
    return devices.find((d) => d.name.toLowerCase().includes(wanted.toLowerCase())) || null;
  }
}

module.exports = { BluetoothAgent };
