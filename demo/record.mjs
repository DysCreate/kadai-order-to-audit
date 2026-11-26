/**
 * Kadai order-to-audit — narrated-by-captions demo recording.
 *
 * One browser context, one page, one continuous video. Captions are injected
 * DOM banners because Playwright records no audio.
 *
 *   node demo/record.mjs                # full run against BASE_URL
 *   BASE_URL=http://localhost:3000 node demo/record.mjs
 *   DRY=1 node demo/record.mjs          # validate selectors, write nothing
 *   SPEED=0.95 node demo/record.mjs     # stretch/compress every caption pause
 *
 * The script never logs in with a role it was not given, never touches app
 * code, and only uses role/text/label locators.
 */
import { chromium } from 'playwright'
import { execFileSync } from 'node:child_process'
import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'

const HERE = path.dirname(new URL(import.meta.url).pathname)
const DEMO = HERE
const SCREENS = path.join(DEMO, 'screens')
const VIDEOS = path.join(DEMO, 'videos')
const ASSETS = path.join(DEMO, 'assets')

const BASE = process.env.BASE_URL ?? 'https://13-207-33-205.sslip.io'
const DRY = process.env.DRY === '1'
const SPEED = Number(process.env.SPEED ?? '1')
const SLOWMO = Number(process.env.SLOWMO ?? '250')

await mkdir(SCREENS, { recursive: true })
await mkdir(VIDEOS, { recursive: true })
await mkdir(ASSETS, { recursive: true })
for (const name of await readdir(VIDEOS)) await rm(path.join(VIDEOS, name), { force: true })

const startedAt = Date.now()
const elapsed = () => (Date.now() - startedAt) / 1000
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const pause = (seconds) => sleep((seconds * 1000) / SPEED)

const results = []

/* ------------------------------------------------------------------ */
/* Browser                                                             */
/* ------------------------------------------------------------------ */
const browser = await chromium.launch({ slowMo: SLOWMO })
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: VIDEOS, size: { width: 1280, height: 720 } },
  acceptDownloads: true
})

// A red dot follows the real pointer so every click is visible in the video.
await context.addInitScript(() => {
  const install = () => {
    if (!document.body || document.getElementById('__kadai_cursor')) return
    const dot = document.createElement('div')
    dot.id = '__kadai_cursor'
    Object.assign(dot.style, {
      position: 'fixed',
      left: '-40px',
      top: '-40px',
      width: '16px',
      height: '16px',
      borderRadius: '999px',
      background: 'rgba(220, 38, 38, 0.9)',
      border: '2px solid #fff',
      boxShadow: '0 0 0 5px rgba(220, 38, 38, 0.25)',
      zIndex: '2147483647',
      pointerEvents: 'none',
      transition: 'width 90ms ease, height 90ms ease, margin 90ms ease'
    })
    document.body.appendChild(dot)
    window.addEventListener(
      'mousemove',
      (event) => {
        dot.style.left = `${event.clientX - 8}px`
        dot.style.top = `${event.clientY - 8}px`
      },
      { passive: true }
    )
    window.addEventListener('mousedown', () => {
      dot.style.width = '30px'
      dot.style.height = '30px'
      dot.style.marginLeft = '-7px'
      dot.style.marginTop = '-7px'
      dot.style.background = 'rgba(185, 28, 28, 0.95)'
    })
    window.addEventListener('mouseup', () => {
      dot.style.width = '16px'
      dot.style.height = '16px'
      dot.style.marginLeft = '0px'
      dot.style.marginTop = '0px'
      dot.style.background = 'rgba(220, 38, 38, 0.9)'
    })
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, { once: true })
  } else {
    install()
  }
})

const page = await context.newPage()
page.on('pageerror', (error) => console.log('[pageerror]', String(error).slice(0, 300)))
page.on('response', (response) => {
  if (response.status() >= 500) console.log('[http 5xx]', response.status(), response.url())
})

/* ------------------------------------------------------------------ */
/* Overlays and helpers                                                */
/* ------------------------------------------------------------------ */

/** A fixed bottom banner with the narration line; removed when it elapses. */
async function caption(text, seconds = 4) {
  await page.evaluate((line) => {
    let bar = document.getElementById('__kadai_caption')
    if (!bar) {
      bar = document.createElement('div')
      bar.id = '__kadai_caption'
      Object.assign(bar.style, {
        position: 'fixed',
        left: '0',
        right: '0',
        bottom: '0',
        padding: '18px 44px 20px',
        background: 'rgba(9, 14, 30, 0.92)',
        color: '#ffffff',
        fontFamily: 'system-ui, -apple-system, Segoe UI, sans-serif',
        fontSize: '24px',
        lineHeight: '1.35',
        letterSpacing: '0.2px',
        textAlign: 'center',
        boxShadow: '0 -10px 30px rgba(0,0,0,0.35)',
        borderTop: '3px solid #2563eb',
        transition: 'opacity 220ms ease',
        pointerEvents: 'none',
        zIndex: '2147483646'
      })
      document.body.appendChild(bar)
    }
    bar.textContent = line
    bar.style.opacity = '1'
  }, text)
  await pause(seconds)
  await page
    .evaluate(() => {
      const bar = document.getElementById('__kadai_caption')
      if (bar) bar.style.opacity = '0'
    })
    .catch(() => {})
  await sleep(220)
}

