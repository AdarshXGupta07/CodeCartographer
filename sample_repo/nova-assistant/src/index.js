'use strict';

const { Assistant } = require('./core/assistant');
const { loadSettings } = require('./config/settings');
const { registerDeviceTools } = require('./tools/deviceTools');
const { registerMediaTools } = require('./tools/mediaTools');
const { registerNetworkTools } = require('./tools/networkTools');
const { registerCalendarTools } = require('./tools/calendarTools');
const { registerContactTools } = require('./tools/contactTools');
const { ToolRegistry } = require('./tools/toolRegistry');
const { loadSkills } = require('./skills/skillLoader');
const logger = require('./utils/logger');

/**
 * Boot the assistant: load config, register every tool, load skills
 * and start listening for utterances from the ASR pipeline.
 */
async function bootstrap() {
  const settings = loadSettings();
  const registry = new ToolRegistry();

  registerDeviceTools(registry);
  registerMediaTools(registry);
  registerNetworkTools(registry, settings);
  registerCalendarTools(registry);
  registerContactTools(registry);

  const skills = loadSkills(settings.skillsDir);
  const assistant = new Assistant({ registry, settings, skills });

  await assistant.start();
  logger.info(`Nova ${settings.version} ready with ${registry.size()} tools`);
  return assistant;
}

if (require.main === module) {
  bootstrap().catch((err) => {
    logger.error('Fatal boot error', err);
    process.exit(1);
  });
}

module.exports = { bootstrap };
