"""Unit tests for Telegram and WhatsApp communication tools in ThinkDome."""

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock

from thinkdome.platform.orchestration.tools import registry
from thinkdome.core.config import get_settings


@pytest.fixture(autouse=True)
def configure_test_settings(monkeypatch):
    """Set mock test tokens for Telegram and WhatsApp."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_telegram_token_12345")
    monkeypatch.setenv("WHATSAPP_PROVIDER", "cloud_api")
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "mock_whatsapp_token_67890")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "100012345678901")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── TELEGRAM TESTS ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telegram_send_message_direct():
    """Test sending direct message to a user."""
    tool = registry.get_tool("send_telegram")
    assert tool is not None

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 999}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "chat_id": "12345678",
            "message": "Hello from ThinkDome Assistant!",
            "parse_mode": "HTML",
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["chat_id"] == "12345678"
        assert result["message_id"] == 999
        assert result["pinned"] is False

        # Verify payload sent to Telegram API
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "sendMessage" in call_args[0][0]
        assert call_args[1]["json"]["chat_id"] == "12345678"
        assert call_args[1]["json"]["text"] == "Hello from ThinkDome Assistant!"
        assert call_args[1]["json"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_telegram_chat_in_group_with_reply():
    """Test chatting in a group with reply_to_message_id."""
    tool = registry.get_tool("send_telegram")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 1001}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "chat_id": "-1001234567890",
            "message": "I agree with that point!",
            "reply_to_message_id": 42,
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["message_id"] == 1001
        assert result["reply_to_message_id"] == 42

        call_args = mock_post.call_args
        assert call_args[1]["json"]["chat_id"] == "-1001234567890"
        assert call_args[1]["json"]["reply_to_message_id"] == 42


@pytest.mark.asyncio
async def test_telegram_post_to_channel_with_pin():
    """Test posting an announcement to a channel silently and auto-pinning it."""
    tool = registry.get_tool("send_telegram")

    mock_msg_resp = MagicMock()
    mock_msg_resp.json.return_value = {"ok": True, "result": {"message_id": 2002}}

    mock_pin_resp = MagicMock()
    mock_pin_resp.json.return_value = {"ok": True, "result": True}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_msg_resp, mock_pin_resp]

        result_str = await tool.func({
            "chat_id": "@thinkdome_updates",
            "message": "Important update released!",
            "disable_notification": True,
            "pin_message": True,
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["message_id"] == 2002
        assert result["pinned"] is True

        assert mock_post.call_count == 2
        # First call: sendMessage
        assert "sendMessage" in mock_post.call_args_list[0][0][0]
        assert mock_post.call_args_list[0][1]["json"]["disable_notification"] is True
        # Second call: pinChatMessage
        assert "pinChatMessage" in mock_post.call_args_list[1][0][0]
        assert mock_post.call_args_list[1][1]["json"]["message_id"] == 2002


@pytest.mark.asyncio
async def test_telegram_get_updates():
    """Test reading incoming messages and updates from Telegram."""
    tool = registry.get_tool("telegram_get_updates")
    assert tool is not None

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "ok": True,
        "result": [
            {
                "update_id": 501,
                "message": {
                    "message_id": 10,
                    "date": 1600000000,
                    "chat": {"id": 12345, "type": "private", "username": "alice"},
                    "from": {"id": 12345, "username": "alice", "first_name": "Alice", "is_bot": False},
                    "text": "What is the status of the deployment?",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        result_str = await tool.func({"limit": 10})
        result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["next_offset"] == 502
        first_upd = result["updates"][0]
        assert first_upd["update_id"] == 501
        assert first_upd["text"] == "What is the status of the deployment?"
        assert first_upd["sender"]["username"] == "alice"


@pytest.mark.asyncio
async def test_telegram_get_chat():
    """Test retrieving chat details."""
    tool = registry.get_tool("telegram_get_chat")
    assert tool is not None

    mock_chat_resp = MagicMock()
    mock_chat_resp.json.return_value = {
        "ok": True,
        "result": {
            "id": -1001234567890,
            "type": "supergroup",
            "title": "ThinkDome Engineering",
            "username": "thinkdome_eng",
            "description": "Core engineering discussion",
        }
    }

    mock_count_resp = MagicMock()
    mock_count_resp.json.return_value = {"ok": True, "result": 48}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_chat_resp, mock_count_resp]

        result_str = await tool.func({"chat_id": "-1001234567890"})
        result = json.loads(result_str)

        assert result["title"] == "ThinkDome Engineering"
        assert result["type"] == "supergroup"
        assert result["member_count"] == 48


@pytest.mark.asyncio
async def test_telegram_send_media():
    """Test sending media via URL."""
    tool = registry.get_tool("telegram_send_media")
    assert tool is not None

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 3003}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "chat_id": "@thinkdome_updates",
            "media_type": "photo",
            "media_url": "https://example.com/architecture.png",
            "caption": "New Architecture Diagram",
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["media_type"] == "photo"
        assert result["message_id"] == 3003

        call_args = mock_post.call_args
        assert "sendPhoto" in call_args[0][0]
        assert call_args[1]["data"]["photo"] == "https://example.com/architecture.png"
        assert call_args[1]["data"]["caption"] == "New Architecture Diagram"


@pytest.mark.asyncio
async def test_telegram_manage_chat_pin():
    """Test pinning a message in chat."""
    tool = registry.get_tool("telegram_manage_chat")
    assert tool is not None

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": True}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "chat_id": "-1001234567890",
            "action": "pin_message",
            "message_id": 1001,
        })

        result = json.loads(result_str)
        assert result["status"] == "success"
        assert result["action"] == "pin_message"
        assert "pinChatMessage" in mock_post.call_args[0][0]


# ── WHATSAPP TESTS ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_whatsapp_cloud_api():
    """Test sending WhatsApp message via Meta Cloud API."""
    tool = registry.get_tool("send_whatsapp")
    assert tool is not None

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "messaging_product": "whatsapp",
        "contacts": [{"wa_id": "15551234567"}],
        "messages": [{"id": "wamid.HBgLMTU1NTEyMzQ1NjcVAgASGBQz"}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "to": "+1 (555) 123-4567",
            "message": "Hello from WhatsApp tool!",
            "provider": "cloud_api",
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["provider"] == "cloud_api"
        assert result["to"] == "+15551234567"
        assert "wamid." in result["message_id"]

        call_args = mock_post.call_args
        assert "graph.facebook.com" in call_args[0][0]
        assert call_args[1]["json"]["messaging_product"] == "whatsapp"
        assert call_args[1]["json"]["to"] == "15551234567"
        assert call_args[1]["json"]["text"]["body"] == "Hello from WhatsApp tool!"


@pytest.mark.asyncio
async def test_send_whatsapp_cloud_api_template():
    """Test sending a pre-approved template via Meta Cloud API."""
    tool = registry.get_tool("send_whatsapp")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "messaging_product": "whatsapp",
        "messages": [{"id": "wamid.template_msg_123"}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "to": "+15551234567",
            "template_name": "hello_world",
            "template_language": "en_US",
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["message_id"] == "wamid.template_msg_123"

        call_args = mock_post.call_args
        assert call_args[1]["json"]["type"] == "template"
        assert call_args[1]["json"]["template"]["name"] == "hello_world"


@pytest.mark.asyncio
async def test_send_whatsapp_twilio(monkeypatch):
    """Test sending WhatsApp message via Twilio provider."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACmockaccount12345")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "mockauthtoken67890")
    monkeypatch.setenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
    get_settings.cache_clear()

    tool = registry.get_tool("send_whatsapp")

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "sid": "SMmockmessagesid12345",
        "status": "queued",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        result_str = await tool.func({
            "to": "+15559876543",
            "message": "Twilio WhatsApp test message",
            "provider": "twilio",
        })

        result = json.loads(result_str)
        assert result["status"] == "sent"
        assert result["provider"] == "twilio"
        assert result["message_id"] == "SMmockmessagesid12345"

        call_args = mock_post.call_args
        assert "api.twilio.com" in call_args[0][0]
        assert call_args[1]["data"]["To"] == "whatsapp:+15559876543"
        assert call_args[1]["data"]["Body"] == "Twilio WhatsApp test message"