/** Full-screen card used for the title and the closing frame. */
async function card({ kicker, title, subtitle, lines = [], seconds = 8 }) {
  await page.evaluate(
    ({ kicker, title, subtitle, lines }) => {
      document.getElementById('__kadai_card')?.remove()
      const wrap = document.createElement('div')
      wrap.id = '__kadai_card'
      Object.assign(wrap.style, {
        position: 'fixed',
        inset: '0',
        zIndex: '2147483644',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '60px 80px',
        background: 'linear-gradient(135deg, #0b1d3a 0%, #12306b 55%, #1d4ed8 100%)',
        color: '#ffffff',
        fontFamily: 'system-ui, -apple-system, Segoe UI, sans-serif',
        textAlign: 'center',
        gap: '18px'
      })
      const parts = []
      if (kicker) {
        const el = document.createElement('div')
        el.textContent = kicker
        Object.assign(el.style, {
          fontSize: '18px',
          letterSpacing: '4px',
          textTransform: 'uppercase',
          color: '#93c5fd'
        })
        parts.push(el)
      }
      const heading = document.createElement('div')
      heading.textContent = title
      Object.assign(heading.style, {
        fontSize: '64px',
        fontWeight: '700',
        lineHeight: '1.05',
        letterSpacing: '-1px'
      })
      parts.push(heading)
      if (subtitle) {
        const el = document.createElement('div')
        el.textContent = subtitle
        Object.assign(el.style, {
          fontSize: '28px',
          color: '#dbeafe',
          maxWidth: '900px',
          lineHeight: '1.35'
        })
        parts.push(el)
      }
      if (lines.length) {
        const list = document.createElement('div')
        Object.assign(list.style, {
          marginTop: '18px',
          display: 'grid',
          gap: '10px',
          fontSize: '22px',
          color: '#e2e8f0',
          textAlign: 'left'
        })
        for (const line of lines) {
          const row = document.createElement('div')
          row.textContent = line
          list.appendChild(row)
        }
        parts.push(list)
      }
      wrap.append(...parts)
      document.body.appendChild(wrap)
    },
    { kicker, title, subtitle, lines }
  )
  await pause(seconds)
}

async function closeCard() {
  await page.evaluate(() => document.getElementById('__kadai_card')?.remove())
  await sleep(300)
}

/** Smoothly bring an element into frame so the caption matches what is on screen. */
async function scrollTo(locator, block = 'center') {
  const target = locator.first()
  await target.waitFor({ state: 'visible', timeout: 20000 })
  await target.evaluate((el, where) => el.scrollIntoView({ block: where, behavior: 'smooth' }), block)
  await sleep(1100)
}

/**
 * Click a submit button and prove the request really went out.
 *
 * A swallowed click (overlay, re-render) used to leave a scene waiting on a
 * screen that could never arrive; this retries once and surfaces a 4xx body.
 */
async function clickExpecting(button, urlPart, { attempts = 2 } = {}) {
  let lastError = null
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const responsePromise = page
      .waitForResponse(
        (response) =>
          response.url().includes(urlPart) && response.request().method() === 'POST',
        { timeout: 20000 }
      )
      .catch(() => null)
    await button.click({ timeout: 20000 })
    const response = await responsePromise
    if (response && response.status() < 400) return response
    if (response) {
      const body = await response.text().catch(() => '')
      throw new Error(`${urlPart} answered ${response.status()}: ${body.slice(0, 200)}`)
    }
    lastError = new Error(`no POST to ${urlPart} after the click`)
    console.log(`    retrying click (${lastError.message})`)
    await sleep(1500)
  }
  throw lastError ?? new Error(`no POST to ${urlPart}`)
}

async function shot(name) {
  try {
    await page.screenshot({ path: path.join(SCREENS, `${name}.png`) })
  } catch (error) {
    console.log('[screenshot failed]', name, String(error).slice(0, 120))
  }
}

/** Type into a locator at human speed (and let React see every keystroke). */
async function typeInto(locator, text, delay = 70) {
  await locator.waitFor({ state: 'visible', timeout: 15000 })
  await locator.click()
  await locator.fill('')
  await locator.pressSequentially(text, { delay })
}

const navLink = (name) => page.locator('nav[aria-label="Primary"]').getByRole('link', { name })

async function bodyContains(text) {
  return page.evaluate((needle) => document.body.innerText.includes(needle), text)
}

