import json
import logging
from typing import Any
from thinkdome.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.core.config import get_settings
from thinkdome.orchestration.orchestrator_models import SendEmailInput, SendTelegramInput

logger = logging.getLogger(__name__)

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


@register_tool
class SendTelegramTool(BaseTool):
    name = "send_telegram"
    description = "Send a Telegram message via Bot API"
    required_scope = "comms:send"
    input_schema = SendTelegramInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        chat_id = tool_input.get("chat_id")
        message = tool_input.get("message")
        parse_mode = tool_input.get("parse_mode")

        if not chat_id or not message:
            raise ValueError("Parameters 'chat_id' and 'message' are required for send_telegram.")

        settings = get_settings()
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            raise RuntimeError(
                "Telegram not configured. Set TELEGRAM_BOT_TOKEN in .env"
            )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)

        resp_data = resp.json()
        if not resp_data.get("ok"):
            error_desc = resp_data.get("description", "Unknown Telegram API error")
            raise RuntimeError(f"Telegram API error: {error_desc}")

        logger.info(f"📬 Telegram message sent to {chat_id}")
        return json.dumps({
            "status": "sent",
            "chat_id": chat_id,
            "message_id": resp_data.get("result", {}).get("message_id")
        })
