"""
Username enumerator - checks for username existence across platforms.
Provides resilient, production-oriented probing with retries and classification.
"""

import time
import os
import json
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError


@dataclass
class PlatformCheck:
    """Result of a single platform check."""
    platform: str
    url: str
    exists: bool
    confidence: str
    status: str = 'Not Found'
    http_status: int = 0
    response_time_ms: float = 0.0
    detection_method: str = 'unknown'
    error: str = ''


# Platform configurations: name -> (base_url, variant_friendly, notes)
PLATFORMS = {
    'GitHub': {
        'url': 'https://github.com/{}',
        'variant_friendly': True,
        'description': 'Code repository hosting'
    },
    'X': {
        'url': 'https://x.com/{}',
        'variant_friendly': True,
        'description': 'Social media'
    },
    'Reddit': {
        'url': 'https://reddit.com/user/{}',
        'variant_friendly': True,
        'description': 'Community forum'
    },
    'Instagram': {
        'url': 'https://instagram.com/{}',
        'variant_friendly': True,
        'description': 'Photo sharing'
    },
    'Telegram': {
        'url': 'https://t.me/{}',
        'variant_friendly': True,
        'description': 'Messaging platform'
    },
    'LinkedIn': {
        'url': 'https://linkedin.com/in/{}',
        'variant_friendly': False,
        'description': 'Professional network'
    },
    'Facebook': {
        'url': 'https://facebook.com/{}',
        'variant_friendly': True,
        'description': 'Social media'
    },
    'HackerNews': {
        'url': 'https://news.ycombinator.com/user?id={}',
        'variant_friendly': True,
        'description': 'Tech news'
    },
}

DEFAULT_PLATFORM_SIGNATURES = {
    'GitHub': {
        'conservative_200': False,
        'not_found_markers': ['not found'],
        'found_markers': ['repositories', 'followers', 'following']
    },
    'X': {
        'conservative_200': True,
        'not_found_markers': [
            "this account doesn't exist",
            'try searching for another'
        ],
        'found_markers': []
    },
    'Reddit': {
        'conservative_200': False,
        'not_found_markers': ['sorry, nobody on reddit goes by that name', 'page not found'],
        'found_markers': ['karma', 'cake day']
    },
    'Instagram': {
        'conservative_200': True,
        'not_found_markers': ["sorry, this page isn't available", "page isn't available"],
        'found_markers': ['profile', 'followers', 'following']
    },
    'Telegram': {
        'conservative_200': True,
        'not_found_markers': [],
        'found_markers': ['if you have telegram']
    },
    'LinkedIn': {
        'conservative_200': True,
        'not_found_markers': ['profile not found', "this page doesn't exist"],
        'found_markers': []
    },
    'Facebook': {
        'conservative_200': True,
        'not_found_markers': ["this content isn't available", 'page not found'],
        'found_markers': []
    },
    'HackerNews': {
        'conservative_200': False,
        'not_found_markers': ['no such user'],
        'found_markers': ['created:']
    }
}

REQUEST_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9'
}

REQUEST_TIMEOUT_SECONDS = 8
MAX_RETRIES = 2
BACKOFF_SECONDS = 0.35
CACHE_TTL_SECONDS = 300
RESPONSE_PREVIEW_BYTES = 900000
TEMPLATE_COMPARE_WINDOW = 10000

# Platforms that require browser rendering/session context for reliable detection.
# In backend-only mode, mark as Unsupported instead of returning low-confidence guesses.
BROWSER_REQUIRED_PLATFORMS = {'X', 'Instagram', 'LinkedIn', 'Facebook'}

_RESULT_CACHE: Dict[Tuple[str, str], Tuple[float, PlatformCheck]] = {}
_PROXY_OPENER = None


def _is_hybrid_probe_enabled() -> bool:
    """Return whether hybrid node probe integration is enabled (default: enabled)."""
    raw_value = os.environ.get('OSINT_ENABLE_HYBRID_PROBES', 'true').strip().lower()
    return raw_value in {'1', 'true', 'yes', 'on'}


