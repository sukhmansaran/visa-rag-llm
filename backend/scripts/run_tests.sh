#!/bin/bash

# Script to run all tests with coverage

echo "=========================================="
echo "Running Test Suite with Coverage"
echo "=========================================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Run tests with coverage
echo -e "\n${YELLOW}Running all tests...${NC}\n"

pytest backend/tests/ \
  --cov=backend/app \
  --cov-report=html \
  --cov-report=term-missing \
  --cov-report=json \
  -v \
  --tb=short

# Check exit code
if [ $? -eq 0 ]; then
  echo -e "\n${GREEN}✅ All tests passed!${NC}\n"
else
  echo -e "\n${RED}❌ Some tests failed!${NC}\n"
  exit 1
fi

# Display coverage summary
echo -e "\n${YELLOW}Coverage Summary:${NC}\n"
coverage report --skip-empty

# Check coverage threshold
COVERAGE=$(coverage json -o /dev/stdout | python3 -c "import sys, json; print(json.load(sys.stdin)['totals']['percent_covered'])")
THRESHOLD=70

echo -e "\n${YELLOW}Total Coverage: ${COVERAGE}%${NC}"
echo -e "${YELLOW}Threshold: ${THRESHOLD}%${NC}\n"

if (( $(echo "$COVERAGE >= $THRESHOLD" | bc -l) )); then
  echo -e "${GREEN}✅ Coverage threshold met!${NC}\n"
else
  echo -e "${RED}❌ Coverage below threshold!${NC}\n"
  exit 1
fi

echo "=========================================="
echo "Coverage report generated:"
echo "  HTML: htmlcov/index.html"
echo "  JSON: coverage.json"
echo "=========================================="
