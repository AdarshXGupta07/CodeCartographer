'use strict';

const { httpGet } = require('../utils/http');
const { withRetry } = require('../utils/retry');
const { TtlCache } = require('../utils/cache');

const weatherCache = new TtlCache(10 * 60 * 1000);

/**
 * Network backed tools (weather, generic fetch).
 */
function registerNetworkTools(registry, settings) {
  registry.register('fetchWeather', async ({ lat, lon }) => {
    const key = `${lat.toFixed(2)},${lon.toFixed(2)}`;
    const cached = weatherCache.get(key);
    if (cached) return cached;
    const url = `${settings.weatherApi}/v1/forecast?lat=${lat}&lon=${lon}`;
    const data = await withRetry(() => httpGet(url), 3);
    weatherCache.set(key, data);
    return data;
  });

  registry.register('httpFetch', async ({ url }) => withRetry(() => httpGet(url), 2));
}

module.exports = { registerNetworkTools };