/** The language switcher, found by its literal button labels (they never translate). */
async function languageGroup() {
  const englishButton = page.getByRole('button', { name: 'English', exact: true })
  const inHeader = page.locator('header [role="group"]').filter({ has: englishButton })
  if (await inHeader.count()) return inHeader.first()
  return page.locator('[role="group"]').filter({ has: englishButton }).first()
}

async function ensureEnglish() {
  const group = await languageGroup()
  const english = group.getByRole('button', { name: 'English', exact: true })
  if ((await english.count()) === 0) return
  if ((await english.first().getAttribute('aria-pressed')) !== 'true') {
    await english.first().click()
    await sleep(500)
  }
}

/** Sign Out is the last control in the sidebar; its label is translated. */
async function signOut() {
  await page.locator('aside').getByRole('button').last().click()
  await page.waitForURL(/\/login/, { timeout: 20000 })
  await sleep(400)
}

async function loginAs(username, landingCheck) {
  await ensureEnglish()
  await typeInto(page.getByLabel('Username'), username)
  await typeInto(page.getByLabel('Password'), username)
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.waitForURL(`${BASE}/`, { timeout: 25000 })
  await page.locator('aside').waitFor({ state: 'visible', timeout: 20000 })
  await landingCheck()
  await sleep(500)
}

/** Issue-form input for one BOM row, located by the row's own item name. */
async function issueQtyFor(itemName, value) {
  const inputs = page.locator('input[id^="issued-"]')
  const count = await inputs.count()
  for (let index = 0; index < count; index += 1) {
    const input = inputs.nth(index)
    const id = await input.getAttribute('id')
    const row = page.locator(`#${id}`).locator('xpath=ancestor::div[contains(@class,"p-4")][1]')
    const text = await row.innerText().catch(() => '')
    if (text.includes(itemName)) {
      await input.fill(value)
      return
    }
  }
  throw new Error(`no issue input for ${itemName}`)
}

async function showPdfOverlay(pngPath, label) {
  const base64 = (await readFile(pngPath)).toString('base64')
  await page.evaluate(
    ({ base64, label }) => {
      document.getElementById('__kadai_pdf')?.remove()
      const wrap = document.createElement('div')
      wrap.id = '__kadai_pdf'
      Object.assign(wrap.style, {
        position: 'fixed',
        inset: '0',
        zIndex: '2147483643',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '16px',
        padding: '28px 28px 110px',
        background: 'rgba(8, 12, 26, 0.94)'
      })
      const image = document.createElement('img')
      image.src = `data:image/png;base64,${base64}`
      Object.assign(image.style, {
        maxWidth: 'min(720px, 92vw)',
        maxHeight: '70vh',
        background: '#ffffff',
        boxShadow: '0 30px 70px rgba(0,0,0,0.55)'
      })
      const cap = document.createElement('div')
      cap.textContent = label
      Object.assign(cap.style, {
        color: '#cbd5e1',
        fontFamily: 'system-ui, sans-serif',
        fontSize: '18px'
      })
      wrap.append(image, cap)
      document.body.appendChild(wrap)
    },
    { base64, label }
  )
}

async function hidePdfOverlay() {
  await page.evaluate(() => document.getElementById('__kadai_pdf')?.remove())
  await sleep(250)
}

async function scene(id, title, optionsOrFn, maybeFn) {
  // Accept both scene(id, title, fn, {writes}) and scene(id, title, {writes}, fn).
  const fn = typeof optionsOrFn === 'function' ? optionsOrFn : maybeFn
  const { writes = false } = (typeof optionsOrFn === 'function' ? maybeFn : optionsOrFn) ?? {}
  const label = `${id} ${title}`
  const sceneStarted = Date.now()
  console.log(`\n=== ${label}${writes ? ' (writes data)' : ''}`)
  if (writes && DRY) {
    results.push({ id, title, status: 'skipped (dry run)' })
    console.log(`--- skipped in dry run`)
    return
  }
  try {
    await fn()
    results.push({ id, title, status: 'ok' })
  } catch (error) {
    const full = String(error?.message ?? error)
    const message = full.split('\n');
    const summary = message.slice(0, 3).join(' | ')
    results.push({ id, title, status: 'failed', error: summary })
    console.log(`!!! ${label} failed: ${summary}`)
    await shot(`fail-${id}`)
  }
  console.log(`    ${((Date.now() - sceneStarted) / 1000).toFixed(1)}s · total ${elapsed().toFixed(1)}s`)
}

/* ------------------------------------------------------------------ */
/* Scenes                                                              */
/* ------------------------------------------------------------------ */

await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.getByLabel('Username').waitFor({ timeout: 30000 })

await scene('01', 'title card', async () => {
  await card({
    kicker: 'NIT Tiruchirappalli · CDI internship prototype',
    title: 'Kadai — Order to Audit',
    subtitle: 'A South Indian snack factory traced from the salesman’s order to the stock ledger.',
    seconds: 9
  })
  await closeCard()
  await caption('One order. One invoice. Every packet accounted for.', 6)
  await caption('Two loops meet at finished-goods stock: sales and production.', 6)
  await shot('01-login')
})

