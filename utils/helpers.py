"""
Helper utilities for OSINT checker.
Provides common functions for validation, formatting, and scoring.
"""

import re
from typing import List, Dict, Tuple
from urllib.parse import urljoin


def validate_email(email: str) -> bool:
    """
    Validate email format.
    
    Args:
        email: Email string to validate
        
    Returns:
        True if valid email format, False otherwise
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """
    Validate phone number format (basic international format).
    
    Args:
        phone: Phone string to validate
        
    Returns:
        True if valid phone format, False otherwise
    """
    # Remove common formatting characters
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
    # Check if 7-15 digits (standard international range)
    return bool(re.match(r'^\d{7,15}$', cleaned))


def validate_username(username: str) -> Tuple[bool, str]:
    """
    Validate username format.
    
    Args:
        username: Username string to validate
        
    Returns:
        Tuple of (is_valid, reason)
    """
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(username) > 32:
        return False, "Username must be at most 32 characters"
    if not re.match(r'^[a-zA-Z0-9._-]+$', username):
        return False, "Username contains invalid characters"
    return True, ""


def sanitize_input(input_str: str) -> str:
    """
    Sanitize user input by stripping whitespace and limiting length.
    
    Args:
        input_str: Input string to sanitize
        
    Returns:
        Sanitized string
    """
    return input_str.strip()[:256]


def format_url(base_url: str, username: str) -> str:
    """
    Format a profile URL with username.
    
    Args:
        base_url: Base URL template (e.g., "https://github.com/{}")
        username: Username to insert
        
    Returns:
        Formatted URL
    """
    if '{}' in base_url:
        return base_url.format(username)
    return urljoin(base_url, username)


def calculate_confidence(factors: Dict[str, float]) -> str:
    """
    Calculate confidence level based on multiple factors.
    
    Args:
        factors: Dictionary of factor_name -> score (0-1)
        
    Returns:
        Confidence level: 'High', 'Medium', or 'Low'
    """
    if not factors:
        return 'Low'
    
    avg_score = sum(factors.values()) / len(factors)
    
    if avg_score >= 0.9:
        return 'High'
    elif avg_score >= 0.6:
        return 'Medium'
    else:
        return 'Low'


def apply_bold_formatting(text: str, pattern: str) -> str:
    """
    Apply formatting to matching text (helper for frontend formatting).
    
    Args:
        text: Original text
        pattern: Pattern to match
        
    Returns:
        Formatted text (for use in templates)
    """
    return re.sub(f'({re.escape(pattern)})', r'<strong>\1</strong>', text, flags=re.IGNORECASE)
