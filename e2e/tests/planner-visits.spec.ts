import {
  test,
  expect,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { createDoc, deleteDoc, getList } from "../helpers";

/**
 * MBP's managers asked for the old rep app's habits in the planner: every
 * activity is planned against a customer, nothing is closed without saying
 * what happened, a cancelled visit is not a missed one, unplanned work of any
 * kind can be logged, and a manager sees the whole team's week at once.
 */

interface Row {
  name: string;
}

async function deleteOwnPlans(request: APIRequestContext) {
  for (const plan of await getList<Row>(request, "CRM Rep Plan", {
    filters: { user: "Administrator" },
    fields: ["name"],
    limit: 50,
  })) {
    await deleteDoc(request, "CRM Rep Plan", plan.name).catch(() => {});
  }
}

function field(dialog: Locator, page: Page, label: string): Locator {
  // a required field's label reads "Activity *"
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return dialog
    .locator(".field")
    .filter({ has: page.getByText(new RegExp(`^${escaped}\\s*\\*?$`)) });
}

async function chooseActivity(dialog: Locator, page: Page, label: string) {
  await field(dialog, page, "Activity").getByRole("combobox").click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

async function pickCustomer(dialog: Locator, page: Page, name: string) {
  await field(dialog, page, "Customer").getByRole("button").first().click();
  await page.getByPlaceholder("Search").fill(name);
  await page.getByRole("option", { name }).click();
}

test.describe("Planner: customers, outcomes and the team week", () => {
  let orgName: string;

  test.beforeAll(async ({ request }) => {
    const org = await createDoc<Row>(request, "CRM Organization", {
      organization_name: `E2E Visit Customer ${Date.now()}`,
    });
    orgName = org.name;
  });

  test.beforeEach(async ({ request, page }) => {
    await deleteOwnPlans(request);
    await page.goto("/crm/planner");
    await expect(
      page.getByRole("button", { name: "Log activity" }),
    ).toBeVisible();
  });

  test.afterEach(async ({ request }) => {
    await deleteOwnPlans(request);
    for (const event of await getList<Row>(request, "Event", {
      filters: { subject: ["like", `%${orgName}%`] },
      fields: ["name"],
      limit: 50,
    })) {
      await deleteDoc(request, "Event", event.name).catch(() => {});
    }
  });

  test.afterAll(async ({ request }) => {
    if (orgName)
      await deleteDoc(request, "CRM Organization", orgName).catch(() => {});
  });

  async function planAVisit(page: Page, note: string) {
    await page.getByRole("button", { name: "Add an activity" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(
      field(dialog, page, "Activity").getByRole("combobox"),
    ).toHaveText(/Visit/);
    await pickCustomer(dialog, page, orgName);
    await dialog.getByPlaceholder("Note").fill(note);
    await dialog.getByRole("button", { name: /add to plan/i }).click();
    await page.getByRole("button", { name: "Save plan" }).click();
    await expect(page.getByText("Plan saved")).toBeVisible();
    return page.locator(".v-plan-card", { hasText: note });
  }

  async function openActions(card: Locator) {
    await card.hover();
    await card
      .getByRole("button", { name: "Actions for this planned activity" })
      .click();
  }

  test("a visit is planned against a customer and closed with its outcome", async ({
    page,
  }) => {
    const card = await planAVisit(page, "E2E quotation follow-up");
    await expect(card.getByRole("link", { name: orgName })).toBeVisible();

    await openActions(card);
    await page.getByRole("menuitem", { name: "Log the outcome…" }).click();
    const dialog = page.getByRole("dialog");
    await field(dialog, page, "What happened")
      .locator("textarea")
      .fill("Replaced the knife gate valve");
    await dialog.getByRole("button", { name: "Mark as done" }).click();

    await expect(card.getByText("Visit · Done")).toBeVisible();
    await expect(card.getByText("Replaced the knife gate valve")).toBeVisible();
  });

  test("a cancelled visit reads cancelled, not missed", async ({ page }) => {
    const card = await planAVisit(page, "E2E visit to cancel");
    await openActions(card);
    await page.getByRole("menuitem", { name: "Cancel it…" }).click();
    const dialog = page.getByRole("dialog");
    await field(dialog, page, "Why was it cancelled?")
      .locator("textarea")
      .fill("Plant shut");
    await dialog.getByRole("button", { name: "Cancel activity" }).click();

    await expect(card.getByText("Visit · Cancelled")).toBeVisible();
    await expect(page.getByText(/1 cancelled/)).toBeVisible();
  });

  test("a delivery is logged against its customer", async ({ page }) => {
    await page.getByRole("button", { name: "Log activity" }).click();
    const dialog = page.getByRole("dialog");
    await chooseActivity(dialog, page, "Delivery");
    await pickCustomer(dialog, page, orgName);
    await field(dialog, page, "What happened")
      .locator("textarea")
      .fill("Dropped off four actuators");
    await dialog.getByRole("button", { name: "Log activity" }).click();

    const card = page.locator(".v-plan-card", {
      hasText: "Dropped off four actuators",
    });
    await expect(card.getByText("Delivery · Done")).toBeVisible();
  });

  test("a manager sees the whole team week", async ({ page }) => {
    const picker = page.getByRole("combobox", { name: "Whose plan to show" });
    await picker.click();
    await page.getByRole("option", { name: "Whole team" }).click();
    await expect(page.getByRole("columnheader", { name: "Rep" })).toBeVisible();
    await expect(
      page.getByRole("combobox", { name: "Show activity type" }),
    ).toBeVisible();
  });
});
