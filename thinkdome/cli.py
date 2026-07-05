"""ThinkDome CLI - Command-line interface for the ThinkDome server.

Usage::

    thinkdome serve --host 0.0.0.0 --port 8000
    thinkdome version
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="thinkdome",
        description="ThinkDome - Secure code execution sandbox for AI agents",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the ThinkDome API server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    serve_parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")

    # version command
    subparsers.add_parser("version", help="Show ThinkDome version")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute code in the sandbox")
    run_parser.add_argument("code", nargs="?", help="Code string to execute")
    run_parser.add_argument("-f", "--file", help="Path to a script file to execute")
    run_parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    run_parser.add_argument("--backend", default="auto", choices=["auto", "docker", "subprocess"])

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "version":
        _version()
    elif args.command == "run":
        _run(args)
    else:
        parser.print_help()
        sys.exit(1)


def _serve(args) -> None:
    """Start the FastAPI server."""
    import uvicorn

    print(f"Starting ThinkDome API server on {args.host}:{args.port}")
    uvicorn.run(
        "thinkdome.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
    )


def _version() -> None:
    """Print version info."""
    from thinkdome._version import __version__

    print(f"ThinkDome v{__version__}")


def _run(args) -> None:
    """Execute code in a sandbox."""
    from thinkdome import Sandbox

    code = args.code
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            code = f.read()

    if not code:
        print("Error: Provide code as an argument or use --file", file=sys.stderr)
        sys.exit(1)

    with Sandbox(timeout=args.timeout, backend=args.backend) as dome:
        result = dome.run(code)
        if result.output:
            print(result.output, end="")
        if result.error:
            print(result.error, file=sys.stderr, end="")
        sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
