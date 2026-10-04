'use strict';

const { launchDeeplink } = require('../deeplinks/deeplinkLauncher');
const { resolveDeeplink } = require('../deeplinks/deeplinkResolver');
const permissions = require('../services/permissionService');
const location = require('../services/locationService');
const native = require('../services/nativeBridge');

/**
 * Device level tools: radios, volume, brightness, permissions and deeplinks.
 */
function registerDeviceTools(registry) {
  registry.register('checkPermission', async ({ permission }) => {
    const granted = await permissions.isGranted(permission);
    if (!granted) {
      return permissions.request(permission);
    }
    return true;
  });

  registry.register('openDeeplink', async ({ target, extras }) => {
    const uri = resolveDeeplink(target, extras);
    return launchDeeplink(uri);
  });

  registry.register('toggleBluetooth', async ({ enabled }) => {
    return native.call('bluetooth.setEnabled', { enabled });
  });

  registry.register('scanBluetoothDevices', async ({ timeoutMs = 8000 }) => {
    return native.call('bluetooth.scan', { timeoutMs });
  });

  registry.register('pairBluetoothDevice', async ({ address }) => {
    return native.call('bluetooth.pair', { address });
  });

  registry.register('toggleWifi', async ({ enabled }) => {
    return native.call('wifi.setEnabled', { enabled });
  });

  registry.register('setVolume', async ({ level }) => {
    const clamped = Math.max(0, Math.min(100, level));
    return native.call('audio.setVolume', { level: clamped });
  });

  registry.register('setBrightness', async ({ level }) => {
    return native.call('display.setBrightness', { level });
  });

  registry.register('getBatteryStatus', async () => {
    return native.call('battery.status', {});
  });

  registry.register('getUserLocation', async () => {
    return location.getCurrentPosition();
  });
}

module.exports = { registerDeviceTools };
