"""
Result correlator - correlates and scores OSINT check results.
Combines multiple data sources and provides confidence assessments.
"""

from typing import Dict, List, Any
from datetime import datetime


def score_username_results(username_check: Dict) -> Dict:
    """
    Score and correlate username enumeration results.
    
    Args:
        username_check: Results from enumerator.check_username_across_platforms()
        
    Returns:
        Scored and annotated results
    """
    scored_results = {
        'results': [],
        'confidence_score': 0.0,
        'recommendations': [],
        'risk_summary': 'Low'
    }
    
    # Always include original platform checks for visibility
    for result in username_check.get('original', []):
        raw_status = result.get('status', 'Not Found')
        normalized_status = raw_status if raw_status in ('Found', 'Not Found', 'Uncertain', 'Unsupported') else 'Not Found'
        confidence_score = {
            'High': 0.95,
            'Medium': 0.70,
            'Low': 0.40
        }.get(result.get('confidence', 'Low'), 0.4)

        if normalized_status == 'Uncertain':
            confidence_score = min(confidence_score, 0.35)
        elif normalized_status == 'Unsupported':
            confidence_score = 0.1
        elif not result.get('exists', False):
            confidence_score = 0.2

        scored_results['results'].append({
            'platform': result['platform'],
            'username': result['username'],
            'url': result['url'],
            'exists': result.get('exists', False),
            'status': normalized_status,
            'confidence': result.get('confidence', 'Low'),
            'confidence_score': confidence_score,
            'is_variant': False,
            'annotation': (
                'Exact match' if normalized_status == 'Found'
                else 'Browser verification required' if normalized_status == 'Unsupported'
                else 'Uncertain check result' if normalized_status == 'Uncertain'
                else 'Not found'
            ),
            'http_status': result.get('http_status', 0),
            'response_time_ms': result.get('response_time_ms', 0.0),
            'detection_method': result.get('detection_method', ''),
            'error': result.get('error', '')
        })

    # Include only found variants to keep output concise
    for result in username_check.get('variants', []):
        if not result.get('exists', False):
            continue

        confidence_score = {
            'High': 0.95,
            'Medium': 0.70,
            'Low': 0.40
        }.get(result.get('confidence', 'Medium'), 0.5)

        scored_results['results'].append({
            'platform': result['platform'],
            'username': result['username'],
            'url': result['url'],
            'exists': True,
            'status': 'Found',
            'confidence': result['confidence'],
            'confidence_score': confidence_score,
            'is_variant': True,
            'annotation': 'Likely match'
        })
    
    # Aggregate confidence
    found_results = [row for row in scored_results['results'] if row.get('exists', False)]
    if scored_results['results']:
        avg_confidence = sum(r['confidence_score'] for r in scored_results['results']) / len(scored_results['results'])
        scored_results['confidence_score'] = round(avg_confidence, 2)
        
        # Risk assessment based on matches found
        matches_count = len(found_results)
        if matches_count >= 4:
            scored_results['risk_summary'] = 'High - Multiple accounts found'
        elif matches_count >= 2:
            scored_results['risk_summary'] = 'Medium - Account presence across platforms'
        elif matches_count == 1:
            scored_results['risk_summary'] = 'Low - Single account found'
        else:
            scored_results['risk_summary'] = 'Low - No confirmed account matches'
    else:
        scored_results['risk_summary'] = 'None - No accounts found'
    
    # Generate recommendations
    uncertain_results = [row for row in scored_results['results'] if row.get('status') == 'Uncertain']
    unsupported_results = [row for row in scored_results['results'] if row.get('status') == 'Unsupported']
    if found_results:
        scored_results['recommendations'] = [
            'Account found on multiple platforms',
            'Verify you own these accounts',
            'Check OAuth/SSO connections between accounts'
        ]
        if uncertain_results:
            scored_results['recommendations'].append('Some platforms were uncertain due to transient/network/rate-limit conditions; retry for confirmation')
        if unsupported_results:
            scored_results['recommendations'].append('Some platforms require browser-based verification; current backend mode does not claim a definitive result there')
    else:
        if uncertain_results or unsupported_results:
            scored_results['recommendations'] = [
                'No confirmed username matches yet',
                'Some checks were uncertain or unsupported in backend-only mode; use browser verification for final confirmation'
            ]
        else:
            scored_results['recommendations'] = [
                'Username not found on major platforms',
                'Consider checking additional services'
            ]
    
    return scored_results


