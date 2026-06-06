"""ThinkDome - Secure code execution sandbox for AI agents.

Basic usage::

    from thinkdome import Sandbox

    with Sandbox() as dome:
        result = dome.run("print('Hello from ThinkDome!')")
        print(result.output)

Or as a FastAPI server::

    thinkdome serve --host 0.0.0.0 --port 8000
"""

from thinkdome._version import __version__
from thinkdome.sandbox import Sandbox, SandboxResult

__all__ = ["Sandbox", "SandboxResult", "__version__"]
