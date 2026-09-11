import json
import logging
from typing import Any
from pathlib import Path
from thinkdome.platform.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.core.config import get_settings
from thinkdome.platform.orchestration.orchestrator_models import (
    SendEmailInput,
    SendTelegramInput,
    TelegramGetUpdatesInput,
    TelegramGetChatInput,
    TelegramSendMediaInput,
    TelegramManageChatInput,
    SendWhatsAppInput,
)

logger = logging.getLogger(__name__)


# ── EMAIL TOOLS ───────────────────────────────────────────────────────────────

@register_tool
class SendEmailTool(BaseTool):
    name = "send_email"
    description = "Send an email via SMTP server"
    required_scope = "comms:send"
    input_schema = SendEmailInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        to = tool_input.get("to")
        subject = tool_input.get("subject")
        body = tool_input.get("body")
        is_html = tool_input.get("html", False)

        if not to or not subject or not body:
            raise ValueError("Parameters 'to', 'subject', and 'body' are required for send_email.")

        settings = get_settings()
        if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            raise RuntimeError(
                "Email not configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD in .env"
            )

        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject

        content_type = "html" if is_html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
                logger.info(f"📧 Email sent to {to} (subject: {subject})")
        except Exception as e:
            raise RuntimeError(f"Failed to send email: {e}")

        return json.dumps({"status": "sent", "to": to, "subject": subject})


# ── TELEGRAM TOOLS ────────────────────────────────────────────────────────────

def resolve_telegram_chat_id(target: str | None, default_type: str = "auto") -> str:
    """Resolve target Telegram chat identifier from parameter or environment configuration."""
    settings = get_settings()
    raw = (target or "").strip()
    low = raw.lower()

    if low in ("group", "default_group", "g"):
        val = settings.TELEGRAM_GROUP_ID or settings.TELEGRAM_GROUP_NAME
        if val:
            return val
        raise ValueError("No Telegram group configured in .env. Set TELEGRAM_GROUP_NAME or TELEGRAM_GROUP_ID in .env.")

    if low in ("channel", "default_channel", "c"):
        val = settings.TELEGRAM_CHANNEL_ID or settings.TELEGRAM_CHANNEL_NAME
        if val:
            return val
        raise ValueError("No Telegram channel configured in .env. Set TELEGRAM_CHANNEL_NAME or TELEGRAM_CHANNEL_ID in .env.")

    if low in ("person", "dm", "user", "me", "default_user", "default_person", "p"):
        val = settings.TELEGRAM_DEFAULT_CHAT_ID
        if val:
            return val
        raise ValueError("No default Telegram user configured in .env. Set TELEGRAM_DEFAULT_CHAT_ID in .env.")

    # Match by group/channel name if caller passed the configured name
    if settings.TELEGRAM_GROUP_NAME and low == settings.TELEGRAM_GROUP_NAME.lower().strip():
        return settings.TELEGRAM_GROUP_ID or settings.TELEGRAM_GROUP_NAME
    if settings.TELEGRAM_CHANNEL_NAME and low == settings.TELEGRAM_CHANNEL_NAME.lower().strip():
        return settings.TELEGRAM_CHANNEL_ID or settings.TELEGRAM_CHANNEL_NAME

    # If no target specified at all, use intelligent fallback
    if not raw:
        if default_type == "group":
            val = settings.TELEGRAM_GROUP_ID or settings.TELEGRAM_GROUP_NAME
            if val:
                return val
        elif default_type == "channel":
            val = settings.TELEGRAM_CHANNEL_ID or settings.TELEGRAM_CHANNEL_NAME
            if val:
                return val
        elif default_type == "person":
            val = settings.TELEGRAM_DEFAULT_CHAT_ID
            if val:
                return val

        # Generic fallback order: group -> channel -> default personal chat id
        val = (
            settings.TELEGRAM_GROUP_ID
            or settings.TELEGRAM_GROUP_NAME
            or settings.TELEGRAM_CHANNEL_ID
            or settings.TELEGRAM_CHANNEL_NAME
            or settings.TELEGRAM_DEFAULT_CHAT_ID
        )
        if val:
            return val
        raise ValueError(
            "Parameter 'chat_id' is required or configure TELEGRAM_GROUP_NAME, "
            "TELEGRAM_CHANNEL_NAME, or TELEGRAM_DEFAULT_CHAT_ID in .env."
        )

    return raw


