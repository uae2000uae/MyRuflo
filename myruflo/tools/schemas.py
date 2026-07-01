"""Anthropic tool-use JSON schemas for MyRuflo's built-in tools."""

FILE_TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Read a text file from the workspace. Returns content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path relative to the workspace root"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file in the workspace with the given content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace root"},
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace an exact, unique substring in an existing file. Fails if old_string is not found or is not unique.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string", "description": "Exact text to find (must be unique in the file)"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_dir",
        "description": "List files and subdirectories at a path in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "glob_search",
        "description": "Find files in the workspace matching a glob pattern, e.g. '**/*.py'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search file contents in the workspace using a regular expression.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression"},
                "glob": {"type": "string", "default": "**/*", "description": "Glob to restrict which files are searched"},
                "path": {"type": "string", "default": "."},
            },
            "required": ["pattern"],
        },
    },
]

SHELL_TOOL_SCHEMA = {
    "name": "run_shell",
    "description": (
        "Run a shell command in the workspace root. Only available when the "
        "user has explicitly enabled shell access (MYRUFLO_ALLOW_SHELL=true)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 30, "description": "Seconds before the command is killed"},
        },
        "required": ["command"],
    },
}

MEMORY_TOOL_SCHEMAS = [
    {
        "name": "memory_store",
        "description": "Save a durable note (fact, decision, or finding) for later retrieval by yourself or other agents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Logical bucket, e.g. 'findings', 'decisions'"},
                "text": {"type": "string", "description": "The content to remember"},
            },
            "required": ["namespace", "text"],
        },
    },
    {
        "name": "memory_search",
        "description": "Search previously stored memory for relevant notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["namespace", "query"],
        },
    },
]
