/**
 * Where a notification row points, and what identifies it in a list.
 *
 * `crm.api.notifications.get_notifications` returns a `hash` the server has
 * already worked out -- `#<comment name>` for a mention, `#whatsapp`, `#tasks`
 * for a task assignment, and empty when the notification points at the record
 * itself. The client built its own instead, out of a `comment` field the
 * payload does not contain, so it read `'#' + undefined`. That is a truthy
 * string, so the `||` fallback beside it could never run and every tap landed
 * on `#undefined` -- which the tab manager does not recognise, so a mention
 * opened the deal on whichever tab was last used rather than on the comment.
 *
 * The same missing field was the list key, so every row keyed as `undefined`
 * and Vue could not tell them apart on a reload.
 */

/**
 * The router target for a notification row, or null when it points nowhere.
 *
 * A task can be assigned with no lead or deal behind it. Its notification came
 * back labelled with the Lead route and no name, and asking vue-router for
 * `/leads/:leadId` without a leadId throws while the row renders -- so the row
 * the badge counted never appeared. Such a task is on the Tasks list; anything
 * else that names no record gets a row that is not a link.
 */
export function notificationRoute(notification) {
  const routeName = notification?.route_name
  const referenceName = notification?.reference_name
  if (!routeName || !referenceName) {
    return notification?.notification_type_doctype === 'CRM Task'
      ? { name: 'Tasks' }
      : null
  }
  return {
    name: routeName,
    params:
      routeName === 'Deal'
        ? { dealId: referenceName }
        : { leadId: referenceName },
    // The server's hash, or none: an empty hash lands on the record's default
    // tab, which is the right answer for a notification that names no anchor.
    hash: notification?.hash || '',
  }
}

/**
 * A stable per-row key.
 *
 * The payload carries no primary key, so this pairs the creation timestamp --
 * unique per user to the microsecond -- with the document the notification is
 * about, which separates two notifications raised in the same transaction.
 */
export function notificationKey(notification) {
  return `${notification?.creation ?? ''}:${
    notification?.notification_type_doc ?? ''
  }`
}