@register_tool
class SendTelegramTool(BaseTool):
    name = "send_telegram"
    description = "Send a Telegram message to a person, group, or channel via Bot API"
    required_scope = "comms:send"
    input_schema = SendTelegramInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        raw_chat_id = tool_input.get("chat_id")
        chat_id = resolve_telegram_chat_id(raw_chat_id)
        message = tool_input.get("message")
        parse_mode = tool_input.get("parse_mode")
        reply_to_message_id = tool_input.get("reply_to_message_id")
        disable_notification = tool_input.get("disable_notification", False)
        pin_message = tool_input.get("pin_message", False)

        if not message:
            raise ValueError("Parameter 'message' is required for send_telegram.")

        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env"
            )

        base_url = f"https://api.telegram.org/bot{token}"
        payload: dict[str, Any] = {"chat_id": chat_id, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if disable_notification:
            payload["disable_notification"] = True

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{base_url}/sendMessage", json=payload)
            resp_data = resp.json()
            if not resp_data.get("ok"):
                error_desc = resp_data.get("description", "Unknown Telegram API error")
                raise RuntimeError(f"Telegram API error: {error_desc}")

            result = resp_data.get("result", {})
            message_id = result.get("message_id")

            pinned = False
            if pin_message and message_id:
                try:
                    pin_resp = await client.post(
                        f"{base_url}/pinChatMessage",
                        json={"chat_id": chat_id, "message_id": message_id, "disable_notification": disable_notification}
                    )
                    pinned = pin_resp.json().get("ok", False)
                except Exception as pe:
                    logger.warning(f"Failed to pin telegram message {message_id}: {pe}")

        logger.info(f"📬 Telegram message sent to {chat_id} (id: {message_id})")
        return json.dumps({
            "status": "sent",
            "chat_id": chat_id,
            "message_id": message_id,
            "pinned": pinned,
            "reply_to_message_id": reply_to_message_id,
        })


@register_tool
class TelegramGetUpdatesTool(BaseTool):
    name = "telegram_get_updates"
    description = "Read incoming messages, mentions, and updates from Telegram chats, groups, and channels"
    required_scope = "comms:send"
    input_schema = TelegramGetUpdatesInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        offset = tool_input.get("offset")
        limit = tool_input.get("limit", 20)
        timeout = tool_input.get("timeout", 0)

        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError("Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env")

        params: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        url = f"https://api.telegram.org/bot{token}/getUpdates"
        async with httpx.AsyncClient(timeout=max(35, timeout + 5)) as client:
            resp = await client.get(url, params=params)

        resp_data = resp.json()
        if not resp_data.get("ok"):
            error_desc = resp_data.get("description", "Unknown Telegram API error")
            raise RuntimeError(f"Telegram API error: {error_desc}")

        raw_updates = resp_data.get("result", [])
        parsed_updates = []
        for upd in raw_updates:
            upd_id = upd.get("update_id")
            msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message")
            if not msg:
                continue

            chat = msg.get("chat", {})
            sender = msg.get("from", {})
            parsed_updates.append({
                "update_id": upd_id,
                "message_id": msg.get("message_id"),
                "date": msg.get("date"),
                "chat": {
                    "id": chat.get("id"),
                    "type": chat.get("type"),
                    "title": chat.get("title"),
                    "username": chat.get("username"),
                },
                "sender": {
                    "id": sender.get("id"),
                    "username": sender.get("username"),
                    "first_name": sender.get("first_name"),
                    "is_bot": sender.get("is_bot", False),
                },
                "text": msg.get("text") or msg.get("caption", ""),
                "reply_to_message_id": msg.get("reply_to_message", {}).get("message_id") if msg.get("reply_to_message") else None,
            })

        latest_offset = (raw_updates[-1]["update_id"] + 1) if raw_updates else offset
        return json.dumps({
            "status": "success",
            "count": len(parsed_updates),
            "next_offset": latest_offset,
            "updates": parsed_updates,
        })


@register_tool
class TelegramGetChatTool(BaseTool):
    name = "telegram_get_chat"
    description = "Retrieve details and metadata about a Telegram user, group, or channel"
    required_scope = "comms:send"
    input_schema = TelegramGetChatInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        raw_chat_id = tool_input.get("chat_id")
        chat_id = resolve_telegram_chat_id(raw_chat_id)

        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError("Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env")

        base_url = f"https://api.telegram.org/bot{token}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{base_url}/getChat", params={"chat_id": chat_id})
            resp_data = resp.json()
            if not resp_data.get("ok"):
                error_desc = resp_data.get("description", "Unknown Telegram API error")
                raise RuntimeError(f"Telegram API error: {error_desc}")

            chat_info = resp_data.get("result", {})

            # Attempt to fetch member count if it's a group or channel
            member_count = None
            if chat_info.get("type") in ("group", "supergroup", "channel"):
                try:
                    count_resp = await client.get(f"{base_url}/getChatMemberCount", params={"chat_id": chat_id})
                    if count_resp.json().get("ok"):
                        member_count = count_resp.json().get("result")
                except Exception:
                    pass

        return json.dumps({
            "id": chat_info.get("id"),
            "type": chat_info.get("type"),
            "title": chat_info.get("title"),
            "username": chat_info.get("username"),
            "description": chat_info.get("description"),
            "member_count": member_count,
            "invite_link": chat_info.get("invite_link"),
        })