await scene('02', 'salesman signs in', async () => {
  await caption('Salesman A signs in. Django session auth plus CSRF, one origin.', 6)
  await typeInto(page.getByLabel('Username'), 'salesman_a')
  await caption('Six roles: salesman, admin, production, accountant, owner — and per-org onboarding.', 4)
  await typeInto(page.getByLabel('Password'), 'salesman_a')
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.waitForURL(`${BASE}/`, { timeout: 25000 })
  await page.getByRole('heading', { name: 'My dashboard' }).waitFor({ timeout: 20000 })
  await sleep(600)
  await shot('02-salesman-dashboard')
})

await scene('03', 'salesman dashboard', async () => {
  await caption('Her own book only: open orders, approvals, invoices. The server scopes every query.', 8)
  await shot('03-salesman-tiles')
})

await scene('04', 'create an order', async () => {
  await navLink('New order').click()
  await page.getByRole('heading', { name: 'New order' }).waitFor({ timeout: 20000 })
  await caption('New order: pick the customer, then tap quantities on a phone-sized screen.', 7)
  await page.getByRole('button', { name: /Retailer A/ }).click()
  await page.getByText('Murukku 200 g').first().waitFor({ timeout: 20000 })
  await caption('Prices come from the customer’s price list; GST and HSN from the product.', 6)
  await typeInto(page.getByLabel('Murukku 200 g quantity'), '40', 220)
  await caption('Forty packets. The phone does no money arithmetic — the server prices and taxes it.', 6)
  if (DRY) {
    await shot('04-order-form')
    console.log('    [dry] order not submitted')
    return
  }
  await page.getByRole('button', { name: 'Submit order' }).click()
  const status = page.getByRole('status').first()
  await status.waitFor({ timeout: 20000 })
  const statusText = await status.innerText()
  const match = statusText.match(/ORD\/[0-9-]+\/\d+/)
  if (!match) throw new Error(`no order number in: ${statusText}`)
  globalThis.orderA = match[0]
  console.log('    order A:', globalThis.orderA)
  await caption('Submitted once per client UUID: a retry returns the same order, never a duplicate.', 6)
  await shot('04-order-submitted')
})

await scene('05', 'my orders', async () => {
  const viewOrders = page.getByRole('button', { name: 'View my orders' })
  if (await viewOrders.count()) await viewOrders.first().click()
  else await navLink('My orders').click()
  await page.getByRole('heading', { name: 'My orders' }).waitFor({ timeout: 20000 })
  await caption('The state machine is auditable: Submitted, Approved, Invoiced, Dispatched.', 7)
  await shot('05-my-orders')
})

await scene('06', 'offline order and sync', async () => {
  await context.setOffline(true)
  await navLink('New order').click()
  await page.getByRole('heading', { name: 'New order' }).waitFor({ timeout: 20000 })
  await page.getByText('You are offline').first().waitFor({ timeout: 20000 })
  await caption('Now the connection drops. The app keeps the last customer and price catalog.', 7)
  await page.getByRole('button', { name: /Retailer A/ }).click()
  await page.getByText('Murukku 200 g').first().waitFor({ timeout: 20000 })
  await caption('Catalog rows come from IndexedDB, with the price-list version they were fetched under.', 6)
  await typeInto(page.getByLabel('Murukku 200 g quantity'), '120', 200)
  if (DRY) {
    await shot('06-offline-form')
    await context.setOffline(false)
    console.log('    [dry] offline order not submitted')
    return
  }
  await page.getByRole('button', { name: 'Submit order' }).click()
  await page.getByText('Offline — the order is saved').first().waitFor({ timeout: 20000 })
  await page.getByText(/Pending \(1\)/).first().waitFor({ timeout: 20000 })
  await caption('Queued in the outbox under its own client UUID; the sidebar shows Pending (1).', 8)
  await shot('06-offline-queued')

  await context.setOffline(false)
  await caption('Back online: the outbox flushes on the browser event, or from Sync now.', 4)
  await page.getByText(/Pending \(\d+\)/).first().waitFor({ state: 'hidden', timeout: 30000 })
  await caption('Synced, and still exactly one order — the UUID is the idempotency key.', 5)
  await shot('06-offline-synced')

  await navLink('My orders').click()
  await page.getByRole('heading', { name: 'My orders' }).waitFor({ timeout: 20000 })
  const card = page.locator('li').filter({ hasText: '× 120.000' }).first()
  await card.waitFor({ timeout: 20000 })
  const cardText = await card.innerText()
  const match = cardText.match(/ORD\/[0-9-]+\/\d+/)
  if (match) globalThis.orderB = match[0]
  console.log('    order B:', globalThis.orderB)
  await caption('Both orders are on the server now, with no duplicates.', 6)
  await shot('06-my-orders-both')
})

