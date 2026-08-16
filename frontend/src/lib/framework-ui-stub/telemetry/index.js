// No-op mirror of @framework/ui/telemetry — see ../README.md.
export const telemetryPlugin = { install() {} }

export function useTelemetry() {
  return { capture: () => {} }
}
