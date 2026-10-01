import { expect, test, type Page } from '@playwright/test'

/**
 * The README's five-minute demo, clicked through the UI (B19, Phase 8 DoD): PO 7 goes from
 * MATERIAL_SHORTAGE to COMPLETED. Order 7 and STEEL-001 are those of a fresh `python -m seed`.
 */
const PASSWORD = process.env.E2E_PASSWORD ?? ''
const ORDER = 'PO-2026-00007'

async function loginAs(page: Page, username: string) {
  await page.goto('/login')
  await page.getByLabel('Tên đăng nhập').fill(username)
  await page.getByLabel('Mật khẩu').fill(PASSWORD)
  await page.getByRole('button', { name: 'Đăng nhập' }).click()
  await expect(page.getByRole('button', { name: 'Đăng xuất' })).toBeVisible()
}

async function logout(page: Page) {
  await page.getByRole('button', { name: 'Đăng xuất' }).click()
  await expect(page.getByRole('button', { name: 'Đăng nhập' })).toBeVisible()
}

async function openOrder(page: Page) {
  await page.getByRole('link', { name: 'Lệnh sản xuất' }).click()
  await page.getByRole('link', { name: ORDER }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText(ORDER)
}

async function report(page: Page, worker: string, good: string, rejected = '') {
  await loginAs(page, worker)
  await page.getByRole('link', { name: 'Work center của tôi' }).click()
  const order = page.locator('section', { has: page.getByRole('heading', { name: new RegExp(ORDER) }) })
  await order.getByLabel('Đạt').fill(good)
  if (rejected) await order.getByLabel('Lỗi').fill(rejected)
  const sent = page.waitForResponse((r) => r.url().includes('/progress') && r.request().method() === 'POST')
  await order.getByRole('button', { name: 'Báo' }).click()
  expect((await sent).status()).toBe(200)
  await logout(page)
}

test('shortage to completed through the UI', async ({ page }) => {
  test.skip(!PASSWORD, 'set E2E_PASSWORD to the seed password')

  // 1. The manager sees the risks, the bottleneck and the shortage.
  await loginAs(page, 'demo.manager')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect(page.getByText('OVERDUE', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('row', { name: /WC-WELD.*BOTTLENECK/ })).toBeVisible()
  await openOrder(page)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('MATERIAL_SHORTAGE')
  // BR-PO-05: only what the server allows.
  await expect(page.getByRole('button', { name: 'Bắt đầu sản xuất' })).toHaveCount(0)
  await logout(page)

  // 2. The warehouse receives steel, re-checks the order and issues every line.
  await loginAs(page, 'demo.warehouse')
  await page.getByRole('link', { name: 'Tồn kho' }).click()
  const material = page.getByRole('combobox', { name: 'Vật tư' }).first()
  const steel = await material.locator('option', { hasText: 'STEEL-001' }).getAttribute('value')
  await material.selectOption(steel ?? '')
  await page.getByLabel(/^Số lượng/).fill('200')
  await page.getByLabel('Số chứng từ / lý do').fill('GRN-E2E')
  await page.getByRole('button', { name: 'Nhập kho' }).click()
  await expect(page.getByRole('status')).toContainText('RECEIVE STEEL-001')

  await openOrder(page)
  await page.getByRole('button', { name: 'Kiểm tra lại vật tư' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('READY_TO_PRODUCE')
  const lines = page.locator('section', { has: page.getByRole('heading', { name: 'Vật tư' }) }).locator('tbody tr')
  await expect(lines).toHaveCount(3)
  for (let i = 0; i < 3; i++) {
    const issued = page.waitForResponse((r) => r.url().includes('/inventory/issues'))
    await lines.nth(i).getByRole('button', { name: 'Xuất' }).click()
    expect((await issued).status()).toBe(201)
  }
  await logout(page)

  // 3. The manager starts production.
  await loginAs(page, 'demo.manager')
  await openOrder(page)
  await page.getByRole('button', { name: 'Bắt đầu sản xuất' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('IN_PROGRESS')
  await logout(page)

  // 4. Each worker reports at their own station, with scrap at painting and QC.
  await report(page, 'demo.cut', '400')
  await report(page, 'demo.weld', '400')
  await report(page, 'demo.paint', '398', '2')
  await report(page, 'demo.qc', '396', '2')

  // 5. The order completed itself (D-12) with the good units of the last operation.
  await loginAs(page, 'demo.manager')
  await openOrder(page)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('COMPLETED')
  await expect(page.getByText(/Hoàn thành: 396/)).toBeVisible()
  await logout(page)

  // 6. The admin finds the completion in the audit log.
  await loginAs(page, 'demo.admin')
  await page.getByRole('link', { name: 'Audit log' }).click()
  await page.getByLabel('Hành động').selectOption('ORDER_COMPLETED')
  await expect(page.getByRole('cell', { name: 'ORDER_COMPLETED' }).first()).toBeVisible()
})
