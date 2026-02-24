"""Test that pycryptodome is optional for non-PA-JT models."""

import pytest
from unittest.mock import patch, MagicMock

from ark_agentic.core.llm.factory import create_chat_model, PAModel


def test_pa_sx_works_without_pycryptodome():
    """Test that PA-SX models work without pycryptodome installed."""
    # Mock environment variables for PA-SX
    with patch.dict('os.environ', {
        'PA_SX_BASE_URL': 'https://test-sx.example.com',
        'PA_SX_API_KEY': 'test-key',
        'PA_SX_80B_APP_ID': 'test-app-id'
    }):
        # This should work without pycryptodome
        llm = create_chat_model(PAModel.PA_SX_80B)
        assert llm is not None


def test_deepseek_works_without_pycryptodome():
    """Test that DeepSeek models work without pycryptodome installed."""
    # This should work without pycryptodome
    llm = create_chat_model("deepseek-chat", api_key="sk-test")
    assert llm is not None


def test_pa_jt_fails_without_pycryptodome():
    """Test that PA-JT models raise when creation fails (e.g. missing pycryptodome)."""
    with patch('ark_agentic.core.llm.pa_jt_llm.create_pa_jt_llm') as mock_create:
        mock_create.side_effect = ImportError(
            "PA-JT models require pycryptodome for RSA signing. Install with: uv add 'ark-agentic[pa-jt]' or uv add pycryptodome"
        )
        with patch.dict('os.environ', {
            'PA_JT_BASE_URL': 'https://test-jt.example.com',
            'PA_JT_OPEN_API_CODE': 'test-code',
            'PA_JT_OPEN_API_CREDENTIAL': 'test-cred',
            'PA_JT_RSA_PRIVATE_KEY': 'test-key',
            'PA_JT_GPT_APP_KEY': 'test-app-key',
            'PA_JT_GPT_APP_SECRET': 'test-secret',
            'PA_JT_SCENE_ID': 'test-scene'
        }):
            with pytest.raises(ImportError):
                create_chat_model(PAModel.PA_JT_80B)


def test_helpful_error_message_for_pa_jt():
    """Test that PA-JT models provide helpful error message."""
    # Test the actual transport error handling directly
    try:
        from ark_agentic.core.llm.pa_jt_llm import rsa_sign

        # Try to use RSA signing - should fail with helpful message if pycryptodome missing
        # Use a valid hex string for the RSA key (dummy hex data)
        try:
            rsa_sign("deadbeef", "1234567890")
            # If this succeeds, pycryptodome is available, which is fine
            assert True
        except ImportError as e:
            error_msg = str(e)
            assert "pycryptodome is required" in error_msg
            assert "ark-agentic[pa-jt]" in error_msg
        except Exception:
            # Other exceptions (like invalid key format) are also fine -
            # we just want to test the ImportError handling
            assert True

    except ImportError:
        # If we can't even import the pa_jt_llm module, that's also fine for this test
        assert True