def score_email_results(email_check: Dict) -> Dict:
    """
    Score and correlate email breach check results.
    
    Args:
        email_check: Results from breach_checker.check_email_breaches()
        
    Returns:
        Scored and annotated results
    """
    scored_results = {
        'results': [],
        'breach_count': email_check['breach_count'],
        'risk_level': email_check['risk_level'],
        'recommendations': [],
        'action_required': False
    }
    
    # Format breach results
    scored_results['results'] = email_check['breaches_found']
    
    # Determine action required
    if email_check['risk_level'] in ['Critical', 'High']:
        scored_results['action_required'] = True
        scored_results['recommendations'] = [
            'Change password immediately',
            'Check for unauthorized account access',
            'Consider enabling two-factor authentication',
            'Monitor credit/financial accounts closely'
        ]
    elif email_check['risk_level'] == 'Medium':
        scored_results['action_required'] = True
        scored_results['recommendations'] = [
            'Consider changing password',
            'Enable two-factor authentication if available',
            'Monitor account for suspicious activity'
        ]
    else:
        scored_results['recommendations'] = [
            'Email appears safe',
            'Good practice: enable two-factor authentication',
            'Review your password strength'
        ]
    
    return scored_results


def score_phone_results(phone_check: Dict) -> Dict:
    """
    Score phone number validation results.
    
    Args:
        phone_check: Results from phone validation
        
    Returns:
        Scored results
    """
    scored_results = {
        'results': [],
        'phone': phone_check.get('phone', ''),
        'valid_format': phone_check.get('is_valid', False),
        'risk_level': 'Unknown',
        'recommendations': []
    }
    
    if phone_check.get('is_valid', False):
        scored_results['results'].append({
            'check': 'Format validation',
            'result': 'Valid international format',
            'confidence': 'High'
        })
        
        if phone_check.get('appears_in_breaches', False):
            scored_results['risk_level'] = 'High'
            scored_results['recommendations'] = [
                'Phone number found in breach databases',
                'Disable SMS-based authentication if possible',
                'Use app-based 2FA instead'
            ]
        else:
            scored_results['risk_level'] = 'Low'
            scored_results['recommendations'] = [
                'Phone number format is valid',
                'No obvious breach appearance detected'
            ]
    else:
        scored_results['risk_level'] = 'Invalid'
        scored_results['recommendations'] = [
            'Phone number format is invalid',
            'Please enter a valid international phone number'
        ]
    
    return scored_results


def correlate_all_results(
    username_results: Dict = None,
    email_results: Dict = None,
    phone_results: Dict = None
) -> Dict:
    """
    Correlate all OSINT check results for comprehensive assessment.
    
    Args:
        username_results: Scored username results
        email_results: Scored email results
        phone_results: Scored phone results
        
    Returns:
        Correlated assessment
    """
    correlation = {
        'overall_risk': 'Low',
        'findings': [],
        'correlations': [],
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'total_matches': 0,
            'breaches_found': 0,
            'accounts_enumerated': 0
        }
    }
    
    risks = []
    
    # Process username results
    if username_results and username_results.get('results'):
        correlation['summary']['accounts_enumerated'] = len(username_results['results'])
        risks.append(username_results['confidence_score'])
        
        correlation['findings'].append({
            'type': 'Username Matches',
            'count': len(username_results['results']),
            'summary': username_results['risk_summary']
        })
    
    # Process email results
    if email_results and email_results.get('results'):
        correlation['summary']['breaches_found'] = email_results['breach_count']
        
        risk_levels = {'Critical': 0.95, 'High': 0.75, 'Medium': 0.5, 'None': 0.1}
        risks.append(risk_levels.get(email_results['risk_level'], 0.3))
        
        correlation['findings'].append({
            'type': 'Email Breaches',
            'count': email_results['breach_count'],
            'summary': f"Found in {email_results['breach_count']} breach(es)"
        })
    
    # Calculate overall risk
    if risks:
        avg_risk = sum(risks) / len(risks)
        if avg_risk >= 0.8:
            correlation['overall_risk'] = 'Critical'
        elif avg_risk >= 0.6:
            correlation['overall_risk'] = 'High'
        elif avg_risk >= 0.4:
            correlation['overall_risk'] = 'Medium'
        else:
            correlation['overall_risk'] = 'Low'
    
    # Add correlations if multiple check types are present
    if username_results and email_results:
        if username_results.get('results') and email_results.get('results'):
            correlation['correlations'].append({
                'type': 'Cross-check',
                'message': 'User has both account presence and email in breaches',
                'recommendation': 'Immediate security review recommended'
            })
    
    return correlation
