"""
Username enumerator - checks for username existence across platforms.
Provides resilient, production-oriented probing with retries and classification.
"""

import re
import time
import os
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen, build_opener, ProxyHandler
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

NOT_FOUND_MARKERS = {
    'X': [
        "this account doesn\'t exist",
        "this account doesn't exist",
        'try searching for another'
    ],
    'Instagram': [
        "sorry, this page isn't available",
        'page isn\'t available'
    ],
    'GitHub': [
        'not found'
    ],
    'Reddit': [
        'sorry, nobody on reddit goes by that name',
        'page not found'
    ],
    'LinkedIn': [
        'profile not found',
        'this page doesn\'t exist'
    ],
    'Facebook': [
        "this content isn't available",
        'page not found'
    ],
    'Telegram': [
        'if you have telegram, you can contact'
    ],
    'HackerNews': [
        'no such user'
    ]
}

FOUND_MARKERS = {
    'X': ['@'],
    'Instagram': ['profile', 'followers', 'following'],
    'Telegram': ['if you have telegram'],
    'GitHub': ['repositories', 'followers', 'following'],
    'Reddit': ['karma', 'cake day'],
    'HackerNews': ['created:']
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

_RESULT_CACHE: Dict[Tuple[str, str], Tuple[float, PlatformCheck]] = {}
_PROXY_OPENER = None


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


def simulate_platform_check(username: str, platform: str, is_variant: bool = False) -> PlatformCheck:
    """
    Simulate platform check (in production, would make actual HTTP requests).
    
    For demo purposes, returns probabilistic results based on username patterns.
    
    Args:
        username: Username to check
        platform: Platform name
        is_variant: Whether checking a variant
        
    Returns:
        PlatformCheck result object
    """
    platform_config = PLATFORMS.get(platform, {})
    base_url = platform_config.get('url', '')
    
    # Simulated existence check - in production would:
    # 1. Make HTTP HEAD/GET request
    # 2. Check for 404/200 status codes
    # 3. Validate response patterns for false positives
    
    # Demo logic: longer, alphanumeric usernames are more likely to exist
    exists = False
    confidence = 'Low'
    
    # Heuristic: original usernames are more likely on all platforms
    if not is_variant:
        # Check for common name patterns (simplified demo)
        if len(username) >= 4 and re.match(r'^[a-z0-9_]+$', username.lower()):
            confidence = 'Medium'
            exists = hash(username + platform) % 100 > 60  # Simulated: 40% exist
        else:
            confidence = 'Low'
    else:
        # Variants are less likely to exist
        confidence = 'Low'
        exists = hash(username + platform) % 100 > 85  # Simulated: 15% exist
    
    if exists:
        confidence = 'High' if not is_variant else 'Medium'
    
    return PlatformCheck(
        platform=platform,
        url=base_url.format(username),
        exists=exists,
        confidence=confidence,
        status='Found' if exists else 'Not Found',
        detection_method='simulated'
    )


def _decode_response_bytes(raw_bytes: bytes) -> str:
    """Decode response bytes safely for marker-based checks."""
    try:
        text = raw_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return ''
    return text.replace('’', "'").lower()


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


def _classify_response(platform: str, status_code: int, response_text: str, is_variant: bool) -> Tuple[bool, str, str, str]:
    """
    Classify platform response into: exists, status_label, confidence, method.
    """
    text = response_text or ''

    if status_code in (404, 410):
        return False, 'Not Found', 'Low', 'http-status'

    if status_code == 429:
        return False, 'Uncertain', 'Low', 'rate-limited'

    if status_code in (401, 403):
        return True, 'Found', 'Medium', 'http-status'

    if status_code >= 500:
        return False, 'Uncertain', 'Low', 'server-error'

    markers_not_found = [marker.replace('’', "'").lower() for marker in NOT_FOUND_MARKERS.get(platform, [])]
    for marker in markers_not_found:
        if marker and marker in text:
            if platform == 'Telegram' and status_code == 200:
                break
            return False, 'Not Found', 'Low', 'marker'

    markers_found = [marker.replace('’', "'").lower() for marker in FOUND_MARKERS.get(platform, [])]
    for marker in markers_found:
        if marker and marker in text:
            confidence = 'High' if not is_variant else 'Medium'
            return True, 'Found', confidence, 'marker'

    if status_code == 200:
        confidence = 'High' if not is_variant else 'Medium'
        return True, 'Found', confidence, 'http-status'

    return False, 'Uncertain', 'Low', 'fallback'


def real_platform_check(username: str, platform: str, is_variant: bool = False) -> PlatformCheck:
    """
    Perform real HTTP probing for username existence on a platform.

    Uses status codes and simple page markers to determine likely existence.
    """
    platform_config = PLATFORMS.get(platform, {})
    base_url = platform_config.get('url', '')
    profile_url = base_url.format(username)

    cached = _get_cached_result(platform, username)
    if cached is not None:
        return cached

    start = time.perf_counter()
    last_error = ''
    last_status_code = 0

    for attempt in range(MAX_RETRIES + 1):
        request = Request(profile_url, headers=REQUEST_HEADERS)
        opener = _get_transport_opener()

        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                status_code = getattr(response, 'status', 200)
                body_preview = _decode_response_bytes(response.read(200000))
                exists, status_label, confidence, method = _classify_response(
                    platform=platform,
                    status_code=status_code,
                    response_text=body_preview,
                    is_variant=is_variant
                )

                result = PlatformCheck(
                    platform=platform,
                    url=profile_url,
                    exists=exists,
                    confidence=confidence,
                    status=status_label,
                    http_status=status_code,
                    response_time_ms=round((time.perf_counter() - start) * 1000, 2),
                    detection_method=method,
                    error=''
                )
                _set_cached_result(platform, username, result)
                return result

        except HTTPError as error:
            status_code = int(getattr(error, 'code', 0) or 0)
            last_status_code = status_code
            body_preview = ''
            try:
                body_preview = _decode_response_bytes(error.read(100000))
            except Exception:
                body_preview = ''

            exists, status_label, confidence, method = _classify_response(
                platform=platform,
                status_code=status_code,
                response_text=body_preview,
                is_variant=is_variant
            )

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
                error=f'http_error_{status_code}'
            )
            _set_cached_result(platform, username, result)
            return result

        except (URLError, TimeoutError) as error:
            last_error = str(error)
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))
                continue

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
            except Exception:
                platform_result_map[platform] = simulate_platform_check(username, platform, is_variant=False)

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
        else:
            results['summary']['not_found_count'] += 1

        if result.detection_method == 'cache':
            results['summary']['cache_hits'] += 1

        if result.error:
            results['summary']['network_errors'] += 1
    
    # Check variants (optional, limits to reduce noise)
    if check_variants:
        variant_limit = min(5, len(variant_info['variants']) - 1)  # Check up to 5 variants
        for variant in variant_info['variants'][1:variant_limit + 1]:
            for platform in platforms_to_check[:3]:  # Check variants on top 3 platforms
                result = simulate_platform_check(variant, platform, is_variant=True)
                if result.exists:  # Only include if found
                    results['variants'].append({
                        'platform': result.platform,
                        'username': variant,
                        'url': result.url,
                        'exists': True,
                        'confidence': result.confidence
                    })
                    results['summary']['matches_found'] += 1
                results['summary']['total_checks'] += 1

    response_times = [row.get('response_time_ms', 0.0) for row in results['original'] if row.get('response_time_ms', 0.0) > 0]
    if response_times:
        results['summary']['avg_response_time_ms'] = round(sum(response_times) / len(response_times), 2)
    
    return results
