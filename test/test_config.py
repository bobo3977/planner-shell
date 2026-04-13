#!/usr/bin/env python3
"""
Configuration and environment variable tests.
Tests the config module's ability to load settings from environment and .env files.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import config
from config import get_int, get_float, get_bool, load_prompt


def test_config_values():
    """Test that configuration values are loaded correctly."""
    print("=" * 60)
    print("Testing Configuration Values")
    print("=" * 60)
    
    print("\n1. Checking core configuration values:")
    
    # LLM Configuration
    print(f"   OPENAI_MODEL: {config.OPENAI_MODEL}")
    assert isinstance(config.OPENAI_MODEL, str), "OPENAI_MODEL should be string"
    print(f"   ✅ OPENAI_MODEL is valid")
    
    print(f"   OPENROUTER_MODEL: {config.OPENROUTER_MODEL}")
    assert isinstance(config.OPENROUTER_MODEL, str), "OPENROUTER_MODEL should be string"
    print(f"   ✅ OPENROUTER_MODEL is valid")
    
    print(f"   LLM_TEMPERATURE: {config.LLM_TEMPERATURE}")
    assert 0 <= config.LLM_TEMPERATURE <= 1, "LLM_TEMPERATURE should be between 0 and 1"
    print(f"   ✅ LLM_TEMPERATURE is valid")
    
    # Cache Configuration
    print(f"   CACHE_BACKEND: {config.CACHE_BACKEND}")
    assert config.CACHE_BACKEND in ('sqlite', 'singlestore'), "CACHE_BACKEND should be sqlite or singlestore"
    print(f"   ✅ CACHE_BACKEND is valid")
    
    print(f"   PLAN_CACHE_DB_PATH: {config.PLAN_CACHE_DB_PATH}")
    assert isinstance(config.PLAN_CACHE_DB_PATH, str), "PLAN_CACHE_DB_PATH should be string"
    print(f"   ✅ PLAN_CACHE_DB_PATH is valid")
    
    print(f"   PLAN_CACHE_TTL_DAYS: {config.PLAN_CACHE_TTL_DAYS}")
    assert config.PLAN_CACHE_TTL_DAYS > 0, "PLAN_CACHE_TTL_DAYS should be positive"
    print(f"   ✅ PLAN_CACHE_TTL_DAYS is valid")
    
    # Timeout Configuration
    print(f"   PLAN_TIMEOUT: {config.PLAN_TIMEOUT}")
    assert config.PLAN_TIMEOUT > 0, "PLAN_TIMEOUT should be positive"
    print(f"   ✅ PLAN_TIMEOUT is valid")
    
    print(f"   EXECUTE_TIMEOUT: {config.EXECUTE_TIMEOUT}")
    assert config.EXECUTE_TIMEOUT > 0, "EXECUTE_TIMEOUT should be positive"
    print(f"   ✅ EXECUTE_TIMEOUT is valid")
    
    # Security Configuration
    print(f"   ENABLE_AUDITOR: {config.ENABLE_AUDITOR}")
    assert isinstance(config.ENABLE_AUDITOR, bool), "ENABLE_AUDITOR should be boolean"
    print(f"   ✅ ENABLE_AUDITOR is valid")
    
    print(f"   AUTO_APPROVE: {config.AUTO_APPROVE}")
    assert isinstance(config.AUTO_APPROVE, bool), "AUTO_APPROVE should be boolean"
    print(f"   ✅ AUTO_APPROVE is valid")
    
    print("\n✅ All configuration values are valid!")
    return True


def test_env_var_overrides():
    """Test that environment variables can override defaults."""
    print("\n" + "=" * 60)
    print("Testing Environment Variable Overrides")
    print("=" * 60)
    
    # Save original environment
    original_env = os.environ.copy()
    
    try:
        # Set test environment variables
        os.environ['PLAN_CACHE_TTL_DAYS'] = '15'
        os.environ['LLM_TEMPERATURE'] = '0.5'
        os.environ['ENABLE_AUDITOR'] = 'false'
        os.environ['MAX_OUTPUT_BYTES'] = '5242880'  # 5 MB
        
        # Reload config module to pick up new env vars
        import importlib
        import config.config as config_module
        importlib.reload(config_module)
        importlib.reload(config)
        
        print("\n1. Testing overridden values:")
        
        # Verify overrides took effect
        assert config.PLAN_CACHE_TTL_DAYS == 15, \
            f"PLAN_CACHE_TTL_DAYS should be 15, got {config.PLAN_CACHE_TTL_DAYS}"
        print(f"   ✅ PLAN_CACHE_TTL_DAYS = {config.PLAN_CACHE_TTL_DAYS} (overridden)")
        
        assert config.LLM_TEMPERATURE == 0.5, \
            f"LLM_TEMPERATURE should be 0.5, got {config.LLM_TEMPERATURE}"
        print(f"   ✅ LLM_TEMPERATURE = {config.LLM_TEMPERATURE} (overridden)")
        
        assert config.ENABLE_AUDITOR == False, \
            f"ENABLE_AUDITOR should be False, got {config.ENABLE_AUDITOR}"
        print(f"   ✅ ENABLE_AUDITOR = {config.ENABLE_AUDITOR} (overridden)")
        
        assert config.MAX_OUTPUT_BYTES == 5242880, \
            f"MAX_OUTPUT_BYTES should be 5242880, got {config.MAX_OUTPUT_BYTES}"
        print(f"   ✅ MAX_OUTPUT_BYTES = {config.MAX_OUTPUT_BYTES:,} (overridden)")
        
        print("\n✅ Environment variable overrides work correctly!")
        
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)
        import config.config as config_module
        importlib.reload(config_module)
        importlib.reload(config)
    
    return True


def test_get_int_get_float_get_bool():
    """Test the helper functions for type conversion."""
    print("\n" + "=" * 60)
    print("Testing Type Conversion Helpers")
    print("=" * 60)
    
    # Test get_int
    print("\n1. Testing get_int():")
    assert get_int('TEST_INT_ENV', 42) == 42, "Should return default when env var not set"
    print("   ✅ Default value works")
    
    os.environ['TEST_INT_ENV'] = '100'
    assert get_int('TEST_INT_ENV', 42) == 100, "Should read from environment"
    print("   ✅ Environment value works")
    
    os.environ['TEST_INT_ENV'] = 'invalid'
    assert get_int('TEST_INT_ENV', 42) == 42, "Should fall back to default on invalid"
    print("   ✅ Invalid value falls back to default")
    
    # Test get_float
    print("\n2. Testing get_float():")
    assert get_float('TEST_FLOAT_ENV', 3.14) == 3.14, "Should return default"
    print("   ✅ Default value works")
    
    os.environ['TEST_FLOAT_ENV'] = '2.718'
    assert get_float('TEST_FLOAT_ENV', 3.14) == 2.718, "Should read from environment"
    print("   ✅ Environment value works")
    
    os.environ['TEST_FLOAT_ENV'] = 'invalid'
    assert get_float('TEST_FLOAT_ENV', 3.14) == 3.14, "Should fall back to default on invalid"
    print("   ✅ Invalid value falls back to default")
    
    # Test get_bool
    print("\n3. Testing get_bool():")
    assert get_bool('TEST_BOOL_ENV', True) == True, "Should return default"
    print("   ✅ Default value works")
    
    os.environ['TEST_BOOL_ENV'] = '1'
    assert get_bool('TEST_BOOL_ENV', True) == True, "Should interpret '1' as True"
    print("   ✅ '1' -> True")
    
    os.environ['TEST_BOOL_ENV'] = 'true'
    assert get_bool('TEST_BOOL_ENV', False) == True, "Should interpret 'true' as True"
    print("   ✅ 'true' -> True")
    
    os.environ['TEST_BOOL_ENV'] = '0'
    assert get_bool('TEST_BOOL_ENV', True) == False, "Should interpret '0' as False"
    print("   ✅ '0' -> False")
    
    os.environ['TEST_BOOL_ENV'] = 'false'
    assert get_bool('TEST_BOOL_ENV', True) == False, "Should interpret 'false' as False"
    print("   ✅ 'false' -> False")
    
    os.environ['TEST_BOOL_ENV'] = 'invalid'
    assert get_bool('TEST_BOOL_ENV', True) == True, "Should return default on invalid"
    print("   ✅ Invalid value falls back to default")
    
    print("\n✅ Type conversion helpers work correctly!")
    return True


def test_prompt_loading_config():
    """Test prompt loading with different configurations."""
    print("\n" + "=" * 60)
    print("Testing Prompt Loading Configuration")
    print("=" * 60)
    
    # Save original PROMPT_DIR
    original_prompt_dir = os.environ.get('PROMPT_DIR')
    
    try:
        # Test with default prompts
        print("\n1. Loading default prompts:")
        
        planner_prompt = load_prompt('planner', required_vars=['{task}', '{os_info}', '{current_date}'])
        assert len(planner_prompt) > 1000, "Planner prompt should be substantial"
        print(f"   ✅ Planner prompt loaded ({len(planner_prompt)} chars)")
        
        executor_prompt = load_prompt('executor', required_vars=['{os_info}', '{user_task}', '{plan}'])
        assert len(executor_prompt) > 500, "Executor prompt should be substantial"
        print(f"   ✅ Executor prompt loaded ({len(executor_prompt)} chars)")
        
        distill_prompt = load_prompt('distill', required_vars=['{current_date}', '{os_info}', '{user_task}', '{execution_history}'])
        assert len(distill_prompt) > 1000, "Distill prompt should be substantial"
        print(f"   ✅ Distill prompt loaded ({len(distill_prompt)} chars)")
        
        # Test with custom prompt directory
        print("\n2. Testing custom PROMPT_DIR:")
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_dir = Path(tmpdir) / "custom_prompts"
            prompt_dir.mkdir()
            
            # Create a custom planner prompt
            custom_prompt = """# Custom Planner Prompt
