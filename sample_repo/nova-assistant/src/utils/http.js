'use strict';

const https = require('https');

/**
 * Minimal promise based GET returning parsed JSON.
 */
function httpGet(url, { timeoutMs = 5000 } = {}) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch (err) {
          reject(err);
        }
      });
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error(`timeout after ${timeoutMs}ms`)));
    req.on('error', reject);
  });
}

module.exports = { httpGet };
