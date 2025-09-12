#!/usr/bin/env python3
"""
Debug script to test Nominal connection and basic operations.
"""

import os
from nominal import get_default_client, NominalClient

def test_nominal_connection():
    """Test basic Nominal connection and operations."""
    print("🔍 Testing Nominal connection...")
    
    try:
        # Test 1: Create client
        print("1. Creating Nominal client...")
        client = NominalClient.from_profile(profile="nominal-demo@muonspace.com")
        print("✅ Client created successfully")
        
        # Test 2: Create empty dataset
        print("2. Creating empty dataset...")
        dataset = client.create_dataset(
            name="Test Dataset - Debug",
            description="Test dataset for debugging",
            prefix_tree_delimiter="."
        )
        print(f"✅ Dataset created: {dataset.rid}")
        
        # Test 3: List datasets (optional)
        print("3. Testing dataset access...")
        datasets = client.list_datasets()
        print(f"✅ Found {len(datasets)} datasets")
        
        print("🎉 All tests passed! Nominal connection is working.")
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_nominal_connection()


