const express = require('express');
const { chromium } = require('playwright');

const app = express();
app.use(express.json({ limit: '1mb' }));

const PORT = Number(process.env.HYBRID_PROBE_PORT || 8787);
const NAV_TIMEOUT_MS = Number(process.env.HYBRID_NAV_TIMEOUT_MS || 25000);
const RENDER_WAIT_MS = Number(process.env.HYBRID_RENDER_WAIT_MS || 1800);

function normalizeText(value) {
    return String(value || '').toLowerCase();
}

function extractPlatform(url) {
    try {
        const host = new URL(url).hostname.toLowerCase();
        if (host.includes('instagram.com')) return 'Instagram';
        if (host === 'x.com' || host.endsWith('.x.com')) return 'X';
        if (host.includes('linkedin.com')) return 'LinkedIn';
        if (host.includes('facebook.com')) return 'Facebook';
    } catch (_error) {
    }
    return '';
}

function evaluateDeterministicVerdict({ platform, username, targetContent, controlContent, targetStatus }) {
    const target = normalizeText(targetContent);
    const control = normalizeText(controlContent);
    const lowerUsername = normalizeText(username);

    if (platform === 'Instagram') {
        const targetHasProfileToken = target.includes('profilepage_');
        const controlHasProfileToken = control.includes('profilepage_');
        const targetHasUsername = lowerUsername.length > 2 && target.includes(lowerUsername);
        const controlHasUsername = lowerUsername.length > 2 && control.includes(lowerUsername);

        if (targetStatus === 404) {
            return { status: 'Not Found', exists: false, confidence: 'High', method: 'hybrid-http-status' };
        }

        if (targetHasProfileToken && !controlHasProfileToken) {
            return { status: 'Found', exists: true, confidence: 'High', method: 'hybrid-profile-token' };
        }

        if (!targetHasProfileToken && !controlHasProfileToken) {
            return { status: 'Not Found', exists: false, confidence: 'High', method: 'hybrid-profile-token' };
        }

        if (targetHasUsername && !controlHasUsername) {
            return { status: 'Found', exists: true, confidence: 'Medium', method: 'hybrid-username-evidence' };
        }

        return { status: 'Uncertain', exists: false, confidence: 'Low', method: 'hybrid-ambiguous' };
    }

    if (platform === 'X') {
        if (target.includes("this account doesn't exist") || target.includes('try searching for another')) {
            return { status: 'Not Found', exists: false, confidence: 'High', method: 'hybrid-not-found-marker' };
        }

        const mention = lowerUsername.length > 2 ? `@${lowerUsername}` : '';
        if (mention && target.includes(mention) && !control.includes(mention)) {
            return { status: 'Found', exists: true, confidence: 'Medium', method: 'hybrid-handle-evidence' };
        }

        return {
            status: 'Unsupported',
            exists: false,
            confidence: 'Low',
            method: 'hybrid-js-gated',
            error: 'browser_verification_non_deterministic'
        };
    }

    if (platform === 'LinkedIn' || platform === 'Facebook') {
        return {
            status: 'Unsupported',
            exists: false,
            confidence: 'Low',
            method: 'hybrid-access-gated',
            error: 'platform_blocks_automated_verification'
        };
    }

    return { status: 'Uncertain', exists: false, confidence: 'Low', method: 'hybrid-unknown-platform' };
}

async function renderWithBrowser(rawUrl) {
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
        const finalUrl = page.url();

        await context.close();

        return {
            status: response ? response.status() : 0,
            finalUrl,
            content
        };
    } finally {
        if (browser) {
            try {
                await browser.close();
            } catch (_error) {
            }
        }
    }
}

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

    try {
        const rendered = await renderWithBrowser(rawUrl);
        return res.json(rendered);
    } catch (error) {
        return res.status(502).json({
            error: 'probe_failed',
            message: String(error?.message || error)
        });
    }
});

app.post('/probe', async (req, res) => {
    const rawUrl = String(req.body?.url || '').trim();
    const username = String(req.body?.username || '').trim();
    const platformFromBody = String(req.body?.platform || '').trim();

    if (!rawUrl || !username) {
        return res.status(400).json({ error: 'missing_url_or_username' });
    }

    let parsed;
    try {
        parsed = new URL(rawUrl);
        if (!['http:', 'https:'].includes(parsed.protocol)) {
            return res.status(400).json({ error: 'invalid_protocol' });
        }
    } catch (_error) {
        return res.status(400).json({ error: 'invalid_url' });
    }

    const platform = platformFromBody || extractPlatform(rawUrl);
    const controlUsername = `osint_probe_${Date.now()}_nohit`;
    const controlUrl = rawUrl.replace(encodeURIComponent(username), encodeURIComponent(controlUsername)).replace(username, controlUsername);

    try {
        const target = await renderWithBrowser(rawUrl);
        const control = await renderWithBrowser(controlUrl);
        const verdict = evaluateDeterministicVerdict({
            platform,
            username,
            targetContent: target.content,
            controlContent: control.content,
            targetStatus: target.status
        });

        return res.json({
            platform,
            url: rawUrl,
            controlUrl,
            targetStatus: target.status,
            controlStatus: control.status,
            verdict
        });
    } catch (error) {
        return res.status(502).json({
            error: 'probe_failed',
            message: String(error?.message || error)
        });
    }
});

app.listen(PORT, () => {
    console.log(`Hybrid probe listening on :${PORT}`);
});
