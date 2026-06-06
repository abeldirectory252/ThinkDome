# thinkBox 🧠📦

> Secure, isolated code execution sandbox for AI agents and applications.

thinkBox is a lightweight FastAPI application that provides secure code execution capabilities. It supports multiple programming languages (currently Python, with C++, Java, and C# planned) and runs code in isolated environments using Docker or subprocess execution.

## Features

- **Secure Execution**: Code runs in isolated containers or subprocesses
- **Multi-Language Support**: Python (primary), with stubs for C++, Java, C#
- **File Management**: Upload, download, and manage files for execution
- **Session Management**: Persistent execution sessions for REPL-like workflows
- **Workspace Management**: Isolated workspaces with snapshots and restores
- **Streaming Execution**: Real-time output via Server-Sent Events
- **API Key Authentication**: Optional security for production use
- **Health Checks**: Readiness and liveness probes
- **Docker Integration**: Out-of-the-box containerization

## Quick Start

### Prerequisites

- Python 3.11+ (for subprocess mode)
- Docker (for Docker mode)

### Option 1: Docker Mode (Recommended for Production)

```bash
# Clone and navigate to the repo
cd thinkbox

# Start with Docker Compose
docker compose up --build
```

This runs the app in a container with Docker-in-Docker support.

### Option 2: Development Mode (No Docker Required)

```bash
# Clone and navigate to the repo
cd thinkbox

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure for subprocess execution
echo "EXECUTOR_BACKEND=subprocess" > .env

# Run the app
python -m app.main
```

The app will be available at `http://localhost:8000`.

## Configuration

Create a `.env` file in the project root to customize settings:

```env
# Server
HOST=0.0.0.0
PORT=8000

# Execution Backend: "docker" or "subprocess"
EXECUTOR_BACKEND=subprocess

# Security (optional)
API_KEY=your-secret-key
```

See `.env` for all available options with comments.

## API Documentation

The API is documented at `http://localhost:8000/docs` when running.

### Authentication

If `API_KEY` is set in configuration, include it in requests:

```bash
curl -H "X-API-Key: your-secret-key" ...
```

Requests without a valid key will be rejected if authentication is enabled.

### Endpoints

#### Health

- **GET /health** - Liveness check
  ```bash
  curl http://localhost:8000/health
  # {"status": "ok"}
  ```

- **GET /ready** - Readiness check with executor status
  ```bash
  curl http://localhost:8000/ready
  # {"status": "ready", "executors": {"python": true}}
  ```

#### Execution

- **POST /execute** - Execute code snippet
  ```bash
  curl -X POST http://localhost:8000/execute \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{
      "code": "print(\"Hello, World!\")",
      "language": "python"
    }'
  # {"stdout": "Hello, World!\n", "exit_code": 0, ...}
  ```

- **POST /execute/batch** - Execute multiple code blocks
  ```bash
  curl -X POST http://localhost:8000/execute/batch \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{
      "executions": [
        {"code": "x = 1", "language": "python"},
        {"code": "print(x + 1)", "language": "python"}
      ]
    }'
  ```

- **POST /execute/stream** - Stream execution output
  ```bash
  curl -X POST http://localhost:8000/execute/stream \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{
      "code": "import time; [print(f\"Step {i}\") or time.sleep(0.1) for i in range(3)]",
      "language": "python"
    }'
  ```

#### Files

- **POST /files/upload** - Upload a file
  ```bash
  curl -X POST http://localhost:8000/files/upload \
    -H "X-API-Key: your-secret-key" \
    -F "file=@example.txt"
  # {"file_id": "abc123", "filename": "example.txt", ...}
  ```

- **GET /files** - List uploaded files
  ```bash
  curl http://localhost:8000/files \
    -H "X-API-Key: your-secret-key"
  ```

- **GET /files/{file_id}** - Download file
  ```bash
  curl http://localhost:8000/files/abc123 \
    -H "X-API-Key: your-secret-key" \
    -o downloaded_file.txt
  ```

- **GET /files/{file_id}/metadata** - Get file metadata
  ```bash
  curl http://localhost:8000/files/abc123/metadata \
    -H "X-API-Key: your-secret-key"
  ```

- **PUT /files/{file_id}** - Update file content
  ```bash
  curl -X PUT http://localhost:8000/files/abc123 \
    -H "X-API-Key: your-secret-key" \
    -F "file=@new_content.txt"
  ```

- **DELETE /files/{file_id}** - Delete file
  ```bash
  curl -X DELETE http://localhost:8000/files/abc123 \
    -H "X-API-Key: your-secret-key"
  ```

#### Sessions

- **POST /sessions** - Create execution session
  ```bash
  curl -X POST http://localhost:8000/sessions \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{"language": "python"}'
  # {"session_id": "sess123", "status": "active", ...}
  ```

- **GET /sessions/{session_id}** - Get session info
  ```bash
  curl http://localhost:8000/sessions/sess123 \
    -H "X-API-Key: your-secret-key"
  ```

- **POST /sessions/{session_id}/exec** - Execute in session context
  ```bash
  curl -X POST http://localhost:8000/sessions/sess123/exec \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{"code": "x = 42"}'
  ```

- **DELETE /sessions/{session_id}** - Close session
  ```bash
  curl -X DELETE http://localhost:8000/sessions/sess123 \
    -H "X-API-Key: your-secret-key"
  ```

#### Workspaces

- **POST /workspaces** - Create workspace
  ```bash
  curl -X POST http://localhost:8000/workspaces \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{"name": "my-workspace", "ttl_seconds": 3600}'
  ```

- **GET /workspaces** - List workspaces
  ```bash
  curl http://localhost:8000/workspaces \
    -H "X-API-Key: your-secret-key"
  ```

- **GET /workspaces/{ws_id}** - Get workspace info
  ```bash
  curl http://localhost:8000/workspaces/ws123 \
    -H "X-API-Key: your-secret-key"
  ```

- **PUT /workspaces/{ws_id}** - Update workspace
  ```bash
  curl -X PUT http://localhost:8000/workspaces/ws123 \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-secret-key" \
    -d '{"ttl_seconds": 7200}'
  ```

- **DELETE /workspaces/{ws_id}** - Delete workspace
  ```bash
  curl -X DELETE http://localhost:8000/workspaces/ws123 \
    -H "X-API-Key: your-secret-key"
  ```

- **POST /workspaces/{ws_id}/snapshot** - Create workspace snapshot
  ```bash
  curl -X POST http://localhost:8000/workspaces/ws123/snapshot \
    -H "X-API-Key: your-secret-key"
  ```

- **POST /workspaces/{ws_id}/restore** - Restore workspace from snapshot
  ```bash
  curl -X POST http://localhost:8000/workspaces/ws123/restore \
    -H "X-API-Key: your-secret-key"
  ```

#### Languages

- **GET /languages** - List supported languages
  ```bash
  curl http://localhost:8000/languages
  ```

- **GET /languages/{lang}/packages** - List pre-installed packages
  ```bash
  curl http://localhost:8000/languages/python/packages
  ```

## Development

### Running Tests

```bash
# Install test dependencies
pip install pytest

# Run tests
pytest
```

### Building Docker Images

```bash
# Build executor image
docker build -t thinkbox-executor:latest docker/executor/

# Build app image
docker build -t thinkbox-api:latest docker/app/
```

### Project Structure

```
thinkbox/
├── app/                    # FastAPI application
│   ├── api/               # API endpoints
│   ├── core/              # Configuration and core utilities
│   ├── executors/         # Code execution backends
│   ├── models/            # Pydantic models
│   ├── services/          # Business logic services
│   └── utils/             # Helper utilities
├── docker/                # Docker configurations
├── tests/                 # Test suite
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Project metadata
└── README.md             # This file
```

## Security Considerations

- **Docker Mode**: Recommended for production. Code runs in isolated containers.
- **Subprocess Mode**: For development only. Less secure, runs code in host process.
- **API Keys**: Enable authentication for production deployments.
- **Resource Limits**: Configure execution timeouts and memory limits.
- **File Uploads**: Validate file types and sizes.

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

For questions or issues, please open a GitHub issue.