await scene('07', 'Tamil UI', async () => {
  const group = page.locator('header [role="group"][aria-label="Language"]').first()
  await group.getByRole('button', { name: 'தமிழ்' }).click()
  await caption('Every screen is translated — here the salesman’s order book in Tamil.', 8)
  await shot('07-tamil-orders')
  // Nav labels are translated now; the route itself is not.
  await page.locator('a[href="/orders/new"]').first().click()
  await page.waitForURL(/\/orders\/new$/, { timeout: 15000 })
  await caption('Same flow, same numbers, Tamil copy — English and தமிழ் ship together.', 7)
  await shot('07-tamil-new-order')
  await ensureEnglish()
  await caption('The choice is remembered per device in localStorage.', 4)
  await shot('07-tamil-back-to-english')
})

await scene('08', 'admin approves the order', async () => {
  await signOut()
  await caption('Admin signs in: every salesman’s order lands in one inbox.', 3)
  await loginAs('admin', async () => {
    await page.getByText('Outstanding dues').first().waitFor({ timeout: 25000 })
  })
  await navLink('Order inbox').click()
  await page.getByRole('heading', { name: 'Order inbox' }).waitFor({ timeout: 20000 })
  await caption('Before approval: stock cover per line, price-list drift and a GST preview.', 6)
  if (!globalThis.orderA) {
    // Dry-run fallback: pick the newest submitted order in the list.
    const first = page.locator('main ul li button').first()
    await first.click()
  } else {
    await page.getByRole('button', { name: new RegExp(globalThis.orderA.replace(/\//g, '\\/')) }).click()
  }
  await page.getByText('If invoiced now:').first().waitFor({ timeout: 20000 })
  await page.getByText(/free|Short by/).first().waitFor({ timeout: 20000 })
  await caption('The preview is exactly what the invoice will say: taxable, CGST and SGST split.', 7)
  await shot('08-admin-inbox')
  if (DRY) {
    console.log('    [dry] order not approved')
    return
  }
  await clickExpecting(page.getByRole('button', { name: 'Approve order' }), '/approve/')
  // Approving removes the order from the Submitted filter, so reopen it under Approved.
  const approvedFilter = page.getByRole('button', { name: 'Approved', exact: true })
  await approvedFilter.waitFor({ timeout: 20000 })
  await approvedFilter.click()
  await page.getByRole('button', { name: new RegExp(globalThis.orderA.replace(/\//g, '\\/')) }).click()
  await page.getByRole('button', { name: 'Raise GST invoice' }).waitFor({ timeout: 20000 })
  await caption('Approved — and the audit log row was written in the same transaction.', 6)
  await shot('08-order-approved')
})

await scene('09', 'invoice, PDF and dispatch', { writes: true }, async () => {
  await clickExpecting(page.getByRole('button', { name: 'Raise GST invoice' }), '/invoice/')
  await page.waitForURL(/\/invoices\/\d+$/, { timeout: 25000 })
  await page.getByText(/^INV\//).first().waitFor({ timeout: 20000 })
  const invoiceNumber = (await page.getByRole('heading', { level: 2 }).first().innerText()).trim()
  globalThis.invoiceNumber = invoiceNumber
  const invoiceId = Number(page.url().match(/\/invoices\/(\d+)$/)[1])
  console.log('    invoice:', invoiceNumber, 'id', invoiceId)
  await caption('Intra-state supply: 5% GST split as CGST + SGST, rounded per line to paise.', 8)
  await shot('09-invoice')

  await caption('Open PDF — rendered server-side by WeasyPrint, not the browser.', 2)
  const response = await context.request.get(`${BASE}/api/sales/invoices/${invoiceId}/pdf/`)
  if (!response.ok()) throw new Error(`PDF request failed: ${response.status()}`)
  const pdfBuffer = await response.body()
  if (pdfBuffer.subarray(0, 4).toString() !== '%PDF') throw new Error('response is not a PDF')
  const pdfPath = path.join(ASSETS, 'invoice.pdf')
  await writeFile(pdfPath, pdfBuffer)
  const prefix = path.join(ASSETS, 'invoice-page')
  execFileSync('pdftoppm', ['-png', '-r', '120', '-f', '1', '-l', '1', pdfPath, prefix])
  const rendered = (await readdir(ASSETS))
    .filter((name) => /^invoice-page.*\.png$/.test(name))
    .sort()
  const pngPath = path.join(ASSETS, rendered[rendered.length - 1])
  await showPdfOverlay(pngPath, `Invoice ${invoiceNumber} · ${(pdfBuffer.length / 1024).toFixed(0)} KB PDF rendered from HTML`)
  await caption('GSTIN, HSN, place of supply and the tax split are all on the document.', 11)
  await shot('09-invoice-pdf')
  await hidePdfOverlay()

  await caption('Dispatch posts finished-goods ISSUE rows; it can never take stock below zero.', 6)
  await clickExpecting(page.getByRole('button', { name: 'Record dispatch' }), '/dispatch/')
  await page.getByText(/Dispatch #/).first().waitFor({ timeout: 25000 })
  await caption('Posted invoices are immutable — corrections are credit notes, never edits.', 6)
  await shot('09-invoice-dispatched')
})

await scene('10', 'record a payment', { writes: true }, async () => {
  if (!globalThis.invoiceNumber) throw new Error('no invoice was raised in scene 09')
  await navLink('Payments').click()
  await page.getByRole('heading', { name: 'Payments' }).waitFor({ timeout: 20000 })
  await page.getByLabel('Customer').selectOption({ label: 'Retailer A' })
  await page.getByText('Outstanding', { exact: true }).first().waitFor({ timeout: 20000 })
  await page.getByText(globalThis.invoiceNumber).first().waitFor({ timeout: 20000 })
  await caption('Money received is allocated to invoices, with ageing in 0–30, 31–60, 61–90 and 90+ buckets.', 7)
  await typeInto(page.getByLabel('Amount'), '1000', 150)
  await typeInto(page.getByLabel(`Allocation for ${globalThis.invoiceNumber}`), '1000', 120)
  await caption('An allocation can never exceed the invoice’s outstanding balance.', 5)
  await clickExpecting(page.getByRole('button', { name: 'Record payment' }), '/payments/payments/')
  await page.getByRole('status').first().waitFor({ timeout: 25000 })
  await caption('Outstanding drops immediately; the customer ledger keeps the trail.', 7)
  await shot('10-payment')
})

await scene('11', 'credit note', { writes: true }, async () => {
  if (!globalThis.invoiceNumber) throw new Error('no invoice was raised in scene 09')
  await navLink('Invoices').click()
  await page.getByRole('heading', { name: 'Invoices' }).waitFor({ timeout: 20000 })
  await page.getByRole('link', { name: new RegExp(globalThis.invoiceNumber.replace(/\//g, '\\/')) }).click()
  await page.getByText('Credit note', { exact: true }).first().waitFor({ timeout: 20000 })
  await caption('Posted invoices are immutable at the database level. A credit note is the only correction.', 8)
  await typeInto(page.getByLabel('Credit quantity for Murukku 200 g'), '5', 200)
  await typeInto(page.getByLabel('Reason'), '5 packets damaged in transit', 45)
  await caption('Credit five packets and return them to stock; the invoice itself is never edited.', 5)
  await clickExpecting(page.getByRole('button', { name: 'Issue credit note' }), '/credit-notes/')
  await page.getByText(/CN\/[0-9-]+\/\d+/).first().waitFor({ timeout: 25000 })
  await caption('The credit note credits the invoice and posts the restock receipt.', 7)
  await shot('11-credit-note')
})

await scene('12', 'loop closer: shortage to batches', async () => {
  await navLink('Order inbox').click()
  await page.getByRole('heading', { name: 'Order inbox' }).waitFor({ timeout: 20000 })
  const target = globalThis.orderB
  if (target) {
    await page.getByRole('button', { name: new RegExp(target.replace(/\//g, '\\/')) }).click()
  } else {
    await page.locator('main ul li button').first().click()
  }
  await page.getByText('If invoiced now:').first().waitFor({ timeout: 20000 })
  await page.getByText(/Short by/).first().waitFor({ timeout: 20000 })
  await page.getByText('Loop Closer').first().waitFor({ timeout: 20000 })
  await caption('The order is bigger than stock on hand: shortage → batches → purchase.', 8)
  await caption('Whole batches, the limiting input and a draft purchase list only when there is a real gap.', 7)
  await shot('12-loop-closer')
})

await scene('13', 'production plans a run', async () => {
  await signOut()
  await caption('Production signs in and lands straight on the run list.', 3)
  await loginAs('production', async () => {
    await page.getByRole('heading', { name: 'Production runs' }).waitFor({ timeout: 25000 })
  })
  const planForm = page.locator('form').filter({ hasText: 'Plan a production run' }).first()
  await planForm.waitFor({ timeout: 20000 })
  await caption('A draft run is planned from the current BOM version — one batch, 200 packets.', 7)
  await shot('13-production-plan')
  if (DRY) {
    console.log('    [dry] run not created')
    return
  }
  await page.getByRole('button', { name: 'Create draft run' }).click()
  await page.waitForURL(/\/production\/runs\/\d+$/, { timeout: 25000 })
  await page.getByText(/^Run #\d+/).first().waitFor({ timeout: 20000 })
  globalThis.runId = Number(page.url().match(/\/runs\/(\d+)$/)[1])
  console.log('    run id:', globalThis.runId)
  await caption('The BOM version and its standard rates are snapshotted on the run.', 6)
})

await scene('14', 'issue materials', { writes: true }, async () => {
  await page.getByRole('heading', { name: 'Issue materials' }).waitFor({ timeout: 20000 })
  await caption('Issue what actually left the store — not always the plan.', 5)
  await caption('Pouches and cartons stay at zero here: packaging is consumed at packing.', 5)
  await issueQtyFor('Cooking oil', '10.5')
  await page.getByText('+5.0%').first().waitFor({ timeout: 15000 })
  await caption('10.5 litres against a plan of 10: the live chip shows +5.0%, beyond the 3% tolerance.', 8)
  await shot('14-issue-oil')
  await clickExpecting(page.getByRole('button', { name: 'Issue materials' }), '/issue/')
  await page.getByRole('heading', { name: 'Complete run' }).waitFor({ timeout: 25000 })
  await caption('Issuing posts one ISSUE ledger row per raw material, under a stock row lock.', 6)
})

await scene('15', 'complete the run and variance', { writes: true }, async () => {
  await typeInto(page.getByLabel('Good packets'), '188', 150)
  await caption('188 good packets from a plan of 200: −6%, adverse, flagged.', 5)
  await typeInto(page.getByLabel('Damaged pouches'), '6', 150)
  await typeInto(page.getByLabel('Cartons used'), '9', 150)
  await caption('Pouches 194 vs 200 is −3%, which is exactly at tolerance and not flagged.', 7)
  await clickExpecting(page.getByRole('button', { name: 'Complete run' }), '/complete/')
  await page.getByRole('heading', { name: 'Variance', exact: true }).waitFor({ timeout: 25000 })
  await caption('Variance is computed once and stored as a snapshot; later BOM edits never rewrite it.', 8)
  await shot('15-variance')
})

await scene('16', 'cost sheet and Leakage Radar', { writes: true }, async () => {
  await page.getByRole('heading', { name: 'Cost sheet' }).scrollIntoViewIfNeeded()
  await caption('Labour ₹1,200 and gas/power ₹600 go onto this run.', 4)
  await typeInto(page.getByLabel('Amount'), '1200', 120)
  await typeInto(page.getByLabel('Description'), 'Packers wages', 60)
  await clickExpecting(page.getByRole('button', { name: 'Add overhead' }), '/overheads/')
  await page.waitForTimeout(1500)
  await page.getByLabel('Category').selectOption('power')
  await typeInto(page.getByLabel('Amount'), '600', 120)
  await typeInto(page.getByLabel('Description'), 'Gas and power', 60)
  await clickExpecting(page.getByRole('button', { name: 'Add overhead' }), '/overheads/')
  await page.getByText('1,800.00').first().waitFor({ timeout: 25000 })

  // Read the real numbers from the API so the narration can never disagree
  // with the screen (a restock changes the weighted average).
  const money = (value) =>
    Number(value).toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })
  if (!globalThis.runId) throw new Error('run id unknown')
  let cost = null
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const response = await context.request.get(`${BASE}/api/costing/runs/${globalThis.runId}/`)
    cost = await response.json()
    if (Number(cost.overhead_value) === 1800) break
    await sleep(700)
  }
  const cardResponse = await context.request.get(
    `${BASE}/api/production/runs/${globalThis.runId}/report-card/`
  )
  const card = await cardResponse.json()
  console.log(
    `    cost: materials ${cost.materials_value}, overheads ${cost.overhead_value}, total ${cost.total_cost}, per packet ${cost.cost_per_packet}`
  )

  // The report card panel does not refetch when an overhead is added, so the
  // run page is reloaded once to show the bridge with its overhead step.
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: 'Cost sheet' }).waitFor({ timeout: 30000 })
  await page.getByText('1,800.00').first().waitFor({ timeout: 30000 })
  await sleep(900)

  await scrollTo(page.getByText('Cost per good packet', { exact: true }), 'center')
  await caption(
    `Materials ${money(cost.materials_value)} + overheads ${money(cost.overhead_value)} = ${money(cost.total_cost)} over ${Number(cost.good_packets)} packets, so ${money(cost.cost_per_packet)} per good packet.`,
    9
  )
  await shot('16-cost-sheet')
  await scrollTo(page.getByRole('heading', { name: 'Leakage Radar report card' }), 'start')
  await page.getByText('Cost per packet bridge').first().waitFor({ timeout: 25000 })
  await caption(
    `Leakage Radar: standard ${money(card.standard_materials)} against actual ${money(card.actual_materials)} — price ${money(card.price_impact)}, usage ${money(card.usage_impact)}.`,
    8
  )
  await shot('16-leakage-radar')
  await scrollTo(page.getByText('Cost per packet bridge', { exact: true }), 'center')
  const [base, yieldStep, usageStep, overheadStep] = card.bridge
  await caption(
    `The bridge: ${money(base.amount)} standard, plus ${money(yieldStep.amount)} yield, ${money(usageStep.amount)} price and usage, ${money(overheadStep.amount)} overhead = ${money(card.cost_per_packet)}.`,
    8
  )
  await shot('16-leakage-bridge')
})

await scene('17', 'accountant: reports, exports, reconciliation', async () => {
  await signOut()
  await caption('Accountant: read-only across money and stock.', 3)
  await loginAs('accountant', async () => {
    await page.getByText('Outstanding dues').first().waitFor({ timeout: 25000 })
  })
  await caption('The dashboard flags reorder lines, variance alerts and leakage this month.', 6)
  await shot('17-accountant-dashboard')
  await navLink('Reports').click()
  await page.getByRole('heading', { name: 'Sales register' }).waitFor({ timeout: 25000 })
  await caption('Ten reports, all filtered on the business date — not the server clock.', 7)
  const csv = await Promise.all([
    page.waitForEvent('download', { timeout: 25000 }),
    page.getByRole('link', { name: 'CSV', exact: true }).click()
  ])
  await csv[0].saveAs(path.join(ASSETS, 'sales-register.csv'))
  const csvStat = await stat(path.join(ASSETS, 'sales-register.csv'))
  const excel = await Promise.all([
    page.waitForEvent('download', { timeout: 25000 }),
    page.getByRole('link', { name: 'Excel', exact: true }).click()
  ])
  await excel[0].saveAs(path.join(ASSETS, 'sales-register.xlsx'))
  const excelStat = await stat(path.join(ASSETS, 'sales-register.xlsx'))
  console.log(`    exports: csv ${csvStat.size}B, xlsx ${excelStat.size}B`)
  await caption('CSV and Excel come from the same rows the screen shows — plus a PDF of the same report.', 7)
  await shot('17-reports-exports')
  await page.getByRole('heading', { name: 'Reconciliation' }).scrollIntoViewIfNeeded()
  await page.getByText('stock balance equals ledger sum').first().waitFor({ timeout: 20000 })
  await caption('Three audit checks: stock = ledger, invoice totals = lines, register = GST summary.', 8)
  await shot('17-reconciliation')
})

await scene('18', 'owner: the audit view', async () => {
  await signOut()
  await caption('Owner: the whole business in one screen.', 3)
  await loginAs('owner', async () => {
    await page.getByText('Leakage this month').first().waitFor({ timeout: 25000 })
  })
  await caption('Leakage counts adverse money only: price, usage and the standard cost of missing packets.', 8)
  await shot('18-owner-dashboard')
  await caption('Stock cover, variance alerts and reorder lines are the same numbers the floor uses.', 7)
  await caption('Append-only ledger and immutable invoices are PostgreSQL triggers, not UI promises.', 8)
  await caption('`make benchmark` replays Appendix A through these same services in a rolled-back transaction.', 8)
  await shot('18-owner-audit')
})

await scene('19', 'closing card', async () => {
  await card({
    kicker: 'Kadai',
    title: 'Order → audit, end to end',
    subtitle: 'Django 5 · React + TypeScript · PostgreSQL 16 · Docker Compose · AWS',
    lines: [
      'Salesman — orders and offline outbox',
      'Admin — approval, GST invoice, dispatch, payments',
      'Production — BOM, runs, variance, Leakage Radar',
      'Accountant — read-only reports and reconciliation',
      'Owner — dashboard, audit trail, benchmark harness',
      'Benchmark — Appendix A replayed through the same services',
    ],
    seconds: 16
  })
  await shot('19-closing')
})

/* ------------------------------------------------------------------ */
/* Finish                                                              */
/* ------------------------------------------------------------------ */
await page.close()
const rawVideo = await page.video().path()
await context.close()
await browser.close()

const finalVideo = path.join(VIDEOS, 'kadai-demo.webm')
await rm(finalVideo, { force: true })
await rename(rawVideo, finalVideo)

const probe = execFileSync('ffprobe', [
  '-v',
  'error',
  '-show_entries',
  'format=duration',
  '-of',
  'default=noprint_wrappers=1:nokey=1',
  finalVideo
])
  .toString()
  .trim()
const minutes = Math.floor(Number(probe) / 60)
const seconds = Math.round(Number(probe) % 60)

console.log('\n================ SUMMARY ================')
for (const row of results) {
  const detail = row.error ? ` — ${row.error}` : ''
  console.log(`${row.id}  ${row.status.padEnd(16)} ${row.title}${detail}`)
}
console.log(`recording clock: ${elapsed().toFixed(1)}s`)
console.log(`video: ${finalVideo} (${minutes}m ${seconds}s)`)

if (process.env.SKIP_ENCODE !== '1') {
  const mp4 = path.join(DEMO, 'kadai-demo.mp4')
  execFileSync(
    'ffmpeg',
    [
      '-y',
      '-i',
      finalVideo,
      '-vf',
      'scale=1280:720:flags=lanczos,format=yuv420p',
      '-c:v',
      'libx264',
      '-preset',
      'veryfast',
      '-crf',
      '23',
      '-movflags',
      '+faststart',
      mp4
    ],
    { stdio: 'inherit' }
  )
  const mp4Probe = execFileSync('ffprobe', [
    '-v',
    'error',
    '-show_entries',
    'format=duration,size',
    '-of',
    'default=noprint_wrappers=1',
    mp4
  ])
    .toString()
    .trim()
  console.log(`mp4: ${mp4}\n${mp4Probe}`)
}
