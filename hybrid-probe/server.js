const express = require('express');
const { chromium } = require('playwright');

const app = express();
app.use(express.json({ limit: '1mb' }));

const PORT = Number(process.env.HYBRID_PROBE_PORT || 8787);
const NAV_TIMEOUT_MS = Number(process.env.HYBRID_NAV_TIMEOUT_MS || 25000);
const RENDER_WAIT_MS = Number(process.env.HYBRID_RENDER_WAIT_MS || 1800);

app.get('/health', (_req, res) => {
    res.json({ status: 'ok', service: 'hybrid-probe' });
});

app.post('/render', async (req, res) => {
    const rawUrl = String(req.body?.url || '').trim();
    if (!rawUrl) {
        return res.status(400).json({ error: 'missing_url' });
    }

    try {
        const parsed = new URL(rawUrl);
        if (!['http:', 'https:'].includes(parsed.protocol)) {
            return res.status(400).json({ error: 'invalid_protocol' });
        }
    } catch (_error) {
        return res.status(400).json({ error: 'invalid_url' });
    }

    let browser;
    try {
        browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const context = await browser.newContext({
            userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale: 'en-US'
        });

        const page = await context.newPage();
        const response = await page.goto(rawUrl, {
            waitUntil: 'domcontentloaded',
            timeout: NAV_TIMEOUT_MS
        });

        await page.waitForTimeout(RENDER_WAIT_MS);
        const content = (await page.content()) || '';

        await context.close();

        return res.json({
            status: response ? response.status() : 0,
            finalUrl: page.url(),
            content
        });
    } catch (error) {
        return res.status(502).json({
            error: 'probe_failed',
            message: String(error?.message || error)
        });
    } finally {
        if (browser) {
            try {
                await browser.close();
            } catch (_error) {
            }
        }
    }
});

app.listen(PORT, () => {
    console.log(`Hybrid probe listening on :${PORT}`);
});
