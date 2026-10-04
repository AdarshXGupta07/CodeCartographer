'use strict';

const logger = require('../utils/logger');
const eventBus = require('../core/eventBus');

/**
 * Central registry for every tool an agent may invoke.
 * Tools are registered by name and invoked with `registry.invoke(name, args)`.
 */
class ToolRegistry {
  constructor() {
    this.tools = new Map();
  }

  register(name, handler, meta = {}) {
    if (this.tools.has(name)) {
      throw new Error(`Tool ${name} already registered`);
    }
    this.tools.set(name, { name, handler, meta });
  }

  size() {
    return this.tools.size;
  }

  list() {
    return Array.from(this.tools.keys());
  }

  async invoke(name, args = {}) {
    const tool = this.tools.get(name);
    if (!tool) {
      throw new Error(`Unknown tool: ${name}`);
    }
    const started = Date.now();
    try {
      const result = await tool.handler(args, this);
      eventBus.publish('tool:invoked', { name, ms: Date.now() - started });
      return result;
    } catch (err) {
      logger.error(`Tool ${name} failed`, err);
      eventBus.publish('agent:error', err);
      throw err;
    }
  }
}

module.exports = { ToolRegistry };
