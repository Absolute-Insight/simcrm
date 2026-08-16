// No-op mirror of @framework/ui/components/Onboarding — see ../../README.md.
import { computed, defineComponent, ref } from 'vue'

const NullComponent = defineComponent({
  name: 'FrameworkUiStub',
  render: () => null,
})

export const GettingStartedBanner = NullComponent
export const HelpModal = NullComponent
export const IntermediateStepModal = NullComponent

export function showHelpModal() {}
export function minimize() {}

export function useOnboarding() {
  return {
    steps: undefined,
    stepsCompleted: computed(() => 0),
    totalSteps: computed(() => 0),
    completedPercentage: computed(() => 0),
    isOnboardingStepsCompleted: ref(false),
    setUp: () => {},
    updateOnboardingStep: () => {},
  }
}
