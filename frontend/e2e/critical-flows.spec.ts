import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

import { installFixture, signIn } from './fixtures';

const VIEWPORTS = [390, 768, 1280] as const;

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page): Promise<void> {
  const widths = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
    body: document.body.scrollWidth,
  }));
  expect(widths.document, `document overflow: ${JSON.stringify(widths)}`).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body, `body overflow: ${JSON.stringify(widths)}`).toBeLessThanOrEqual(widths.viewport);
}

test('unauthenticated navigation reaches login and a controlled 401 is surfaced', async ({ page }) => {
  const state = await installFixture(page);
  await page.goto('/estado');
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page);
  await expect(page.getByTestId('planning-recovery')).toBeVisible();
  state.unauthorizedStatus = true;
  await page.reload();
  await expect(page.getByTestId('failure')).toBeVisible();
  await expect(page.getByTestId('failure')).toContainText('No se puede contactar');
});

for (const width of VIEWPORTS) {
  test(`status remains usable and accessible at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await installFixture(page);
    await signIn(page);
    await expect(page.getByTestId('planning-recovery')).toContainText('Falta telemetría reciente');
    await expectNoHorizontalOverflow(page);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((item) => item.impact === 'critical' || item.impact === 'serious')).toEqual([]);
  });
}

test('invalid planning explains the correction and keeps activation disabled until a valid preview', async ({ page }) => {
  const state = await installFixture(page);
  await signIn(page);
  await page.goto('/planificacion');
  await expect(page.getByTestId('planning-recovery')).toBeVisible();
  await expect(page.getByTestId('planning-recovery-action')).toHaveAttribute('href', '/estado#telemetry-title');
  const planningA11y = await new AxeBuilder({ page }).analyze();
  expect(planningA11y.violations.filter((item) => item.impact === 'critical' || item.impact === 'serious')).toEqual([]);
  await page.getByRole('tab', { name: 'Nueva planificación' }).click();
  const activate = page.getByTestId('activate-button');
  await expect(activate).toBeDisabled();
  await page.getByTestId('target-temperature-input').fill('22');
  await page.getByTestId('recalculate-button').click();
  await expect(page.getByTestId('preview-visualization')).toBeVisible();
  await expect(activate).toBeEnabled();
  await activate.click();
  await expect(page.getByTestId('confirm-delete')).toBeVisible();
  const activation = page.waitForResponse((response) => response.url().endsWith('/api/v1/planning/activate'));
  await page.getByTestId('confirm-delete').click();
  await activation;
  expect(state.activated).toBe(true);
  await expect(page.getByTestId('planning-action-error')).toHaveCount(0);
});

test('essential planning controls remain keyboard reachable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await installFixture(page);
  await signIn(page);
  await page.goto('/planificacion');
  await page.getByRole('tab', { name: 'Nueva planificación' }).click();
  await page.getByTestId('target-temperature-input').focus();
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.type('22');
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (await page.getByTestId('recalculate-button').evaluate((element) => element === document.activeElement)) break;
    await page.keyboard.press('Tab');
  }
  await expect(page.getByTestId('recalculate-button')).toBeFocused();
  await expectNoHorizontalOverflow(page);
});
