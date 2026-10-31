// A stand-in for '@twilio/voice-sdk'. The constructor rejects a token that is
// not a string, as the real Device does (it calls updateToken, which throws).
//
//   vi.mock('@twilio/voice-sdk', () => import('./telephony/twilioSdk.js'))
class Emitter {
  constructor() {
    this.handlers = {}
  }
  on(event, fn) {
    ;(this.handlers[event] ||= []).push(fn)
    return this
  }
  emit(event, ...args) {
    for (const fn of this.handlers[event] || []) fn(...args)
  }
}

export class FakeCall extends Emitter {
  constructor(parameters) {
    super()
    this.parameters = parameters
    this.muted = false
  }
  accept() {
    return Promise.resolve()
  }
  reject() {
    this.emit('reject')
  }
  disconnect() {
    this.emit('disconnect')
  }
  isMuted() {
    return this.muted
  }
  mute(value = true) {
    this.muted = value
  }
}

// Every Device constructed, oldest first.
export const devices = []
export const connect = { fail: null }

export class Device extends Emitter {
  constructor(token, options) {
    super()
    if (typeof token !== 'string') {
      throw new Error('Parameter "token" must be of type "string".')
    }
    this.token = token
    this.options = options
    this.state = 'unregistered'
    devices.push(this)
  }
  register() {
    this.state = 'registered'
    return Promise.resolve()
  }
  destroy() {
    this.state = 'destroyed'
  }
  updateToken(token) {
    this.token = token
  }
  async connect({ params }) {
    if (connect.fail) throw connect.fail
    this.lastCall = new FakeCall({ CallSid: 'CA-OUT', To: params.To })
    return this.lastCall
  }
}
