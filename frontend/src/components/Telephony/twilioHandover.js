/**
 * The call that outlived the popup it was answered in.
 *
 * The app shell swaps its mobile and desktop layouts at a breakpoint, each
 * with a header that mounts its own TwilioCallUI. A swap while a rep is on a
 * call unmounts the popup the call is shown in, and the next one starts with
 * a Device of its own that knows nothing about it: the call went on, with no
 * way to mute it or hang up.
 *
 * So the instance that unmounts mid-call leaves the call here, and the one
 * that mounts next picks it up and draws its controls. It is module state
 * because it has to outlive both: `current` is null whenever no call is
 * between popups.
 *
 * @type {{current: null | {
 *   call: object, incoming: boolean, number: string,
 *   onCall: boolean, calling: boolean, callStatus: string, muted: boolean,
 * }}}
 */
export const twilioHandover = { current: null }
