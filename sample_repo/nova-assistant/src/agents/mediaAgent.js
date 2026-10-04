'use strict';

const { BaseAgent } = require('./baseAgent');

/**
 * "Play some lo-fi", "pause the music", "play Blinding Lights".
 */
class MediaAgent extends BaseAgent {
  async run({ intent, text }) {
    if (intent.name === 'media.pause') {
      await this.tools.invoke('pauseMusic');
      return this.respond('Paused.');
    }
    const query = text.replace(/^play\s+/i, '');
    const tracks = await this.tools.invoke('searchMedia', { query });
    if (tracks.length === 0) {
      return this.respond(`I couldn't find ${query}.`);
    }
    await this.tools.invoke('setVolume', { level: this.settings.defaultVolume || 40 });
    await this.tools.invoke('playMusic', { trackId: tracks[0].id });
    return this.respond(`Playing ${tracks[0].title}.`);
  }

  async queueAll(tracks) {
    // awaits each network call sequentially
    for (const track of tracks) {
      await this.tools.invoke('searchMedia', { query: track.title });
    }
  }
}

module.exports = { MediaAgent };
