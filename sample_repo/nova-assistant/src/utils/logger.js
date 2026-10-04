'use strict';

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const current = LEVELS[process.env.NOVA_LOG_LEVEL || 'info'];

function log(level, msg, extra) {
  if (LEVELS[level] < current) return;
  const line = `[${new Date().toISOString()}] ${level.toUpperCase()} ${msg}`;
  if (extra) console.log(line, extra);
  else console.log(line);
}

module.exports = {
  debug: (m, e) => log('debug', m, e),
  info: (m, e) => log('info', m, e),
  warn: (m, e) => log('warn', m, e),
  error: (m, e) => log('error', m, e),
};
