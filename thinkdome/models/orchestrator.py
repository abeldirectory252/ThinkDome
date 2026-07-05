"""Pydantic schema models for orchestrator tool_use validation.

All tool input schemas are defined here as the single source of truth.
The JSON schema is auto-generated from these models via ToolUseRequest.model_json_schema().
"""

from __future__ import annotations

from typing import Literal, Optional, Union, Dict, List
from pydantic import BaseModel, Field, ValidationError


# â”€â”€ FILE SYSTEM TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ReadFileInput(BaseModel):
    path: str = Field(..., description="The path of the file to read.")


class WriteFileInput(BaseModel):
    path: str = Field(..., description="The destination path where the file will be written.")
    content: str = Field(..., description="The text content to write into the file.")


class RunCodeInput(BaseModel):
    code: str = Field(..., description="Source code to execute in the sandbox.")
    language: Optional[Literal["python"]] = Field(default="python", description="Programming language of the code.")
    stdin: Optional[str] = Field(default=None, description="Optional standard input to feed the execution process.")
    security_profile: Optional[Literal["HIGH_SECURITY", "ISOLATED", "DEVELOPMENT"]] = Field(
        default="HIGH_SECURITY", description="Containment security profile."
    )
    env_vars: Optional[Dict[str, str]] = Field(
        default=None, description="Optional custom environment variables to pass into the sandbox environment."
    )
    allow_network: Optional[bool] = Field(
        default=False, description="Whether to allow network egress."
    )


class ListDirInput(BaseModel):
    path: Optional[str] = Field(default=".", description="The directory path to list.")


class WebSearchInput(BaseModel):
    query: str = Field(..., description="The search query to query the web for.")
    max_results: Optional[int] = Field(default=10, description="Maximum number of search results to return.")


class FileExistsInput(BaseModel):
    path: str = Field(..., description="The file or directory path to check.")


class MakeDirInput(BaseModel):
    path: str = Field(..., description="The directory path to create.")


class RemoveFileInput(BaseModel):
    path: str = Field(..., description="The file path to delete.")


class RemoveDirInput(BaseModel):
    path: str = Field(..., description="The directory path to remove.")


class MoveFileInput(BaseModel):
    src: str = Field(..., description="Source file path.")
    dest: str = Field(..., description="Destination file path.")


class CopyFileInput(BaseModel):
    src: str = Field(..., description="Source file path.")
    dest: str = Field(..., description="Destination file path.")


class GrepSearchInput(BaseModel):
    pattern: str = Field(..., description="Regex pattern or text to search for.")
    path: Optional[str] = Field(default=".", description="Directory or file path to search under.")


class FindFilesInput(BaseModel):
    pattern: str = Field(..., description="Glob pattern (e.g. '*.py' or '**/test_*').")
    path: Optional[str] = Field(default=".", description="Directory path to search under.")


class GetFileInfoInput(BaseModel):
    path: str = Field(..., description="The file or directory path.")


class HashFileInput(BaseModel):
    path: str = Field(..., description="The file path to hash.")
    algorithm: Optional[Literal["md5", "sha256"]] = Field(default="sha256", description="Hash algorithm to use.")


# â”€â”€ API / HTTP REQUEST TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class HttpRequestInput(BaseModel):
    url: str = Field(..., description="The URL to send the HTTP request to.")
    method: Optional[Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]] = Field(
        default="GET", description="HTTP method."
    )
    headers: Optional[Dict[str, str]] = Field(default=None, description="Optional HTTP headers.")
    body: Optional[str] = Field(default=None, description="Optional request body (JSON string for POST/PUT/PATCH).")
    timeout: Optional[int] = Field(default=30, ge=1, le=120, description="Request timeout in seconds.")


# â”€â”€ MEMORY & KNOWLEDGE RETRIEVAL TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class MemoryStoreInput(BaseModel):
    key: str = Field(..., min_length=1, max_length=256, description="Unique key to store the memory under.")
    content: str = Field(..., description="The content/value to store.")
    tags: Optional[List[str]] = Field(default=None, description="Optional tags for categorization and retrieval.")


