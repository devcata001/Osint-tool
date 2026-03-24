"""
Trace Handle - Production-ready OSINT tool
Fast, minimal, engineer-level intelligence for username/email enumeration.
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import time
import sys

from engine.enumerator import check_username_across_platforms
from engine.breach_checker import check_email_breaches, check_password_strength_in_breach
from engine.correlator import score_username_results, score_email_results, correlate_all_results
from utils.helpers import (
    validate_email, validate_username,
    sanitize_input, calculate_confidence
)


def create_app(config=None):
    """
    Factory function to create Flask application.
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        Configured Flask application
    """
    app = Flask(__name__, 
                template_folder='templates', 
                static_folder='static')
    
    # Configuration
    app.config['JSON_SORT_KEYS'] = False
    if config:
        app.config.update(config)
    
    # Enable CORS
    CORS(app)
    
    # ==================== ROUTES ====================
    
    @app.route('/')
    def index():
        """Serve main page."""
        return render_template('index.html')
    
    @app.route('/api/check', methods=['POST'])
    def api_check():
        """
        Main API endpoint for OSINT checks.
        
        Accepts:
            - input: The input string (username/email)
            - input_type: Type of input ('username', 'email')
            
        Returns:
            JSON with results and recommendations
        """
        try:
            data = request.get_json()
            input_value = sanitize_input(data.get('input', '').strip())
            input_type = data.get('input_type', '').lower()
            
            if not input_value or not input_type:
                return jsonify({
                    'success': False,
                    'error': 'Missing input or input_type'
                }), 400
            
            start_time = time.time()
            results = None
            
            # Route to appropriate checker
            if input_type == 'username':
                results = check_username(input_value)
            elif input_type == 'email':
                results = check_email(input_value)
            elif input_type == 'phone':
                return jsonify({
                    'success': False,
                    'error': 'Phone checks are disabled in this release. Use username or email.'
                }), 400
            else:
                return jsonify({
                    'success': False,
                    'error': f'Unknown input type: {input_type}'
                }), 400
            
            # Add timing
            results['execution_time_ms'] = round((time.time() - start_time) * 1000, 2)
            results['success'] = True
            
            return jsonify(results), 200
            
        except Exception as e:
            import traceback
            print(f"Error in /api/check: {str(e)}", file=sys.stderr)
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Health check endpoint."""
        return jsonify({
            'status': 'healthy',
            'version': '1.0.0',
            'timestamp': time.time()
        }), 200
    
    # ==================== HELPER FUNCTIONS ====================
    
    def check_username(username):
        """
        Check username across platforms.
        
        Args:
            username: Username to check
            
        Returns:
            Dictionary with results
        """
        is_valid, reason = validate_username(username)
        if not is_valid:
            return {
                'input_type': 'username',
                'input': username,
                'valid': False,
                'error': reason,
                'results': []
            }
        
        # Perform enumeration
        enum_results = check_username_across_platforms(username, check_variants=False)
        
        # Score results
        scored = score_username_results(enum_results)
        
        return {
            'input_type': 'username',
            'input': username,
            'valid': True,
            'results': scored['results'],
            'confidence_score': scored['confidence_score'],
            'risk_summary': scored['risk_summary'],
            'recommendations': scored['recommendations'],
            'summary': {
                'total_checks': enum_results['summary']['total_checks'],
                'matches_found': enum_results['summary']['matches_found'],
                'variants_checked': 0,
                'found_count': enum_results['summary'].get('found_count', 0),
                'not_found_count': enum_results['summary'].get('not_found_count', 0),
                'uncertain_count': enum_results['summary'].get('uncertain_count', 0),
                'cache_hits': enum_results['summary'].get('cache_hits', 0),
                'network_errors': enum_results['summary'].get('network_errors', 0),
                'avg_response_time_ms': enum_results['summary'].get('avg_response_time_ms', 0.0),
                'proxy_enabled': enum_results['summary'].get('proxy_enabled', False)
            }
        }
    
    def check_email(email):
        """
        Check email for breach appearances.
        
        Args:
            email: Email to check
            
        Returns:
            Dictionary with results
        """
        if not validate_email(email):
            return {
                'input_type': 'email',
                'input': email,
                'valid': False,
                'error': 'Invalid email format',
                'results': []
            }
        
        # Check breaches
        breach_results = check_email_breaches(email)
        
        # Score results
        scored = score_email_results(breach_results)
        
        return {
            'input_type': 'email',
            'input': email,
            'valid': True,
            'results': scored['results'],
            'breach_count': scored['breach_count'],
            'risk_level': scored['risk_level'],
            'action_required': scored['action_required'],
            'recommendations': scored['recommendations'],
            'exposed_data_types': breach_results['summary']['exposed_data_types']
        }
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='127.0.0.1', port=5000)
