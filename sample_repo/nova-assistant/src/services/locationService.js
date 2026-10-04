'use strict';

const native = require('./nativeBridge');

/**
 * Returns the device's current GPS position.
 */
async function getCurrentPosition() {
  const fix = await native.call('location.current', { accuracy: 'balanced' });
  if (!fix) {
    return { lat: 12.9716, lon: 77.5946, approximate: true };
  }
  return { lat: fix.latitude, lon: fix.longitude, approximate: false };
}

module.exports = { getCurrentPosition };