class MemoryRetrieveInput(BaseModel):
    key: str = Field(..., description="The key of the memory entry to retrieve.")


class MemorySearchInput(BaseModel):
    query: str = Field(..., description="Search query to find relevant memory entries.")
    limit: Optional[int] = Field(default=10, ge=1, le=100, description="Maximum number of results to return.")
    tags: Optional[List[str]] = Field(default=None, description="Optional tags to filter results by.")


class MemoryDeleteInput(BaseModel):
    key: str = Field(..., description="The key of the memory entry to delete.")


class MemoryListInput(BaseModel):
    tags: Optional[List[str]] = Field(default=None, description="Optional tags to filter by.")
    limit: Optional[int] = Field(default=50, ge=1, le=500, description="Maximum number of keys to return.")


# â”€â”€ SHELL / SYSTEM COMMAND TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ShellExecInput(BaseModel):
    command: str = Field(..., description="The shell command to execute.")
    timeout: Optional[int] = Field(default=30, ge=1, le=300, description="Command timeout in seconds.")
    cwd: Optional[str] = Field(default=None, description="Working directory for the command (defaults to workspace root).")


# â”€â”€ COMMUNICATION TOOLS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SendEmailInput(BaseModel):
    to: str = Field(..., description="Recipient email address.")
    subject: str = Field(..., max_length=500, description="Email subject line.")
    body: str = Field(..., description="Email body content (plain text or HTML).")
    html: Optional[bool] = Field(default=False, description="Whether the body is HTML formatted.")


class SendTelegramInput(BaseModel):
    chat_id: str = Field(..., description="Telegram chat ID or username to send the message to.")
    message: str = Field(..., description="The message text to send.")
    parse_mode: Optional[Literal["Markdown", "MarkdownV2", "HTML"]] = Field(
        default=None, description="Optional parse mode for message formatting."
    )


# â”€â”€ TOOL REGISTRY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

INPUT_MODELS = {
    # File system
    "read_file": ReadFileInput,
    "write_file": WriteFileInput,
    "run_code": RunCodeInput,
    "list_dir": ListDirInput,
    "web_search": WebSearchInput,
    "file_exists": FileExistsInput,
    "make_dir": MakeDirInput,
    "remove_file": RemoveFileInput,
    "remove_dir": RemoveDirInput,
    "move_file": MoveFileInput,
    "copy_file": CopyFileInput,
    "grep_search": GrepSearchInput,
    "find_files": FindFilesInput,
    "get_file_info": GetFileInfoInput,
    "hash_file": HashFileInput,
    # API / HTTP
    "http_request": HttpRequestInput,
    # Memory & Knowledge
    "memory_store": MemoryStoreInput,
    "memory_retrieve": MemoryRetrieveInput,
    "memory_search": MemorySearchInput,
    "memory_delete": MemoryDeleteInput,
    "memory_list": MemoryListInput,
    # Shell
    "shell_exec": ShellExecInput,
    # Communication
    "send_email": SendEmailInput,
    "send_telegram": SendTelegramInput,
}

# All valid tool names (auto-generated from the registry)
TOOL_NAMES = tuple(sorted(INPUT_MODELS.keys()))


class ToolUseRequest(BaseModel):
    type: Literal["tool_use"]
    id: str
    name: Literal[
        "copy_file", "file_exists", "find_files", "get_file_info", "grep_search",
        "hash_file", "http_request", "list_dir", "make_dir",
        "memory_delete", "memory_list", "memory_retrieve", "memory_search", "memory_store",
        "move_file", "read_file", "remove_dir", "remove_file", "run_code",
        "send_email", "send_telegram", "shell_exec",
        "web_search", "write_file"
    ]
    input: dict

    def validate_input(self) -> BaseModel:
        """Validate input field depending on the tool name."""
        model_cls = INPUT_MODELS.get(self.name)
        if not model_cls:
            raise ValueError(f"Unknown tool name: {self.name}")
        return model_cls.model_validate(self.input)

