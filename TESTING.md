# OSINT Checker - Development & Testing Guide

## Development Workflow

### Initial Setup

```bash
# Clone repository
git clone <repo-url>
cd osint-checker

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install dev dependencies
pip install pytest pytest-flask black flake8
```

### Running Locally

```bash
# Start development server
python app.py

# Server runs at http://localhost:5000
# Auto-reloads when code changes (debug mode)
```

### Code Quality

```bash
# Format code
black app.py engine/ utils/ --line-length=100

# Lint code
flake8 app.py engine/ utils/ --max-line-length=100

# Find issues
pylint app.py
```

## Testing

### Unit Tests

Create `test_helpers.py`:

```python
import pytest
from utils.helpers import (
    validate_email, validate_username, validate_phone,
    calculate_confidence
)

def test_validate_email():
    assert validate_email("user@example.com") == True
    assert validate_email("invalid.email") == False
    assert validate_email("test@domain.co.uk") == True

def test_validate_username():
    is_valid, reason = validate_username("john_doe")
    assert is_valid == True

    is_valid, reason = validate_username("ab")
    assert is_valid == False
    assert "3 characters" in reason

def test_validate_phone():
    assert validate_phone("+1-202-555-0123") == True
    assert validate_phone("+44 20 1234 5678") == True
    assert validate_phone("123") == False

def test_calculate_confidence():
    factors = {"match_rate": 0.95, "platform_known": 0.9}
    assert calculate_confidence(factors) == "High"

    factors = {"match_rate": 0.65, "platform_known": 0.7}
    assert calculate_confidence(factors) == "Medium"

    assert calculate_confidence({}) == "Low"
```

### API Tests

Create `test_api.py`:

```python
import pytest
import json
from app import create_app

@pytest.fixture
def client():
    app = create_app({'TESTING': True})
    with app.test_client() as client:
        yield client

def test_health_endpoint(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'

def test_username_check(client):
    response = client.post('/api/check',
        json={'input': 'john_doe', 'input_type': 'username'}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert data['input_type'] == 'username'

def test_email_check(client):
    response = client.post('/api/check',
        json={'input': 'test@example.com', 'input_type': 'email'}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert 'results' in data

def test_phone_check(client):
    response = client.post('/api/check',
        json={'input': '+1-202-555-0123', 'input_type': 'phone'}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] == True
    assert data['valid'] == True

def test_invalid_input(client):
    response = client.post('/api/check',
        json={'input': '', 'input_type': 'username'}
    )
    assert response.status_code == 400

def test_short_username(client):
    response = client.post('/api/check',
        json={'input': 'ab', 'input_type': 'username'}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['valid'] == False

def test_invalid_email(client):
    response = client.post('/api/check',
        json={'input': 'not-an-email', 'input_type': 'email'}
    )
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['valid'] == False
```

### Run Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest test_api.py

# Run with coverage
pytest --cov=. --cov-report=html
```

## Manual Testing

### Browser Testing

1. **Open http://localhost:5000**
2. **Test Username Check:**
   - Enter: `github_user`
   - Select: Username
   - Click: Check
   - Verify: Results table appears with platforms
   - Verify: Confidence scores shown
   - Check: Links are clickable

3. **Test Email Check:**
   - Enter: `test@example.com`
   - Select: Email
   - Click: Check
   - Verify: Breach information displayed
   - Verify: Risk level shown
   - Check: Recommendations appear

4. **Test Phone Check:**
   - Enter: `+1-202-555-0123`
   - Select: Phone
   - Click: Check
   - Verify: Validation passed
   - Verify: Format check shows valid

5. **Test Copy Button:**
   - Click: "Copy Results"
   - Paste somewhere: Check results copied
   - Verify: "✓ Copied" confirmation shown

6. **Test Reset:**
   - Click: "New Search"
   - Verify: Form cleared
   - Verify: Results hidden

### cURL Testing

```bash
# Username check
curl -X POST http://localhost:5000/api/check \
  -H "Content-Type: application/json" \
  -d '{
    "input": "john_doe",
    "input_type": "username"
  }'

# Email check
curl -X POST http://localhost:5000/api/check \
  -H "Content-Type: application/json" \
  -d '{
    "input": "user@example.com",
    "input_type": "email"
  }'

# Phone check
curl -X POST http://localhost:5000/api/check \
  -H "Content-Type: application/json" \
  -d '{
    "input": "+1-202-555-0123",
    "input_type": "phone"
  }'

# Health check
curl http://localhost:5000/api/health
```

### Load Testing

```bash
# Install Apache Bench
sudo apt install apache2-utils

# Load test (100 requests, 10 concurrent)
ab -n 100 -c 10 http://localhost:5000/

# Load test API endpoint
ab -n 100 -c 10 -p payload.json -T application/json \
  http://localhost:5000/api/health