def _get_hybrid_probe_url() -> str:
    """Return hybrid probe endpoint URL."""
    return os.environ.get('OSINT_HYBRID_PROBE_URL', 'http://127.0.0.1:8787/render').strip()


def _get_hybrid_deterministic_probe_url() -> str:
    """Return deterministic hybrid probe endpoint URL."""
    raw = _get_hybrid_probe_url()
    if raw.endswith('/render'):
        return raw[:-7] + '/probe'
    return raw.rstrip('/') + '/probe'


def _load_platform_signatures() -> Dict[str, Dict[str, object]]:
    """Load signature definitions from JSON; fall back to defaults on any error."""
    signature_path = Path(__file__).resolve().parent / 'platform_signatures.json'
    if not signature_path.exists():
        return DEFAULT_PLATFORM_SIGNATURES

    try:
        with signature_path.open('r', encoding='utf-8') as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict) and loaded:
            return loaded
    except Exception:
        pass
    return DEFAULT_PLATFORM_SIGNATURES


PLATFORM_SIGNATURES = _load_platform_signatures()


def _get_platform_signature(platform: str) -> Dict[str, object]:
    """Return merged signature for a platform with safe defaults."""
    fallback = {
        'conservative_200': False,
        'not_found_markers': [],
        'found_markers': []
    }
    loaded = PLATFORM_SIGNATURES.get(platform, {})
    if not isinstance(loaded, dict):
        return fallback

    signature = {**fallback, **loaded}
    for key in ('not_found_markers', 'found_markers'):
        values = signature.get(key, [])
        if not isinstance(values, list):
            signature[key] = []
        else:
            signature[key] = [str(marker) for marker in values if str(marker).strip()]
    signature['conservative_200'] = bool(signature.get('conservative_200', False))
    return signature


def generate_username_variants(username: str) -> Dict[str, List[str]]:
    """
    Generate username variants for enumeration.
    
    Variants include:
    - Original
    - With numeric suffixes (01, 123, etc.)
    - With underscores instead of dots
    - Dev variants (username_dev, dev_username)
    - Alternative formats
    
    Args:
        username: Original username
        
    Returns:
        Dictionary with 'variants' and 'original' keys
    """
    variants = [username]
    original = username
    
    # Numeric suffixes
    variants.extend([
        f"{username}01",
        f"{username}123",
        f"{username}_",
        f"_{username}",
    ])
    
    # Dev variants
    if not username.endswith('dev'):
        variants.extend([
            f"{username}_dev",
            f"dev_{username}",
            f"{username}1",
            f"{username}2023",
        ])
    
    # Replace special characters
    if '.' in username:
        underscore_variant = username.replace('.', '_')
        variants.append(underscore_variant)
        variants.extend([
            f"{underscore_variant}_dev",
            f"{underscore_variant}01",
        ])
    
    # Remove duplicates and sort by likelihood (original first)
    variants = list(dict.fromkeys(variants))  # Remove duplicates while preserving order
    
    return {
        'original': original,
        'variants': variants[:15],  # Limit to top 15 variants
        'variant_count': len(variants)
    }


def _decode_response_bytes(raw_bytes: bytes) -> str:
    """Decode response bytes safely for marker-based checks."""
    try:
        text = raw_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return ''
    return text.replace('’', "'").lower()


def _normalize_page_text(page_text: str) -> str:
    """Normalize page text for robust fingerprint-style comparisons."""
    if not page_text:
        return ''
    return ' '.join(page_text.split())


