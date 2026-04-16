#!/usr/bin/env python3
"""
Unit tests for validation functions in agent_runner.py
"""

import unittest
import sys
import os
from unittest.mock import patch

# Add parent directory to path to import agent_runner
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_runner import validate_checklist, validate_config


class TestValidateChecklist(unittest.TestCase):
    """Test validate_checklist function"""
    
    def test_valid_checklist_passes(self):
        """Test that a valid checklist passes validation"""
        checklist = {
            "tasks": [
                {
                    "id": 1,
                    "repo": "red-eye-agent",
                    "description": "Add test suite",
                    "status": "pending"
                },
                {
                    "id": 2,
                    "repo": "red-eye-agent",
                    "description": "Fix bug in validation",
                    "status": "done"
                }
            ]
        }
        
        # Should not raise SystemExit
        try:
            with patch('agent_runner.logger') as mock_logger:
                validate_checklist(checklist, "test_checklist.yaml")
                # Check that info was logged
                mock_logger.info.assert_called_with(
                    "Checklist validation passed for test_checklist.yaml"
                )
        except SystemExit:
            self.fail("validate_checklist raised SystemExit for valid checklist")
    
    def test_checklist_missing_required_field_fails(self):
        """Test that checklist with missing required field fails"""
        checklist = {
            "tasks": [
                {
                    "id": 1,
                    "repo": "red-eye-agent",
                    "description": "Add test suite",
                    # Missing 'status' field
                }
            ]
        }
        
        # Should raise SystemExit
        with self.assertRaises(SystemExit) as cm:
            with patch('agent_runner.logger') as mock_logger:
                validate_checklist(checklist, "test_checklist.yaml")
        
        # Check exit code is 1
        self.assertEqual(cm.exception.code, 1)
        
        # Check that error was logged
        mock_logger.error.assert_called_with(
            "Checklist validation failed: Task 1 missing required field 'status' in test_checklist.yaml"
        )


class TestValidateConfig(unittest.TestCase):
    """Test validate_config function"""
    
    def test_valid_config_passes(self):
        """Test that a valid config passes validation"""
        config = {
            "default_provider": "deepseek",
            "models": {
                "deepseek": {
                    "model": "deepseek-chat",
                    "max_tokens": 4096,
                    "temperature": 0.2
                },
                "openai": {
                    "model": "gpt-4o",
                    "max_tokens": 4096,
                    "temperature": 0.2
                },
                "anthropic": {
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4096,
                    "temperature": 0.2
                }
            },
            "budget": {
                "max_tokens_per_task": 100000,
                "max_cost_per_run": 10.00,
                "max_retries_per_task": 2
            },
            "repos": [
                {
                    "name": "red-eye-agent",
                    "url": "https://github.com/ah8571/red-eye-agent.git",
                    "branch_prefix": "agent/",
                    "default_branch": "main",
                    "test_command": "python -m unittest discover tests",
                    "install_command": "pip install -r requirements.txt",
                    "workspace_dir": "/workspace/red-eye-agent"
                }
            ]
        }
        
        errors = validate_config(config)
        self.assertEqual(errors, [], "Valid config should return empty error list")
    
    def test_config_invalid_provider_fails(self):
        """Test that config with invalid provider fails validation"""
        config = {
            "default_provider": "invalid_provider",  # Invalid provider
            "models": {
                "deepseek": {
                    "model": "deepseek-chat",
                    "max_tokens": 4096,
                    "temperature": 0.2
                }
            },
            "budget": {
                "max_tokens_per_task": 100000,
                "max_cost_per_run": 10.00,
                "max_retries_per_task": 2
            },
            "repos": [
                {
                    "name": "red-eye-agent",
                    "url": "https://github.com/ah8571/red-eye-agent.git"
                }
            ]
        }
        
        errors = validate_config(config)
        self.assertGreater(len(errors), 0, "Invalid config should return errors")
        
        # Check that the error mentions invalid provider
        provider_error_found = any(
            "invalid_provider" in error.lower() and "default_provider" in error.lower() 
            for error in errors
        )
        self.assertTrue(
            provider_error_found, 
            "Error message should mention invalid default_provider"
        )


if __name__ == '__main__':
    unittest.main()
