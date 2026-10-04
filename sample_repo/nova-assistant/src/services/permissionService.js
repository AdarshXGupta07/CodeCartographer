'use strict';

const native = require('./nativeBridge');

const grantedCache = new Set();

/**
 * Runtime permission helpers wrapping the Android permission APIs.
 */
async function isGranted(permission) {
  if (grantedCache.has(permission)) return true;
  const granted = await native.call('permissions.check', { permission });
  if (granted) grantedCache.add(permission);
  return granted;
}

async function request(permission) {
  const granted = await native.call('permissions.request', { permission });
  if (granted) grantedCache.add(permission);
  return granted;
}

module.exports = { isGranted, request };