def _looks_like_same_page(target_text: str, control_text: str) -> bool:
    """Return True when two responses look like the same generic page template."""
    normalized_target = _normalize_page_text(target_text)
    normalized_control = _normalize_page_text(control_text)

    if not normalized_target or not normalized_control:
        return False

    if normalized_target == normalized_control:
        return True

    target_len = len(normalized_target)
    control_len = len(normalized_control)
    max_len = max(target_len, control_len)
    if max_len > 0:
        divergence = abs(target_len - control_len) / max_len
        if divergence >= 0.12:
            return False

    probe_window = TEMPLATE_COMPARE_WINDOW
    target_window = normalized_target[:probe_window]
    control_window = normalized_control[:probe_window]

    min_len = min(len(target_window), len(control_window))
    if min_len < 120:
        return False

    equal_chars = sum(1 for left, right in zip(target_window, control_window) if left == right)
    similarity_ratio = equal_chars / min_len
    return similarity_ratio >= 0.93


def _get_cached_result(platform: str, username: str) -> Optional[PlatformCheck]:
    """Return cached result if within TTL."""
    key = (platform, username)
    entry = _RESULT_CACHE.get(key)
    if not entry:
        return None

    cached_at, cached_result = entry
    if (time.time() - cached_at) > CACHE_TTL_SECONDS:
        _RESULT_CACHE.pop(key, None)
        return None
    return replace(cached_result, detection_method='cache')


def _set_cached_result(platform: str, username: str, result: PlatformCheck) -> None:
    """Store result in cache with timestamp."""
    _RESULT_CACHE[(platform, username)] = (time.time(), result)


def _get_proxy_configuration() -> Dict[str, str]:
    """Build proxy settings from environment variables."""
    if os.environ.get('OSINT_DISABLE_PROXY', '').strip().lower() in {'1', 'true', 'yes'}:
        return {}

    http_proxy = os.environ.get('OSINT_HTTP_PROXY') or os.environ.get('HTTP_PROXY', '')
    https_proxy = os.environ.get('OSINT_HTTPS_PROXY') or os.environ.get('HTTPS_PROXY', '')

    proxies: Dict[str, str] = {}
    if http_proxy:
        proxies['http'] = http_proxy
    if https_proxy:
        proxies['https'] = https_proxy
    return proxies


def _get_transport_opener():
    """Return a reusable opener with proxy support when configured."""
    global _PROXY_OPENER
    if _PROXY_OPENER is not None:
        return _PROXY_OPENER

    proxies = _get_proxy_configuration()
    if proxies:
        _PROXY_OPENER = build_opener(ProxyHandler(proxies))
    else:
        _PROXY_OPENER = build_opener()
    return _PROXY_OPENER


def _is_browser_probe_enabled() -> bool:
    """Return whether browser probes are enabled (default: enabled)."""
    raw_value = os.environ.get('OSINT_ENABLE_BROWSER_PROBES', 'true').strip().lower()
    return raw_value in {'1', 'true', 'yes', 'on'}


