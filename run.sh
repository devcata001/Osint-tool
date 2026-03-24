#!/bin/bash
# Development startup script for OSINT Checker

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting OSINT Checker...${NC}"

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Start the app
echo -e "${GREEN}Starting Flask development server...${NC}"
echo -e "${YELLOW}OSINT Checker is running at http://localhost:5000${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

python app.py