```

Install `wrk` for better load testing:

```bash
# Install wrk
sudo apt install wrk

# Create test script (test.lua)
request = function()
   wrk.method = "POST"
   wrk.body = '{"input":"john_doe","input_type":"username"}'
   wrk.headers["Content-Type"] = "application/json"
   return wrk.format(nil, "/api/check")
end

# Run test (4 threads, 100 connections, 30 seconds)
wrk -t4 -c100 -d30s -s test.lua http://localhost:5000/
```

## Integration Testing

### End-to-End Workflow

```bash
#!/bin/bash
# e2e-test.sh

BASE_URL="http://localhost:5000"
TESTS_PASSED=0
TESTS_FAILED=0

# Test 1: Health check
echo "Test 1: Health Check..."
RESPONSE=$(curl -s "$BASE_URL/api/health")
if echo "$RESPONSE" | grep -q "healthy"; then
    echo "✓ Health check passed"
    ((TESTS_PASSED++))
else
    echo "✗ Health check failed"
    ((TESTS_FAILED++))
fi

# Test 2: Username check
echo "Test 2: Username Check..."
RESPONSE=$(curl -s -X POST "$BASE_URL/api/check" \
  -H "Content-Type: application/json" \
  -d '{"input":"john_doe","input_type":"username"}')
if echo "$RESPONSE" | grep -q '"success":true'; then
    echo "✓ Username check passed"
    ((TESTS_PASSED++))
else
    echo "✗ Username check failed"
    ((TESTS_FAILED++))
fi

# Test 3: Frontend page
echo "Test 3: Frontend Page..."
RESPONSE=$(curl -s "$BASE_URL/" | grep -o "OSINT Checker")
if [ ! -z "$RESPONSE" ]; then
    echo "✓ Frontend page loaded"
    ((TESTS_PASSED++))
else
    echo "✗ Frontend page failed"
    ((TESTS_FAILED++))
fi

echo ""
echo "Tests passed: $TESTS_PASSED"
echo "Tests failed: $TESTS_FAILED"
```

Run it:

```bash
chmod +x e2e-test.sh
./e2e-test.sh
```

## Performance Testing

### Benchmark Results

Track these metrics:

```python
# benchmark.py
import time
import requests
import statistics

def benchmark_endpoint(endpoint, json_data, iterations=100):
    times = []
    for _ in range(iterations):
        start = time.time()
        response = requests.post(f"http://localhost:5000{endpoint}", json=json_data)
        end = time.time()
        times.append((end - start) * 1000)  # Convert to ms

    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0,
        "min": min(times),
        "max": max(times)
    }

# Test username check
print("Username Check Performance:")
results = benchmark_endpoint("/api/check",
    {"input": "john_doe", "input_type": "username"})
print(f"  Mean: {results['mean']:.2f}ms")
print(f"  Median: {results['median']:.2f}ms")
print(f"  Min: {results['min']:.2f}ms")
print(f"  Max: {results['max']:.2f}ms")

# Test email check
print("\nEmail Check Performance:")
results = benchmark_endpoint("/api/check",
    {"input": "test@example.com", "input_type": "email"})
print(f"  Mean: {results['mean']:.2f}ms")
```

Run benchmark:

```bash
pip install requests
python benchmark.py
```

## Debugging

### Enable Flask Debug Mode

```python
# In app.py or set environment
app.run(debug=True)  # Auto-reload, interactive debugger
```

### Logging

Add to your code:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.debug("Check started for: %s", username)
logger.info("Found match on GitHub")
logger.warning("Slow response time: %.2fs", response_time)
logger.error("API error: %s", str(e))
```

View logs:

```bash
tail -f logs/app.log
```

### Browser DevTools

- **Elements**: Inspect DOM structure
- **Console**: Check for JavaScript errors
- **Network**: Monitor API requests
- **Performance**: Check page load times

### VS Code Debugging

Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Flask",
      "type": "python",
      "request": "launch",
      "module": "flask",
      "env": {
        "FLASK_APP": "app.py",
        "FLASK_ENV": "development"
      },
      "args": ["run"],
      "jinja": true
    }
  ]
}
```

## Performance Optimization Checklist

- [ ] Enable gzip compression in Nginx
- [ ] Set appropriate cache headers
- [ ] Minimize CSS/JavaScript
- [ ] Optimize database queries (if applicable)
- [ ] Use CDN for static files
- [ ] Enable HTTP/2
- [ ] Implement request rate limiting
- [ ] Monitor slow queries/endpoints
- [ ] Profile memory usage
- [ ] Review Python GC settings

---

**Development best practices:**

- Always test locally before pushing
- Keep tests up-to-date with code changes
- Document any new endpoints or features
- Use consistent code style (Black, Flake8)
- Review security implications of changes