def _browser_probe_once(url: str) -> Tuple[int, str, str]:
    """Probe a URL with a real headless browser for JS-rendered platforms."""
    if _is_hybrid_probe_enabled():
        hybrid_url = _get_hybrid_probe_url()
        if hybrid_url:
            try:
                payload = json.dumps({'url': url}).encode('utf-8')
                request = Request(
                    hybrid_url,
                    data=payload,
                    headers={
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'User-Agent': REQUEST_HEADERS['User-Agent'],
                    },
                    method='POST'
                )
                opener = _get_transport_opener()
                with opener.open(request, timeout=max(REQUEST_TIMEOUT_SECONDS, 12)) as response:
                    status_code = getattr(response, 'status', 200)
                    body = response.read().decode('utf-8', errors='ignore')
                    parsed = json.loads(body or '{}')
                    rendered_status = int(parsed.get('status', 0) or 0)
                    rendered_content = str(parsed.get('content', '') or '').lower()
                    if rendered_status > 0:
                        return rendered_status, rendered_content, ''
                    return status_code, rendered_content, ''
            except Exception:
                pass

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return 0, '', 'browser_engine_unavailable'

    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=REQUEST_HEADERS['User-Agent'],
                locale='en-US',
            )
            page = context.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(1200)
            content = page.content().lower()
            status_code = response.status if response is not None else 0
            return status_code, content, ''
    except Exception as error:
        return 0, '', str(error)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def _hybrid_deterministic_platform_check(username: str, platform: str, profile_url: str, is_variant: bool = False) -> Optional[PlatformCheck]:
    """Use hybrid service deterministic verdict endpoint when available."""
    if not _is_hybrid_probe_enabled():
        return None

    endpoint = _get_hybrid_deterministic_probe_url()
    payload = json.dumps({
        'url': profile_url,
        'platform': platform,
        'username': username,
    }).encode('utf-8')

    try:
        request = Request(
            endpoint,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': REQUEST_HEADERS['User-Agent'],
            },
            method='POST'
        )
        opener = _get_transport_opener()
        with opener.open(request, timeout=max(REQUEST_TIMEOUT_SECONDS, 20)) as response:
            body = response.read().decode('utf-8', errors='ignore')
            parsed = json.loads(body or '{}')
            verdict = parsed.get('verdict', {}) if isinstance(parsed, dict) else {}
            if not isinstance(verdict, dict) or not verdict:
                return None

            status_label = str(verdict.get('status', 'Uncertain') or 'Uncertain')
            exists = bool(verdict.get('exists', False))
            confidence = str(verdict.get('confidence', 'Low') or 'Low')
            method = str(verdict.get('method', 'hybrid-deterministic') or 'hybrid-deterministic')
            error = str(verdict.get('error', '') or '')
            http_status = int(parsed.get('targetStatus', 0) or 0) if isinstance(parsed, dict) else 0

            return PlatformCheck(
                platform=platform,
                url=profile_url,
                exists=exists,
                confidence=confidence,
                status=status_label,
                http_status=http_status,
                response_time_ms=0.0,
                detection_method=method,
                error=error,
            )
    except Exception:
        return None


def _probe_once(url: str) -> Tuple[int, str, str]:
    """Probe URL once and return (status_code, decoded_body, error_string)."""
    request = Request(url, headers=REQUEST_HEADERS)
    opener = _get_transport_opener()

    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status_code = getattr(response, 'status', 200)
            body_preview = _decode_response_bytes(response.read(RESPONSE_PREVIEW_BYTES))
            return status_code, body_preview, ''
    except HTTPError as error:
        status_code = int(getattr(error, 'code', 0) or 0)
        body_preview = ''
        try:
            body_preview = _decode_response_bytes(error.read(RESPONSE_PREVIEW_BYTES))
        except Exception:
            body_preview = ''
        return status_code, body_preview, f'http_error_{status_code}'
    except (URLError, TimeoutError) as error:
        return 0, '', str(error)


def _contains_username_evidence(response_text: str, username: str) -> bool:
    """Return True when response body contains strong evidence of requested username."""
    if not response_text or not username:
        return False

    text = response_text.lower()
    username_lower = username.lower()

    candidates = {
        username_lower,
        username_lower.replace('_', ''),
        username_lower.replace('.', ''),
    }

    for candidate in candidates:
        candidate = candidate.strip()
        if len(candidate) >= 3 and candidate in text:
            return True
    return False


