'use strict';

const { AgentRouter } = require('./agentRouter');
const { DialogManager } = require('./dialogManager');
const { SessionStore } = require('./sessionStore');
const eventBus = require('./eventBus');
const { IntentClassifier } = require('../nlu/intentClassifier');
const { extractEntities } = require('../nlu/entityExtractor');
const { fillSlots } = require('../nlu/slotFiller');
const { AsrService } = require('../services/asrService');
const { TtsService } = require('../services/ttsService');
const analytics = require('../services/analytics');
const logger = require('../utils/logger');

/**
 * Top level orchestrator. Receives a transcript from ASR, runs NLU,
 * routes the intent to an agent and speaks the response.
 */
class Assistant {
  constructor({ registry, settings, skills }) {
    this.registry = registry;
    this.settings = settings;
    this.skills = skills;
    this.sessions = new SessionStore();
    this.classifier = new IntentClassifier(settings.nlu);
    this.router = new AgentRouter(registry, settings);
    this.dialog = new DialogManager(this.sessions);
    this.asr = new AsrService(settings.asr);
    this.tts = new TtsService(settings.tts);
  }

  async start() {
    this.asr.on('transcript', (evt) => this.handleUtterance(evt.sessionId, evt.text));
    eventBus.subscribe('agent:error', (err) => this.onAgentError(err));
    await this.asr.startListening();
  }

  /**
   * Main entry point for a single user utterance.
   */
  async handleUtterance(sessionId, text) {
    const started = Date.now();
    const session = this.sessions.getOrCreate(sessionId);
    const intent = await this.classifier.classify(text);
    const entities = extractEntities(text);
    const slots = fillSlots(intent, entities, session.context);

    if (this.dialog.needsClarification(intent, slots)) {
      const prompt = this.dialog.buildClarification(intent, slots);
      await this.tts.speak(prompt);
      return { status: 'clarify', prompt };
    }

    const agent = this.router.route(intent);
    const result = await agent.execute({ intent, slots, session, text });
    this.dialog.updateContext(session, intent, slots, result);
    await this.tts.speak(result.speech);
    analytics.trackTurn(sessionId, intent.name, Date.now() - started);
    return result;
  }

  onAgentError(err) {
    logger.error('Agent failed', err);
    this.tts.speak("Sorry, something went wrong. Please try again.");
  }
}

module.exports = { Assistant };
