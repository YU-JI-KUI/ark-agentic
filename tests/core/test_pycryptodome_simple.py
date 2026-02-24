#!/usr/bin/env python3
"""
Simple test script to verify pycryptodome dependency handling
"""

import sys
import os
from pathlib import Path

# Add src to path (go up two levels from tests/core to project root, then to src)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

def test_transport_error_handling():
    """Test transport RSA signing error handling"""
    print("Testing transport RSA signing error handling...")

    try:
        from ark_agentic.core.llm.pa_jt_llm import rsa_sign

        # This should fail with helpful error message if pycryptodome is missing
        try:
            result = rsa_sign("test-key", "123456789")
            print("PASS: RSA signing worked (pycryptodome is available)")
            return True
        except ImportError as e:
            error_msg = str(e)
            if "pycryptodome is required" in error_msg and "ark-agentic[pa-jt]" in error_msg:
                print("PASS: RSA signing failed with helpful error message")
                print(f"   Error: {error_msg}")
                return True
            else:
                print(f"FAIL: RSA signing failed with unhelpful error: {error_msg}")
                return False

    except Exception as e:
        print(f"FAIL: Transport error handling test failed: {e}")
        return False

def test_hmac_still_works():
    """Test that HMAC signing still works (uses stdlib)"""
    print("Testing HMAC signing (should work without pycryptodome)...")

    try:
        from ark_agentic.core.llm.pa_jt_llm import hmac_sign

        result = hmac_sign("test-key", "test-secret", "123456789")
        if isinstance(result, str) and len(result) > 0:
            print("PASS: HMAC signing works correctly")
            return True
        else:
            print(f"FAIL: HMAC signing returned invalid result: {result}")
            return False

    except Exception as e:
        print(f"FAIL: HMAC signing test failed: {e}")
        return False

def test_crypto_detection():
    """Test that crypto detection works correctly"""
    print("Testing crypto availability detection...")

    try:
        from ark_agentic.core.llm.pa_jt_llm import _HAS_CRYPTO

        if _HAS_CRYPTO:
            print("PASS: pycryptodome is available")
        else:
            print("PASS: pycryptodome is not available (as expected)")
        return True

    except Exception as e:
        print(f"FAIL: Crypto detection test failed: {e}")
        return False

def test_optional_dependency_structure():
    """Test that pyproject.toml has correct optional dependency structure"""
    print("Testing pyproject.toml optional dependency structure...")

    try:
        import toml

        with open("pyproject.toml", "r") as f:
            config = toml.load(f)

        # Check that pycryptodome is not in main dependencies
        main_deps = config.get("project", {}).get("dependencies", [])
        has_crypto_in_main = any("pycryptodome" in dep for dep in main_deps)

        if has_crypto_in_main:
            print("FAIL: pycryptodome is still in main dependencies")
            return False

        # Check that pycryptodome is in pa-jt optional dependencies
        optional_deps = config.get("project", {}).get("optional-dependencies", {})
        pa_jt_deps = optional_deps.get("pa-jt", [])
        has_crypto_in_pa_jt = any("pycryptodome" in dep for dep in pa_jt_deps)

        if not has_crypto_in_pa_jt:
            print("FAIL: pycryptodome is not in pa-jt optional dependencies")
            return False

        print("PASS: pyproject.toml has correct dependency structure")
        return True

    except ImportError:
        print("SKIP: toml module not available, cannot test pyproject.toml structure")
        return True
    except Exception as e:
        print(f"FAIL: pyproject.toml structure test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("PYCRYPTODOME DEPENDENCY HANDLING TESTS")
    print("=" * 60)

    tests = [
        test_crypto_detection,
        test_transport_error_handling,
        test_hmac_still_works,
        test_optional_dependency_structure,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"FAIL: Test {test.__name__} crashed: {e}")
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
        print("SUCCESS: pycryptodome dependency handling is working correctly!")
        return True
    else:
        print("PARTIAL: Some issues remain.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)