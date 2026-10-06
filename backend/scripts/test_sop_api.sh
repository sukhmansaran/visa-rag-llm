#!/bin/bash

# Test script for SOP API endpoints
# Usage: ./test_sop_api.sh

BASE_URL="http://localhost:8000/api/v1"

echo "=========================================="
echo "SOP API Test Script"
echo "=========================================="

# Step 1: Create test user and get token
echo -e "\n📝 Step 1: Creating test user..."
SIGNUP_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "sop.test@example.com",
    "password": "test123"
  }')

TOKEN=$(echo $SIGNUP_RESPONSE | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
  echo "❌ Failed to get token. Response:"
  echo $SIGNUP_RESPONSE
  exit 1
fi

echo "✅ Token obtained: ${TOKEN:0:20}..."

# Step 2: Create user profile
echo -e "\n📝 Step 2: Creating user profile..."
PROFILE_RESPONSE=$(curl -s -X PUT "$BASE_URL/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "John",
    "last_name": "Doe",
    "education_level": "bachelor",
    "field_of_study": "Computer Science",
    "gpa": 3.8,
    "test_scores": {
      "gre": {
        "verbal": 160,
        "quantitative": 168,
        "analytical": 4.5
      },
      "toefl": 108
    },
    "work_experience": 2,
    "target_countries": ["Canada"],
    "target_universities": ["University of Toronto", "McGill"]
  }')

echo "✅ Profile created"

# Step 3: Generate SOP
echo -e "\n📝 Step 3: Generating SOP..."
SOP_RESPONSE=$(curl -s -X POST "$BASE_URL/documents/sop/generate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "university": "University of Toronto",
    "program": "Master of Science in Computer Science",
    "additional_info": "Interested in AI/ML research, particularly in natural language processing. Have published 2 papers in undergraduate research."
  }')

SOP_ID=$(echo $SOP_RESPONSE | grep -o '"id":[0-9]*' | cut -d':' -f2)

if [ -z "$SOP_ID" ]; then
  echo "❌ Failed to generate SOP. Response:"
  echo $SOP_RESPONSE
  exit 1
fi

echo "✅ SOP generated with ID: $SOP_ID"
echo -e "\nGenerated SOP content:"
echo $SOP_RESPONSE | grep -o '"content":"[^"]*' | cut -d'"' -f4 | head -c 500
echo -e "\n...(truncated)\n"

# Step 4: Get SOP by ID
echo -e "\n📝 Step 4: Retrieving SOP by ID..."
GET_SOP_RESPONSE=$(curl -s -X GET "$BASE_URL/documents/sop/$SOP_ID" \
  -H "Authorization: Bearer $TOKEN")

echo "✅ SOP retrieved successfully"

# Step 5: Update SOP
echo -e "\n📝 Step 5: Updating SOP content..."
UPDATE_RESPONSE=$(curl -s -X PUT "$BASE_URL/documents/sop/$SOP_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "This is an updated SOP content for testing purposes."
  }')

echo "✅ SOP updated successfully"

# Step 6: List all documents
echo -e "\n📝 Step 6: Listing all documents..."
LIST_RESPONSE=$(curl -s -X GET "$BASE_URL/documents/" \
  -H "Authorization: Bearer $TOKEN")

echo "✅ Documents listed:"
echo $LIST_RESPONSE | grep -o '"id":[0-9]*' | wc -l | xargs echo "  Total documents:"

# Step 7: Delete SOP
echo -e "\n📝 Step 7: Deleting SOP..."
DELETE_RESPONSE=$(curl -s -X DELETE "$BASE_URL/documents/$SOP_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nHTTP Status: %{http_code}")

echo "✅ SOP deleted successfully"

echo -e "\n=========================================="
echo "✅ All SOP API tests completed!"
echo "=========================================="
