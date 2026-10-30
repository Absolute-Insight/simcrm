import { useOnboarding } from '@framework/ui/components/Onboarding'

/**
 * The getting-started checklist, for everything but the sidebar that owns it.
 *
 * Only the desktop sidebar registers the steps, and only for a manager (see
 * AppSidebar), but every page reports a step whoever is using it. The
 * framework's updateOnboardingStep reads the registered list unguarded, so for
 * a rep or on a phone it threw and the caller stopped there: a converted lead
 * never opened its deal, and a changed password never said so.
 */
export function useCRMOnboarding() {
  const onboarding = useOnboarding('frappecrm')

  return {
    ...onboarding,
    updateOnboardingStep(...args) {
      if (onboarding.totalSteps.value) onboarding.updateOnboardingStep(...args)
    },
  }
}
