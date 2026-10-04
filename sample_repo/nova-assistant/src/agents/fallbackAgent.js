'use strict';

const { BaseAgent } = require('./baseAgent');

/**
 * Catches anything the router could not map to a specialised agent.
 */
class FallbackAgent extends BaseAgent {
  async run({ text }) {
    return this.respond(`Sorry, I don't know how to help with "${text}" yet.`);
  }
}

module.exports = { FallbackAgent };
