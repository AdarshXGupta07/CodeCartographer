'use strict';

const native = require('../services/nativeBridge');

/**
 * Reminder and calendar tools.
 */
function registerCalendarTools(registry) {
  registry.register('createReminder', async ({ task, time }) => {
    const when = new Date();
    when.setHours(time.hour, time.minutes || 0, 0, 0);
    if (when < new Date()) when.setDate(when.getDate() + 1);
    return native.call('reminders.create', { task, at: when.toISOString() });
  });

  registry.register('listReminders', async ({ day }) => {
    const all = await native.call('reminders.list', {});
    if (!day) return all;
    return all.filter((r) => r.at.startsWith(day));
  });

  registry.register('deleteReminder', async ({ id }) => native.call('reminders.delete', { id }));
}

module.exports = { registerCalendarTools };
