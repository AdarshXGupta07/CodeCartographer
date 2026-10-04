'use strict';

const logger = require('../utils/logger');

/**
 * Shared behaviour for all agents. Subclasses implement `run(request)`.
 */
class BaseAgent {
  constructor({ tools, settings }) {
    this.tools = tools;
    this.settings = settings;
    this.name = this.constructor.name;
  }

  async execute(request) {
    logger.debug(`${this.name} handling ${request.intent.name}`);
    try {
      const result = await this.run(request);
      return { status: 'ok', ...result };
    } catch (err) {
      logger.error(`${this.name} failed`, err);
      return { status: 'error', speech: 'I could not complete that.' };
    }
  }

  async run() {
    throw new Error('run() not implemented');
  }

  respond(speech, data = {}) {
    return { speech, data };
  }
}

module.exports = { BaseAgent };