def _classify_response(platform: str, status_code: int, response_text: str, is_variant: bool, username: str = '') -> Tuple[bool, str, str, str]:
    """
    Classify platform response into: exists, status_label, confidence, method.
    """
    text = response_text or ''
    signature = _get_platform_signature(platform)
    conservative_200 = bool(signature.get('conservative_200', False))

    if status_code in (404, 410):
        return False, 'Not Found', 'Low', 'http-status'

    if status_code == 429:
        return False, 'Uncertain', 'Low', 'rate-limited'

    if status_code in (401, 403):
        if conservative_200:
            return False, 'Uncertain', 'Low', 'auth-gated'
        return True, 'Found', 'Medium', 'http-status'

    if status_code == 999:
        return False, 'Uncertain', 'Low', 'access-blocked'

    if 400 <= status_code < 500:
        return False, 'Uncertain', 'Low', 'client-block'

    if status_code >= 500:
        return False, 'Uncertain', 'Low', 'server-error'

    markers_not_found = [marker.replace('’', "'").lower() for marker in signature.get('not_found_markers', [])]
    for marker in markers_not_found:
        if marker and marker in text:
            if platform == 'Telegram' and status_code == 200:
                break
            return False, 'Not Found', 'Low', 'marker'

    markers_found = [marker.replace('’', "'").lower() for marker in signature.get('found_markers', [])]
    for marker in markers_found:
        if len(marker.strip()) < 3:
            continue
        if marker and marker in text:
            if conservative_200 and not _contains_username_evidence(text, username):
                continue
            confidence = 'High' if not is_variant else 'Medium'
            return True, 'Found', confidence, 'marker'

    if status_code == 200:
        if conservative_200:
            return False, 'Uncertain', 'Low', 'ambiguous-200'
        confidence = 'High' if not is_variant else 'Medium'
        return True, 'Found', confidence, 'http-status'

    return False, 'Uncertain', 'Low', 'fallback'


def _browser_platform_check(username: str, platform: str, base_url: str, is_variant: bool = False) -> Optional[PlatformCheck]:
    """Run Playwright-based probe for JS-gated platforms and classify with control comparison."""
    profile_url = base_url.format(username)

    deterministic = _hybrid_deterministic_platform_check(
        username=username,
        platform=platform,
        profile_url=profile_url,
        is_variant=is_variant,
    )
    if deterministic is not None:
        return deterministic

    status_code, body_preview, probe_error = _browser_probe_once(profile_url)

    if probe_error == 'browser_engine_unavailable':
        return PlatformCheck(
            platform=platform,
            url=profile_url,
            exists=False,
            confidence='Low',
            status='Unsupported',
            http_status=0,
            response_time_ms=0.0,
            detection_method='browser-unavailable',
            error='install_playwright_required'
        )

    if status_code == 0 and probe_error:
        return PlatformCheck(
            platform=platform,
            url=profile_url,
            exists=False,
            confidence='Low',
            status='Uncertain',
            http_status=0,
            response_time_ms=0.0,
            detection_method='browser-failure',
            error=probe_error
        )

    exists, status_label, confidence, method = _classify_response(
        platform=platform,
        status_code=status_code,
        response_text=body_preview,
        is_variant=is_variant,
        username=username,
    )

    control_username = f'osint_probe_{int(time.time() * 1000)}'
    control_url = base_url.format(control_username)
    control_status, control_body, _ = _browser_probe_once(control_url)

    if control_status == 200:
        same_template = _looks_like_same_page(body_preview, control_body)
        if exists and same_template:
            exists = False
            status_label = 'Uncertain'
            confidence = 'Low'
            method = 'browser-control-comparison'
        elif (not exists) and same_template and (not _contains_username_evidence(body_preview, username)):
            exists = False
            status_label = 'Not Found'
            confidence = 'Medium' if is_variant else 'High'
            method = 'browser-control-comparison-negative'
        elif (not exists) and (not same_template) and _contains_username_evidence(body_preview, username):
            exists = True
            status_label = 'Found'
            confidence = 'Medium' if is_variant else 'High'
            method = 'browser-control-comparison-positive'

    return PlatformCheck(
        platform=platform,
        url=profile_url,
        exists=exists,
        confidence=confidence,
        status=status_label,
        http_status=status_code,
        response_time_ms=0.0,
        detection_method=method if method.startswith('browser-') else f'browser-{method}',
        error=probe_error if probe_error.startswith('http_error_') else ''
    )


