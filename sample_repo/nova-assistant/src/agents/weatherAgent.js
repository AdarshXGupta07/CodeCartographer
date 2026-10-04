'use strict';

const { BaseAgent } = require('./baseAgent');

/**
 * "What's the weather", "will it rain tomorrow".
 */
class WeatherAgent extends BaseAgent {
  async run() {
    await this.tools.invoke('checkPermission', { permission: 'ACCESS_COARSE_LOCATION' });
    const position = await this.tools.invoke('getUserLocation');
    const forecast = await this.tools.invoke('fetchWeather', { lat: position.lat, lon: position.lon });
    return this.respond(this.describe(forecast), forecast);
  }

  describe(forecast) {
    const today = forecast.daily[0];
    return `It's ${Math.round(forecast.current.temp)} degrees with ${today.summary.toLowerCase()}.`;
  }
}

module.exports = { WeatherAgent };
