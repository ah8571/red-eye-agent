import os
from pathlib import Path

# Secret key for session security
SECRET_KEY = os.getenv('WEB_SECRET_KEY', os.urandom(32).hex())

# Allowed emails for dashboard access
ALLOWED_EMAILS = [
    email.strip()
    for email in os.getenv('ALLOWED_EMAILS', 'founder@connectionism.io').split(',')
    if email.strip()
]

# Session expiration (24 hours)
SESSION_MAX_AGE = 86400

# Path to agent configuration files
BASE_DIR = Path(__file__).parent.parent
AGENT_CONFIG_PATH = BASE_DIR / 'config.yaml'
AGENT_CHECKLIST_PATH = BASE_DIR / 'checklist.yaml'
AGENT_LOG_DIR = BASE_DIR / 'logs'
