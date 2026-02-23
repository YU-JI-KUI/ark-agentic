#!/usr/bin/env python3
"""
Simple test script to verify pycryptodome dependency handling
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_pa_sx_without_crypto():
    """Test that PA-SX models work without pycryptodome"""
    print("Testing PA-SX model creation without pycryptodome...")

    try:
        from ark_agentic.core.llm.factory import create_chat_model, PAModel

        # Mock environment for PA-SX
        os.environ.update({
            'PA_SX_BASE_URL': 'https://test-sx.example.com',
            'PA_SX_API_KEY': 'test-key',
            'PA_SX_80B_APP_ID': 'test-app-id'
        })

        llm = create_chat_model(PAModel.PA_SX_80B)
        print("✅ PA-SX model creation successful")
        return True

    except Exception as e:
        print(f"❌ PA-SX model creation failed: {e}")
        return False

def test_deepseek_without_crypto():
    """Test that DeepSeek models work without pycryptodome"""
    print("Testing DeepSeek model creation without pycryptodome...")

    try:
        from ark_agentic.core.llm.factory import create_chat_model

        llm = create_chat_model("deepseek-chat", api_key="sk-test")
        print("✅ DeepSeek model creation successful")
        return True

    except Exception as e:
        print(f"❌ DeepSeek model creation failed: {e}")
        return False

def test_pa_jt_error_handling():
    """Test that PA-JT models fail gracefully without pycryptodome"""
    print("Testing PA-JT model error handling without pycryptodome...")

    try:
        from ark_agentic.core.llm.factory import create_chat_model, PAModel

        # Mock environment for PA-JT
        os.environ.update({
            'PA_JT_BASE_URL': 'https://test-jt.example.com',
            'PA_JT_OPEN_API_CODE': 'test-code',
            'PA_JT_OPEN_API_CREDENTIAL': 'test-cred',
            'PA_JT_RSA_PRIVATE_KEY': 'test-key',
            'PA_JT_GPT_APP_KEY': 'test-app-key',
            'PA_JT_GPT_APP_SECRET': 'test-secret',
            'PA_JT_SCENE_ID': 'test-scene'
        })

        # This should fail with helpful error message
        try:
            llm = create_chat_model(PAModel.PA_JT_80B)
            print("❌ PA-JT model creation should have failed")
            return False
        except ImportError as e:
            error_msg = str(e)
            if "ark-agentic[pa-jt]" in error_msg and "pycryptodome" in error_msg:
                print("✅ PA-JT model failed with helpful error message")
                print(f"   Error: {error_msg}")
                return True
            else:
                print(f"❌ PA-JT model failed with unhelpful error: {error_msg}")
                return False

    except Exception as e:
        print(f"❌ PA-JT error handling test failed: {e}")
        return False

def test_transport_error_handling():
    """Test transport RSA signing error handling"""
    print("Testing transport RSA signing error handling...")

    try:
        from ark_agentic.core.llm.transport import rsa_sign

        # This should fail with helpful error message
        try:
            result = rsa_sign("test-key", "123456789")
            print("❌ RSA signing should have failed without pycryptodome")
            return False
        except ImportError as e:
            error_msg = str(e)
            if "pycryptodome is required" in error_msg and "ark-agentic[pa-jt]" in error_msg:
                print("✅ RSA signing failed with helpful error message")
                print(f"   Error: {error_msg}")
                return True
            else:
                print(f"❌ RSA signing failed with unhelpful error: {error_msg}")
                return False

    except Exception as e:
        print(f"❌ Transport error handling test failed: {e}")
        return False

def test_hmac_still_works():
    """Test that HMAC signing still works (uses stdlib)"""
    print("Testing HMAC signing (should work without pycryptodome)...")

    try:
        from ark_agentic.core.llm.transport import hmac_sign

        result = hmac_sign("test-key", "test-secret", "123456789")
        if isinstance(result, str) and len(result) > 0:
            print("✅ HMAC signing works correctly")
            return True
        else:
            print(f"❌ HMAC signing returned invalid result: {result}")
            return False

    except Exception as e:
        print(f"❌ HMAC signing test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("PYCRYPTODOME DEPENDENCY HANDLING TESTS")
    print("=" * 60)

    tests = [
        test_pa_sx_without_crypto,
        test_deepseek_without_crypto,
        test_pa_jt_error_handling,
        test_transport_error_handling,
        test_hmac_still_works,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            results.append(False)
        print()

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    for i, (test, result) in enumerate(zip(tests, results)):
        status = "PASS" if result else "FAIL"
        print(f"{i+1}. {test.__name__}: {status}")

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 SUCCESS: pycryptodome dependency handling is working correctly!")
        return True
    else:
        print("⚠️  PARTIAL: Some issues remain.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)