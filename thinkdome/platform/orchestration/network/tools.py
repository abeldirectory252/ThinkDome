import json
from typing import Any
from thinkdome.platform.orchestration.tools import BaseTool, register_tool, get_context
from thinkdome.core.config import get_settings
from thinkdome.platform.orchestration.orchestrator_models import HttpRequestInput

@register_tool
class HttpRequestTool(BaseTool):
    name = "http_request"
    description = "Send outbound HTTP requests to APIs"
    required_scope = "network:all"
    input_schema = HttpRequestInput

    async def execute(self, tool_input: dict[str, Any]) -> str:
        import httpx

        url = tool_input.get("url")
        if not url:
            raise ValueError("Parameter 'url' is required for http_request.")

        method = (tool_input.get("method", "GET")).upper()
        headers = tool_input.get("headers") or {}
        body = tool_input.get("body")
        timeout = min(tool_input.get("timeout", 30), 120)

        settings = get_settings()

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )

        body_text = response.text[:settings.MAX_OUTPUT_BYTES]
        return json.dumps({
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body_text,
            "url": str(response.url),
            "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 2)
        })
