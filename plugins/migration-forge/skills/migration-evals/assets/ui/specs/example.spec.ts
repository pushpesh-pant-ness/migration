import { test, expect } from '@playwright/test';

// Name tests "<STORY-ID> <flow>" so ui_e2e cases can select them with "grep".
// Use role/label/text locators that describe what the USER sees, never framework-specific
// selectors (ng-*, data-reactroot, generated class names). The same spec must pass on legacy and new.
test('STORY-002 customer sees own orders newest first', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox').fill('42');
  await page.getByRole('button', { name: 'Load' }).click();
  const rows = page.getByRole('listitem');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('#2');   // newest first (BR-2)
});

// Visual parity (only with "visual": true in the case): golden image is taken from legacy.
// Mask volatile regions instead of loosening the threshold.
test('STORY-002 order list looks the same', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Load' }).click();
  await expect(page).toHaveScreenshot('orders.png', { mask: [page.locator('time')] });
});
