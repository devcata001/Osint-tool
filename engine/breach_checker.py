"""
Email breach checker - checks if email has appeared in known data breaches.
Simulates checking against breach databases (HaveIBeenPwned, etc.).
"""

from typing import List, Dict
from datetime import datetime
import hashlib


# Simulated breach database
# In production, would use HaveIBeenPwned API or similar service
BREACH_DATABASE = {
    'linkedin': {
        'name': 'LinkedIn',
        'date': '2021-06-01',
        'record_count': '700M+',
        'exposed_data': ['Email addresses', 'Passwords', 'Phone numbers'],
        'description': 'Major LinkedIn data breach',
        'verified': True
    },
    'facebook': {
        'name': 'Facebook Cambridge Analytica',
        'date': '2019-04-03',
        'record_count': '540M+',
        'exposed_data': ['Names', 'Phone numbers', 'Email addresses'],
        'description': 'Facebook user data breach',
        'verified': True
    },
    'yahoo': {
        'name': 'Yahoo',
        'date': '2013-08-01',
        'record_count': '3B+',
        'exposed_data': ['Email addresses', 'Passwords', 'Security questions'],
        'description': 'Massive Yahoo user database breach',
        'verified': True
    },
    'equifax': {
        'name': 'Equifax',
        'date': '2017-07-29',
        'record_count': '147M+',
        'exposed_data': ['Social Security numbers', 'Email addresses', 'Addresses'],
        'description': 'Major credit bureau data breach',
        'verified': True
    },
    'uber': {
        'name': 'Uber',
        'date': '2016-11-14',
        'record_count': '57M+',
        'exposed_data': ['Names', 'Email addresses', 'Phone numbers'],
        'description': 'Uber driver and user data breach',
        'verified': True
    },
    'adobe': {
        'name': 'Adobe',
        'date': '2013-10-03',
        'record_count': '153M+',
        'exposed_data': ['Email addresses', 'Passwords', 'Credit card data'],
        'description': 'Adobe Creative Cloud and other service breach',
        'verified': True
    },
    'dropbox': {
        'name': 'Dropbox',
        'date': '2012-07-01',
        'record_count': '69M+',
        'exposed_data': ['Email addresses', 'Password hashes'],
        'description': 'Dropbox credentials breach',
        'verified': True
    },
}


def should_email_appear_in_breach(email: str, breach_id: str) -> bool:
    """
    Determine if an email should appear in a particular breach.
    
    In production, would query actual breach databases.
    Here uses heuristic based on email hash and breach.
    
    Args:
        email: Email address
        breach_id: Breach identifier
        
    Returns:
        True if email should appear in breach, False otherwise
    """
    # Create deterministic hash - same email always gets same result
    combined = f"{email}:{breach_id}"
    hash_value = hashlib.md5(combined.encode()).hexdigest()
    
    # Convert first 6 chars to integer and check probability
    # This ensures consistent results for same email/breach combo
    probability = int(hash_value[:6], 16) % 100
    
    # Tune probabilities per breach severity/size
    breach_thresholds = {
        'linkedin': 35,   # 35% chance
        'facebook': 30,   # 30% chance
        'yahoo': 55,      # 55% chance (huge breach)
        'equifax': 40,    # 40% chance
        'uber': 25,       # 25% chance
        'adobe': 35,      # 35% chance
        'dropbox': 20,    # 20% chance
    }
    
    threshold = breach_thresholds.get(breach_id, 30)
    return probability < threshold


def check_email_breaches(email: str) -> Dict:
    """
    Check if email appears in any known breaches.
    
    Args:
        email: Email address to check
        
    Returns:
        Dictionary with breach results and metadata
    """
    results = {
        'email': email,
        'breaches_found': [],
        'breach_count': 0,
        'risk_level': 'None',
        'summary': {
            'exposed_data_types': set(),
            'earliest_breach': None,
            'latest_breach': None
        }
    }
    
    # Check against all known breaches
    for breach_id, breach_info in BREACH_DATABASE.items():
        if should_email_appear_in_breach(email, breach_id):
            breach_result = {
                'breach_name': breach_info['name'],
                'breach_date': breach_info['date'],
                'record_count': breach_info['record_count'],
                'exposed_data': breach_info['exposed_data'],
                'verified': breach_info['verified'],
                'description': breach_info['description'],
            }
            results['breaches_found'].append(breach_result)
            results['breach_count'] += 1
            
            # Track exposed data types
            for data_type in breach_info['exposed_data']:
                results['summary']['exposed_data_types'].add(data_type)
            
            # Track earliest and latest breaches
            breach_date = datetime.strptime(breach_info['date'], '%Y-%m-%d')
            if results['summary']['earliest_breach'] is None:
                results['summary']['earliest_breach'] = breach_info['date']
            else:
                earliest = datetime.strptime(results['summary']['earliest_breach'], '%Y-%m-%d')
                if breach_date < earliest:
                    results['summary']['earliest_breach'] = breach_info['date']
            
            if results['summary']['latest_breach'] is None:
                results['summary']['latest_breach'] = breach_info['date']
            else:
                latest = datetime.strptime(results['summary']['latest_breach'], '%Y-%m-%d')
                if breach_date > latest:
                    results['summary']['latest_breach'] = breach_info['date']
    
    # Convert set to list for JSON serialization
    results['summary']['exposed_data_types'] = sorted(list(results['summary']['exposed_data_types']))
    
    # Determine risk level
    if results['breach_count'] >= 3:
        results['risk_level'] = 'Critical'
    elif results['breach_count'] >= 2:
        results['risk_level'] = 'High'
    elif results['breach_count'] == 1:
        results['risk_level'] = 'Medium'
    else:
        results['risk_level'] = 'None'
    
    # Sort by date (newest first)
    results['breaches_found'].sort(
        key=lambda x: datetime.strptime(x['breach_date'], '%Y-%m-%d'),
        reverse=True
    )
    
    return results


def check_password_strength_in_breach(password: str) -> Dict:
    """
    Check if password is commonly found in breaches (simplified).
    
    Args:
        password: Password to check
        
    Returns:
        Result with strength assessment
    """
    # In production would check against SecLists, HaveIBeenPwned etc.
    common_passwords = [
        '123456', 'password', '12345678', 'qwerty', 'abc123',
        'password123', '123456789', '12345', '1234567', 'password1'
    ]
    
    is_common = password.lower() in common_passwords
    
    return {
        'password_common': is_common,
        'recommendation': 'Please use a unique, strong password' if is_common else 'Password strength is acceptable',
        'breached_count': 0 if not is_common else 'Unknown (in common databases)'
    }