@register_tool
class TelegramSendMediaTool(BaseTool):
    name = "telegram_send_media"
    description = "Send media (photo, document, audio, video) to a Telegram user, group, or channel"
    required_scope = "comms:send"
    input_schema = TelegramSendMediaInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        raw_chat_id = tool_input.get("chat_id")
        chat_id = resolve_telegram_chat_id(raw_chat_id)
        media_type = tool_input.get("media_type", "photo")
        media_url = tool_input.get("media_url")
        caption = tool_input.get("caption")
        parse_mode = tool_input.get("parse_mode")

        if not media_url:
            raise ValueError("Parameter 'media_url' is required for telegram_send_media.")

        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError("Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env")

        endpoint_map = {
            "photo": "sendPhoto",
            "document": "sendDocument",
            "audio": "sendAudio",
            "video": "sendVideo",
        }
        method = endpoint_map.get(media_type, "sendPhoto")
        field_name = media_type

        base_url = f"https://api.telegram.org/bot{token}/{method}"

        async with httpx.AsyncClient(timeout=60) as client:
            # Check if media_url is a public web URL or a local file
            if media_url.startswith("http://") or media_url.startswith("https://"):
                data = {"chat_id": chat_id, field_name: media_url}
                if caption:
                    data["caption"] = caption
                if parse_mode:
                    data["parse_mode"] = parse_mode
                resp = await client.post(base_url, data=data)
            else:
                # Local file upload from workspace
                file_path = Path(media_url)
                if not file_path.exists():
                    try:
                        ctx = get_context()
                        file_path = ctx.workspace_dir / media_url.lstrip("/\\")
                    except Exception:
                        pass

                if not file_path.exists():
                    raise FileNotFoundError(f"Local media file not found: {media_url}")

                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                if parse_mode:
                    data["parse_mode"] = parse_mode

                with file_path.open("rb") as f:
                    files = {field_name: (file_path.name, f.read())}
                    resp = await client.post(base_url, data=data, files=files)

        resp_data = resp.json()
        if not resp_data.get("ok"):
            error_desc = resp_data.get("description", "Unknown Telegram API error")
            raise RuntimeError(f"Telegram API error: {error_desc}")

        msg_result = resp_data.get("result", {})
        return json.dumps({
            "status": "sent",
            "chat_id": chat_id,
            "media_type": media_type,
            "message_id": msg_result.get("message_id"),
        })