def real_platform_check(username: str, platform: str, is_variant: bool = False) -> PlatformCheck:
    """
    Perform real HTTP probing for username existence on a platform.

    Uses status codes and simple page markers to determine likely existence.
    """
    platform_config = PLATFORMS.get(platform, {})
    base_url = platform_config.get('url', '')
    profile_url = base_url.format(username)

    if platform in BROWSER_REQUIRED_PLATFORMS:
        if not _is_browser_probe_enabled():
            return PlatformCheck(
                platform=platform,
                url=profile_url,
                exists=False,
                confidence='Low',
                status='Unsupported',
                http_status=0,
                response_time_ms=0.0,
                detection_method='browser-required',
                error='browser_verification_required'
            )

        browser_result = _browser_platform_check(username, platform, base_url, is_variant=is_variant)
        if browser_result is not None:
            _set_cached_result(platform, username, browser_result)
            return browser_result

    cached = _get_cached_result(platform, username)
    if cached is not None:
        return cached

    start = time.perf_counter()
    last_error = ''
    last_status_code = 0

    for attempt in range(MAX_RETRIES + 1):
        status_code, body_preview, probe_error = _probe_once(profile_url)
        last_status_code = status_code or last_status_code

        if status_code == 0 and probe_error:
            last_error = probe_error
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))
                continue
            break

        exists, status_label, confidence, method = _classify_response(
            platform=platform,
            status_code=status_code,
            response_text=body_preview,
            is_variant=is_variant,
            username=username,
        )

        # Control-probe pass: compare target against a known fake username to
        # reduce false positives on generic pages (WhatsMyName-style hardening).
        signature = _get_platform_signature(platform)
        conservative_200 = bool(signature.get('conservative_200', False))
        should_control_probe = status_code == 200 and (exists or method == 'ambiguous-200') and conservative_200
        if should_control_probe:
            control_username = f'osint_probe_{int(time.time() * 1000)}'
            control_url = base_url.format(control_username)
            control_status, control_body, _ = _probe_once(control_url)

            if control_status == 200:
                same_template = _looks_like_same_page(body_preview, control_body)

                if exists:
                    if same_template:
                        exists = False
                        status_label = 'Uncertain'
                        confidence = 'Low'
                        method = 'control-comparison'
                else:
                    # For conservative platforms, allow a controlled positive only when
                    # target differs from control and includes explicit username evidence.
                    if (not same_template) and _contains_username_evidence(body_preview, username):
                        exists = True
                        status_label = 'Found'
                        confidence = 'Medium' if is_variant else 'High'
                        method = 'control-comparison-positive'

        # Retry transient classes only
        if status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
            continue

        result = PlatformCheck(
            platform=platform,
            url=profile_url,
            exists=exists,
            confidence=confidence,
            status=status_label,
            http_status=status_code,
            response_time_ms=round((time.perf_counter() - start) * 1000, 2),
            detection_method=method,
            error=probe_error if probe_error.startswith('http_error_') else ''
        )
        _set_cached_result(platform, username, result)
        return result

    result = PlatformCheck(
        platform=platform,
        url=profile_url,
        exists=False,
        confidence='Low',
        status='Uncertain',
        http_status=last_status_code,
        response_time_ms=round((time.perf_counter() - start) * 1000, 2),
        detection_method='network-failure',
        error=last_error or 'network_failure'
    )
    _set_cached_result(platform, username, result)
    return result


