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


# ── SHELL / SYSTEM COMMAND TOOLS ──────────────────────────────────────────────

class ShellExecInput(BaseModel):
    command: str = Field(..., description="The shell command to execute.")
    timeout: Optional[int] = Field(default=30, ge=1, le=300, description="Command timeout in seconds.")
    cwd: Optional[str] = Field(default=None, description="Working directory for the command (defaults to workspace root).")


# ── COMMUNICATION TOOLS ───────────────────────────────────────────────────────

class SendEmailInput(BaseModel):
    to: str = Field(..., description="Recipient email address.")
    subject: str = Field(..., max_length=500, description="Email subject line.")
    body: str = Field(..., description="Email body content (plain text or HTML).")
    html: Optional[bool] = Field(default=False, description="Whether the body is HTML formatted.")


class SendTelegramInput(BaseModel):
    chat_id: Optional[str] = Field(
        default=None,
        description="Telegram chat ID, username (e.g. @channelusername), or alias ('group', 'channel', 'person'). Defaults to configured .env setting if omitted."
    )
    message: str = Field(..., description="The message text to send.")
    parse_mode: Optional[Literal["Markdown", "MarkdownV2", "HTML"]] = Field(
        default=None, description="Optional parse mode for message formatting."
    )
    reply_to_message_id: Optional[int] = Field(
        default=None, description="Optional ID of the target message to reply to in a group or private chat."
    )
    disable_notification: Optional[bool] = Field(
        default=False, description="Send the message silently without triggering user notifications (great for channel broadcasts)."
    )
    pin_message: Optional[bool] = Field(
        default=False, description="Whether to automatically pin the message in the group or channel after sending."
    )


class TelegramGetUpdatesInput(BaseModel):
    offset: Optional[int] = Field(
        default=None, description="Identifier of the first update to be returned. Set to last update_id + 1 to acknowledge messages."
    )
    limit: Optional[int] = Field(
        default=20, ge=1, le=100, description="Limits the number of updates to be retrieved (1-100, default 20)."
    )
    timeout: Optional[int] = Field(
        default=0, ge=0, le=60, description="Timeout in seconds for long polling (0 for short polling)."
    )


class TelegramGetChatInput(BaseModel):
    chat_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the target chat, username, or alias ('group', 'channel', 'person'). Defaults to configured .env setting if omitted."
    )


class TelegramSendMediaInput(BaseModel):
    chat_id: Optional[str] = Field(
        default=None,
        description="Telegram chat ID, @channel_username, or alias ('group', 'channel', 'person'). Defaults to configured .env setting if omitted."
    )
    media_type: Literal["photo", "document", "audio", "video"] = Field(
        default="photo", description="Type of media to send: photo, document, audio, or video."
    )
    media_url: str = Field(..., description="Public HTTP/HTTPS URL or local file path of the media file.")
    caption: Optional[str] = Field(default=None, description="Optional caption for the media.")
    parse_mode: Optional[Literal["Markdown", "MarkdownV2", "HTML"]] = Field(
        default=None, description="Optional parse mode for caption formatting."
    )


class TelegramManageChatInput(BaseModel):
    chat_id: Optional[str] = Field(
        default=None,
        description="Target chat ID, channel username, or alias ('group', 'channel'). Defaults to configured .env setting if omitted."
    )
    action: Literal["pin_message", "unpin_message", "unpin_all_messages", "set_title", "set_description", "delete_message"] = Field(
        ..., description="Management action to perform."
    )
    message_id: Optional[int] = Field(
        default=None, description="Target message ID for pin, unpin, or delete actions."
    )
    text: Optional[str] = Field(
        default=None, description="New chat title or description when action is set_title or set_description."
    )


class SendWhatsAppInput(BaseModel):
    to: str = Field(..., description="Recipient phone number with country code (e.g. +1234567890 or whatsapp:+1234567890).")
    message: str = Field(..., description="Text message content to send.")
    media_url: Optional[str] = Field(
        default=None, description="Optional public media URL (image, PDF, audio) to attach to the message."
    )
    template_name: Optional[str] = Field(
        default=None, description="Optional pre-approved WhatsApp Business template name (for Meta Cloud API)."
    )
    template_language: Optional[str] = Field(
        default="en_US", description="Language code for the template (default en_US)."
    )
    provider: Optional[Literal["auto", "cloud_api", "twilio", "custom"]] = Field(
        default="auto", description="WhatsApp provider to use: auto (uses configured keys), cloud_api (Meta), twilio, or custom gateway."
    )


# ── WEB HOSTING TOOLS ───────────────────────────────────────────────────────

class HostHtmlInput(BaseModel):
    html: str = Field(..., description="The HTML content/markup to host and serve.")
    filename: Optional[str] = Field(default="index.html", description="Filename for the HTML page (default index.html).")
    site_name: Optional[str] = Field(default="hosted_site", description="Site directory name under workspace.")
    port: Optional[int] = Field(default=8080, description="Web server port to serve the HTML content on.")
    ttl_sec: Optional[int] = Field(default=300, description="Time-to-live in seconds before the hosted site automatically shuts down and times out (default 300s, supports custom values up to 86400s / 24 hours).")


# ── TOOL REGISTRY ─────────────────────────────────────────────────────────────

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
    # API / HTTP & Web Hosting
    "http_request": HttpRequestInput,
    "host_html": HostHtmlInput,
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
    "telegram_get_updates": TelegramGetUpdatesInput,
    "telegram_get_chat": TelegramGetChatInput,
    "telegram_send_media": TelegramSendMediaInput,
    "telegram_manage_chat": TelegramManageChatInput,
    "send_whatsapp": SendWhatsAppInput,
}

# All valid tool names (auto-generated from the registry)
TOOL_NAMES = tuple(sorted(INPUT_MODELS.keys()))


class ToolUseRequest(BaseModel):
    type: Literal["tool_use"]
    id: str
    name: Literal[
        "copy_file", "file_exists", "find_files", "get_file_info", "grep_search",
        "hash_file", "host_html", "http_request", "list_dir", "make_dir",
        "memory_delete", "memory_list", "memory_retrieve", "memory_search", "memory_store",
        "move_file", "read_file", "remove_dir", "remove_file", "run_code",
        "send_email", "send_telegram", "send_whatsapp", "shell_exec",
        "telegram_get_chat", "telegram_get_updates", "telegram_manage_chat", "telegram_send_media",
        "web_search", "write_file"
    ]
    input: dict

    def validate_input(self) -> BaseModel:
        """Validate input field depending on the tool name."""
        model_cls = INPUT_MODELS.get(self.name)
        if not model_cls:
            raise ValueError(f"Unknown tool name: {self.name}")
        return model_cls.model_validate(self.input)