@register_tool
class TelegramManageChatTool(BaseTool):
    name = "telegram_manage_chat"
    description = "Manage a Telegram chat, group, or channel (pin/unpin messages, set title/description, delete messages)"
    required_scope = "comms:send"
    input_schema = TelegramManageChatInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        raw_chat_id = tool_input.get("chat_id")
        chat_id = resolve_telegram_chat_id(raw_chat_id)
        action = tool_input.get("action")
        message_id = tool_input.get("message_id")
        text = tool_input.get("text")

        if not action:
            raise ValueError("Parameter 'action' is required for telegram_manage_chat.")

        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError("Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env")

        base_url = f"https://api.telegram.org/bot{token}"

        async with httpx.AsyncClient(timeout=30) as client:
            if action == "pin_message":
                if not message_id:
                    raise ValueError("Parameter 'message_id' is required to pin a message.")
                resp = await client.post(f"{base_url}/pinChatMessage", json={"chat_id": chat_id, "message_id": message_id})
            elif action == "unpin_message":
                payload: dict[str, Any] = {"chat_id": chat_id}
                if message_id:
                    payload["message_id"] = message_id
                resp = await client.post(f"{base_url}/unpinChatMessage", json=payload)
            elif action == "unpin_all_messages":
                resp = await client.post(f"{base_url}/unpinAllChatMessages", json={"chat_id": chat_id})
            elif action == "set_title":
                if not text:
                    raise ValueError("Parameter 'text' is required to set chat title.")
                resp = await client.post(f"{base_url}/setChatTitle", json={"chat_id": chat_id, "title": text})
            elif action == "set_description":
                resp = await client.post(f"{base_url}/setChatDescription", json={"chat_id": chat_id, "description": text or ""})
            elif action == "delete_message":
                if not message_id:
                    raise ValueError("Parameter 'message_id' is required to delete a message.")
                resp = await client.post(f"{base_url}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id})
            else:
                raise ValueError(f"Unsupported action: {action}")

        resp_data = resp.json()
        if not resp_data.get("ok"):
            error_desc = resp_data.get("description", "Unknown Telegram API error")
            raise RuntimeError(f"Telegram API error: {error_desc}")

        return json.dumps({
            "status": "success",
            "action": action,
            "chat_id": chat_id,
            "result": resp_data.get("result"),
        })


# ── WHATSAPP TOOLS ────────────────────────────────────────────────────────────

@register_tool
class SendWhatsAppTool(BaseTool):
    name = "send_whatsapp"
    description = "Send a WhatsApp message or template to a phone number or group via WhatsApp Cloud API or Twilio"
    required_scope = "comms:send"
    input_schema = SendWhatsAppInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        to = str(tool_input.get("to", "")).strip()
        message = tool_input.get("message", "")
        media_url = tool_input.get("media_url")
        template_name = tool_input.get("template_name")
        template_language = tool_input.get("template_language", "en_US")
        provider = tool_input.get("provider", "auto")

        if not to:
            raise ValueError("Parameter 'to' (recipient phone number) is required for send_whatsapp.")
        if not message and not template_name:
            raise ValueError("Either 'message' or 'template_name' is required for send_whatsapp.")

        settings = get_settings()

        # Clean and normalize recipient phone number using regex
        import re
        digits = re.sub(r"\D", "", to)
        clean_to = f"+{digits}" if digits else to.strip()

        # Auto-detect provider if "auto"
        selected_provider = provider
        if selected_provider == "auto":
            if settings.WHATSAPP_API_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID:
                selected_provider = "cloud_api"
            elif settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
                selected_provider = "twilio"
            elif settings.WHATSAPP_API_URL:
                selected_provider = "custom"
            else:
                selected_provider = settings.WHATSAPP_PROVIDER or "cloud_api"

        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Meta WhatsApp Cloud API (Graph API)
            if selected_provider == "cloud_api":
                token = settings.WHATSAPP_API_TOKEN
                phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID

                if not token or not phone_number_id:
                    raise RuntimeError(
                        "WhatsApp Cloud API not configured. Set WHATSAPP_API_TOKEN and "
                        "WHATSAPP_PHONE_NUMBER_ID in .env (or configure TWILIO credentials)."
                    )

                # Normalize recipient phone number (digits only for Cloud API, leading + stripped)
                recipient_digits = digits
                url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }

                if template_name:
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": recipient_digits,
                        "type": "template",
                        "template": {
                            "name": template_name,
                            "language": {"code": template_language},
                        },
                    }
                elif media_url:
                    is_image = any(media_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"])
                    media_key = "image" if is_image else "document"
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": recipient_digits,
                        "type": media_key,
                        media_key: {
                            "link": media_url,
                            "caption": message,
                        },
                    }
                else:
                    payload = {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": recipient_digits,
                        "type": "text",
                        "text": {"preview_url": True, "body": message},
                    }

                resp = await client.post(url, json=payload, headers=headers)
                resp_data = resp.json()
                if resp.status_code >= 400 or "error" in resp_data:
                    error_msg = resp_data.get("error", {}).get("message", resp.text)
                    raise RuntimeError(f"WhatsApp Cloud API error: {error_msg}")

                msg_id = (resp_data.get("messages", [{}])[0]).get("id", "sent")
                logger.info(f"📱 WhatsApp sent via Cloud API to {clean_to} (id: {msg_id})")
                return json.dumps({
                    "status": "sent",
                    "provider": "cloud_api",
                    "to": clean_to,
                    "message_id": msg_id,
                })

            # 2. Twilio WhatsApp API
            elif selected_provider == "twilio":
                sid = settings.TWILIO_ACCOUNT_SID
                auth_token = settings.TWILIO_AUTH_TOKEN
                from_number = settings.TWILIO_WHATSAPP_NUMBER or "whatsapp:+14155238886"

                if not sid or not auth_token:
                    raise RuntimeError("Twilio not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env")

                url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
                formatted_to = f"whatsapp:{clean_to}" if not clean_to.startswith("whatsapp:") else clean_to
                formatted_from = f"whatsapp:{from_number}" if not from_number.startswith("whatsapp:") else from_number

                data = {
                    "From": formatted_from,
                    "To": formatted_to,
                    "Body": message,
                }
                if media_url:
                    data["MediaUrl"] = media_url

                resp = await client.post(url, data=data, auth=(sid, auth_token))
                resp_data = resp.json()
                if resp.status_code >= 400:
                    error_msg = resp_data.get("message", resp.text)
                    raise RuntimeError(f"Twilio WhatsApp error: {error_msg}")

                msg_sid = resp_data.get("sid", "sent")
                logger.info(f"📱 WhatsApp sent via Twilio to {formatted_to} (sid: {msg_sid})")
                return json.dumps({
                    "status": "sent",
                    "provider": "twilio",
                    "to": formatted_to,
                    "message_id": msg_sid,
                })

            # 3. Custom HTTP Gateway / Webhook
            elif selected_provider == "custom":
                gateway_url = settings.WHATSAPP_API_URL
                if not gateway_url:
                    raise RuntimeError("Custom WhatsApp gateway not configured. Set WHATSAPP_API_URL in .env")

                payload = {
                    "to": clean_to,
                    "message": message,
                    "media_url": media_url,
                }
                resp = await client.post(gateway_url, json=payload)
                if resp.status_code >= 400:
                    raise RuntimeError(f"Custom WhatsApp gateway error (HTTP {resp.status_code}): {resp.text}")

                return json.dumps({
                    "status": "sent",
                    "provider": "custom",
                    "to": clean_to,
                    "response": resp.text[:200],
                })

            else:
                raise ValueError(f"Unknown WhatsApp provider: {selected_provider}")
