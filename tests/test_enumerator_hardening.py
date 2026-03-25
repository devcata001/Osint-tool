import unittest

from engine import enumerator


class EnumeratorHardeningTests(unittest.TestCase):
    def test_control_probe_detects_same_template(self):
        target = 'welcome to instagram sign up to see photos and videos from your friends'
        control = 'welcome to instagram sign up to see photos and videos from your friends'
        self.assertTrue(enumerator._looks_like_same_page(target, control))

    def test_control_probe_distinguishes_different_pages(self):
        target = 'profile page user details repositories followers following recent activity feed'
        control = 'error page page is not available sign up to continue generic template'
        self.assertFalse(enumerator._looks_like_same_page(target, control))

    def test_control_probe_distinguishes_length_divergence(self):
        target = 'a' * 2000
        control = 'a' * 1200
        self.assertFalse(enumerator._looks_like_same_page(target, control))

    def test_classify_instagram_ambiguous_200_as_uncertain(self):
        exists, status, confidence, method = enumerator._classify_response(
            platform='Instagram',
            status_code=200,
            response_text='sign up • instagram',
            is_variant=False,
        )
        self.assertFalse(exists)
        self.assertEqual(status, 'Uncertain')
        self.assertEqual(confidence, 'Low')
        self.assertEqual(method, 'ambiguous-200')

    def test_classify_github_200_as_found(self):
        exists, status, confidence, method = enumerator._classify_response(
            platform='GitHub',
            status_code=200,
            response_text='repositories followers following',
            is_variant=False,
        )
        self.assertTrue(exists)
        self.assertEqual(status, 'Found')
        self.assertIn(method, {'marker', 'http-status'})

    def test_classify_rate_limited_as_uncertain(self):
        exists, status, confidence, method = enumerator._classify_response(
            platform='X',
            status_code=429,
            response_text='',
            is_variant=False,
        )
        self.assertFalse(exists)
        self.assertEqual(status, 'Uncertain')
        self.assertEqual(confidence, 'Low')
        self.assertEqual(method, 'rate-limited')

    def test_classify_not_found_marker(self):
        response = "This account doesn't exist. Try searching for another."
        exists, status, confidence, method = enumerator._classify_response(
            platform='X',
            status_code=200,
            response_text=response.lower(),
            is_variant=False,
        )
        self.assertFalse(exists)
        self.assertEqual(status, 'Not Found')
        self.assertEqual(confidence, 'Low')
        self.assertEqual(method, 'marker')

    def test_summary_counts_found_not_found_uncertain(self):
        original_checker = enumerator.real_platform_check

        def fake_checker(username, platform, is_variant=False):
            if platform == 'GitHub':
                return enumerator.PlatformCheck(
                    platform=platform,
                    url=f'https://github.com/{username}',
                    exists=True,
                    confidence='High',
                    status='Found',
                    http_status=200,
                    response_time_ms=12.0,
                    detection_method='http-status',
                    error=''
                )
            if platform == 'X':
                return enumerator.PlatformCheck(
                    platform=platform,
                    url=f'https://x.com/{username}',
                    exists=False,
                    confidence='Low',
                    status='Uncertain',
                    http_status=429,
                    response_time_ms=30.0,
                    detection_method='rate-limited',
                    error='http_error_429'
                )
            return enumerator.PlatformCheck(
                platform=platform,
                url=f'https://reddit.com/user/{username}',
                exists=False,
                confidence='Low',
                status='Not Found',
                http_status=404,
                response_time_ms=20.0,
                detection_method='http-status',
                error=''
            )

        try:
            enumerator.real_platform_check = fake_checker
            results = enumerator.check_username_across_platforms(
                username='cat3lyst',
                platforms_to_check=['GitHub', 'X', 'Reddit'],
                check_variants=False,
            )
        finally:
            enumerator.real_platform_check = original_checker

        summary = results['summary']
        self.assertEqual(summary['total_checks'], 3)
        self.assertEqual(summary['matches_found'], 1)
        self.assertEqual(summary['found_count'], 1)
        self.assertEqual(summary['uncertain_count'], 1)
        self.assertEqual(summary['not_found_count'], 1)
        self.assertEqual(summary['network_errors'], 1)
        self.assertGreater(summary['avg_response_time_ms'], 0)


if __name__ == '__main__':
    unittest.main()