def check_username_across_platforms(
    username: str, 
    platforms_to_check: List[str] = None,
    check_variants: bool = True
) -> Dict:
    """
    Check username across multiple platforms.
    
    Args:
        username: Username to check
        platforms_to_check: List of platform names (None = all)
        check_variants: Whether to check variants as well
        
    Returns:
        Dictionary with results and metadata
    """
    if platforms_to_check is None:
        platforms_to_check = list(PLATFORMS.keys())
    
    # Generate variants metadata (kept for compatibility)
    variant_info = generate_username_variants(username)
    
    # Check original username
    results = {
        'original': [],
        'variants': [],
        'summary': {
            'total_checks': 0,
            'matches_found': 0,
            'variant_count': variant_info['variant_count'],
            'found_count': 0,
            'not_found_count': 0,
            'uncertain_count': 0,
            'unsupported_count': 0,
            'cache_hits': 0,
            'network_errors': 0,
            'avg_response_time_ms': 0.0,
            'proxy_enabled': bool(_get_proxy_configuration())
        }
    }
    
    # Check original across all platforms concurrently for speed
    with ThreadPoolExecutor(max_workers=min(8, len(platforms_to_check))) as executor:
        future_by_platform = {
            executor.submit(real_platform_check, username, platform, False): platform
            for platform in platforms_to_check
        }

        platform_result_map = {}
        for future in as_completed(future_by_platform):
            platform = future_by_platform[future]
            try:
                platform_result_map[platform] = future.result()
            except Exception as error:
                platform_result_map[platform] = PlatformCheck(
                    platform=platform,
                    url=PLATFORMS.get(platform, {}).get('url', '').format(username),
                    exists=False,
                    confidence='Low',
                    status='Uncertain',
                    http_status=0,
                    response_time_ms=0.0,
                    detection_method='internal-error',
                    error=f'internal_error:{type(error).__name__}'
                )

    for platform in platforms_to_check:
        result = platform_result_map[platform]
        results['original'].append({
            'platform': result.platform,
            'username': username,
            'url': result.url,
            'exists': result.exists,
            'confidence': result.confidence,
            'status': result.status,
            'http_status': result.http_status,
            'response_time_ms': result.response_time_ms,
            'detection_method': result.detection_method,
            'error': result.error
        })
        results['summary']['total_checks'] += 1
        if result.exists:
            results['summary']['matches_found'] += 1

        status = result.status
        if status == 'Found':
            results['summary']['found_count'] += 1
        elif status == 'Uncertain':
            results['summary']['uncertain_count'] += 1
        elif status == 'Unsupported':
            results['summary']['unsupported_count'] += 1
        else:
            results['summary']['not_found_count'] += 1

        if result.detection_method == 'cache':
            results['summary']['cache_hits'] += 1

        if result.error:
            results['summary']['network_errors'] += 1
    
    # Check variants (optional, limits to reduce noise)
    if check_variants:
        variant_limit = min(5, len(variant_info['variants']) - 1)  # Check up to 5 variants
        variant_targets = []
        for variant in variant_info['variants'][1:variant_limit + 1]:
            for platform in platforms_to_check[:3]:  # Check variants on top 3 platforms
                variant_targets.append((variant, platform))

        if variant_targets:
            with ThreadPoolExecutor(max_workers=min(8, len(variant_targets))) as executor:
                future_by_target = {
                    executor.submit(real_platform_check, variant, platform, True): (variant, platform)
                    for (variant, platform) in variant_targets
                }

                for future in as_completed(future_by_target):
                    variant, platform = future_by_target[future]
                    results['summary']['total_checks'] += 1
                    try:
                        result = future.result()
                    except Exception as error:
                        result = PlatformCheck(
                            platform=platform,
                            url=PLATFORMS.get(platform, {}).get('url', '').format(variant),
                            exists=False,
                            confidence='Low',
                            status='Uncertain',
                            http_status=0,
                            response_time_ms=0.0,
                            detection_method='internal-error',
                            error=f'internal_error:{type(error).__name__}'
                        )

                    if result.exists:  # Only include found variants for concise output
                        results['variants'].append({
                            'platform': result.platform,
                            'username': variant,
                            'url': result.url,
                            'exists': True,
                            'confidence': result.confidence
                        })
                        results['summary']['matches_found'] += 1

    response_times = [row.get('response_time_ms', 0.0) for row in results['original'] if row.get('response_time_ms', 0.0) > 0]
    if response_times:
        results['summary']['avg_response_time_ms'] = round(sum(response_times) / len(response_times), 2)
    
    return results
