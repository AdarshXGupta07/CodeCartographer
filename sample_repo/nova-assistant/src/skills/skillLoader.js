'use strict';

const fs = require('fs');
const path = require('path');
const logger = require('../utils/logger');

/**
 * Loads third-party skill manifests (JSON) from a directory.
 */
function loadSkills(dir) {
  if (!fs.existsSync(dir)) {
    logger.warn(`skills dir ${dir} missing`);
    return [];
  }
  const skills = [];
  const files = fs.readdirSync(dir);
  for (const file of files) {
    if (!file.endsWith('.json')) continue;
    const raw = fs.readFileSync(path.join(dir, file), 'utf8');
    const manifest = JSON.parse(raw);
    if (validateManifest(manifest)) {
      skills.push(manifest);
    }
  }
  return skills;
}

function validateManifest(manifest) {
  return Boolean(manifest && manifest.name && Array.isArray(manifest.intents));
}

module.exports = { loadSkills, validateManifest };