Task: {task}
OS: {os_info}
Date: {current_date}
This is a custom prompt for testing."""
            (prompt_dir / "planner.md").write_text(custom_prompt)
            
            os.environ['PROMPT_DIR'] = str(prompt_dir)
            
            # Reload config to pick up new PROMPT_DIR
            import importlib
            importlib.reload(config)
            
            loaded_prompt = load_prompt('planner', required_vars=['{task}', '{os_info}', '{current_date}'])
            assert loaded_prompt == custom_prompt, "Custom prompt should be loaded"
            print("   ✅ Custom prompt directory works")
            
            # Clean up
            del os.environ['PROMPT_DIR']
            importlib.reload(config)
        
        # Test required variable validation
        print("\n3. Testing required variable validation:")
        try:
            load_prompt('planner', required_vars=['{missing_var}'])
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert 'missing_var' in str(e), "Error should mention missing variable"
            print(f"   ✅ Missing variable detection works: {e}")
        
    finally:
        # Restore original PROMPT_DIR if it existed
        if original_prompt_dir:
            os.environ['PROMPT_DIR'] = original_prompt_dir
        else:
            if 'PROMPT_DIR' in os.environ:
                del os.environ['PROMPT_DIR']
    
    print("\n✅ Prompt loading configuration test passed!")
    return True


def test_single_store_config():
    """Test SingleStore configuration values."""
    print("\n" + "=" * 60)
    print("Testing SingleStore Configuration")
    print("=" * 60)
    
    print("\n1. Checking SingleStore settings:")
    
    print(f"   SINGLESTORE_HOST: {config.SINGLESTORE_HOST}")
    assert isinstance(config.SINGLESTORE_HOST, str), "SINGLESTORE_HOST should be string"
    print("   ✅ SINGLESTORE_HOST is valid")
    
    print(f"   SINGLESTORE_PORT: {config.SINGLESTORE_PORT}")
    assert isinstance(config.SINGLESTORE_PORT, int), "SINGLESTORE_PORT should be integer"
    assert 1 <= config.SINGLESTORE_PORT <= 65535, "PORT should be valid port number"
    print("   ✅ SINGLESTORE_PORT is valid")
    
    print(f"   SINGLESTORE_USER: {config.SINGLESTORE_USER}")
    assert isinstance(config.SINGLESTORE_USER, str), "SINGLESTORE_USER should be string"
    print("   ✅ SINGLESTORE_USER is valid")
    
    print(f"   SINGLESTORE_DATABASE: {config.SINGLESTORE_DATABASE}")
    assert isinstance(config.SINGLESTORE_DATABASE, str), "SINGLESTORE_DATABASE should be string"
    print("   ✅ SINGLESTORE_DATABASE is valid")
    
    # Password may be empty but should be string
    assert isinstance(config.SINGLESTORE_PASSWORD, str), "SINGLESTORE_PASSWORD should be string"
    print("   ✅ SINGLESTORE_PASSWORD is valid (may be empty)")
    
    print("\n✅ SingleStore configuration is valid!")
    return True


def main():
    """Run all configuration tests."""
    print("=" * 60)
    print("CONFIGURATION TESTS")
    print("=" * 60)
    
    try:
        test_config_values()
        test_env_var_overrides()
        test_get_int_get_float_get_bool()
        test_prompt_loading_config()
        test_single_store_config()
        
        print("\n" + "=" * 60)
        print("🎉 ALL CONFIGURATION TESTS PASSED!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
