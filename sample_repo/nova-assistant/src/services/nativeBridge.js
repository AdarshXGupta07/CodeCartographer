'use strict';

const logger = require('../utils/logger');

let bridge = null;

/**
 * JS <-> Android bridge. On device this is injected by the host app;
 * in tests a mock bridge is installed with `install()`.
 */
function install(nativeImpl) {
  bridge = nativeImpl;
}

async function call(method, payload) {
  if (!bridge) {
    logger.warn(`native bridge not installed, dropping ${method}`);
    return null;
  }
  const raw = await bridge.postMessage(JSON.stringify({ method, payload }));
  return raw ? JSON.parse(raw) : null;
}

module.exports = { install, call };
