'use strict';

const { BaseAgent } = require('./baseAgent');

/**
 * Creates and lists reminders.
 */
class ReminderAgent extends BaseAgent {
  async run({ intent, slots }) {
    if (intent.name === 'reminder.list') {
      const reminders = await this.tools.invoke('listReminders', { day: slots.day });
      return this.respond(`You have ${reminders.length} reminders.`, reminders);
    }
    await this.tools.invoke('checkPermission', { permission: 'SCHEDULE_EXACT_ALARM' });
    await this.tools.invoke('createReminder', { task: slots.task, time: slots.time });
    return this.respond(`Okay, I'll remind you to ${slots.task}.`);
  }
}

module.exports = { ReminderAgent };