@pytest.mark.asyncio
async def test_send_whatsapp_missing_credentials(monkeypatch):
    """Test clear error when credentials are not configured."""
    monkeypatch.setenv("WHATSAPP_API_TOKEN", "")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    get_settings.cache_clear()

    tool = registry.get_tool("send_whatsapp")

    with pytest.raises(RuntimeError) as excinfo:
        await tool.func({
            "to": "+15551234567",
            "message": "This should fail because no credentials",
            "provider": "cloud_api",
        })

    assert "WhatsApp Cloud API not configured" in str(excinfo.value)


@pytest.mark.asyncio
async def test_telegram_resolve_group_and_channel_from_env(monkeypatch):
    """Test resolving 'group' and 'channel' aliases from environment configuration."""
    monkeypatch.setenv("TELEGRAM_GROUP_NAME", "@my_engineering_group")
    monkeypatch.setenv("TELEGRAM_CHANNEL_NAME", "@my_announcements_channel")
    get_settings.cache_clear()

    tool = registry.get_tool("send_telegram")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 777}}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        # Send to alias 'group'
        res_group = await tool.func({"chat_id": "group", "message": "Hello Group!"})
        data_group = json.loads(res_group)
        assert data_group["chat_id"] == "@my_engineering_group"
        assert mock_post.call_args[1]["json"]["chat_id"] == "@my_engineering_group"

        # Send to alias 'channel'
        res_channel = await tool.func({"chat_id": "channel", "message": "Hello Channel!"})
        data_channel = json.loads(res_channel)
        assert data_channel["chat_id"] == "@my_announcements_channel"
        assert mock_post.call_args[1]["json"]["chat_id"] == "@my_announcements_channel"
