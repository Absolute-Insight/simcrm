import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const totalSteps = ref(0)
const updateOnboardingStep = vi.fn()

vi.mock('@framework/ui/components/Onboarding', () => ({
  useOnboarding: () => ({ totalSteps, updateOnboardingStep }),
}))

import { useCRMOnboarding } from '@/composables/useCRMOnboarding'

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.(vue|js)$/.test(name) ? [path] : []
  })
}

describe('useCRMOnboarding', () => {
  beforeEach(() => {
    totalSteps.value = 0
    updateOnboardingStep.mockClear()
  })

  it('does nothing while no steps are registered, as for a rep', () => {
    useCRMOnboarding().updateOnboardingStep('add_first_comment')

    expect(updateOnboardingStep).not.toHaveBeenCalled()
  })

  it('passes a step through once they are', () => {
    const { updateOnboardingStep: update } = useCRMOnboarding()
    totalSteps.value = 8
    const callback = () => {}

    update('convert_lead_to_deal', true, false, callback)

    expect(updateOnboardingStep).toHaveBeenCalledWith(
      'convert_lead_to_deal',
      true,
      false,
      callback,
    )
  })

  it('is what the app calls, because the framework one throws for a rep', () => {
    const allowed = [
      'src/composables/useCRMOnboarding.js',
      'src/components/Layouts/AppSidebar.vue',
      'src/components/OnboardingPanel.vue',
    ]
    const offenders = sourceFiles(join(process.cwd(), 'src'))
      .map((file) => relative(process.cwd(), file))
      .filter((file) => !file.startsWith('src/lib/framework-ui-stub/'))
      .filter((file) => !allowed.includes(file))
      .filter((file) =>
        /import \{[^}]*\buseOnboarding\b[^}]*\} from '@framework/.test(
          readFileSync(file, 'utf8'),
        ),
      )

    expect(offenders).toEqual([])
  })
})
