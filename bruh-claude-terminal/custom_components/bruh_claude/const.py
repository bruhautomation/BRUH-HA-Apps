"""Constants for the BRUH Claude integration."""

DOMAIN = "bruh_claude"

CONF_TIMEOUT = "timeout"
CONF_NAME = "name"
CONF_SYSTEM_PROMPT = "system_prompt"
DEFAULT_TIMEOUT = 120
DEFAULT_NAME = "BRUH Claude"
DEFAULT_SYSTEM_PROMPT = ""

# Shared directory under /config for add-on <-> integration communication
SHARED_DIR = ".bruh_claude"
REQUESTS_DIR = "requests"
RESPONSES_DIR = "responses"
TASKS_DIR = "tasks"
TASK_RESULTS_DIR = "task_results"
