"""Single-file encrypted FileBox container."""
import base64
import json
import os
from pathlib import Path
from thinkdome.platform.storage.workspace_crypto import workspace_cipher

MAGIC = b"TDBOX1:"

class BoxContainer:
    def __init__(self, path: Path, key_scope: str):
        self.path = Path(path)
        self.cipher = workspace_cipher(f"filebox:{key_scope}")

    def _load(self):
        if not self.path.exists():
            return {"format": "thinkdome-box-v1", "files": {}}
        raw = self.path.read_bytes()
        if not raw.startswith(MAGIC):
            raise PermissionError("Invalid or unauthorized FileBox container.")
        return json.loads(self.cipher.decrypt(raw[len(MAGIC):]).decode("utf-8"))

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = MAGIC + self.cipher.encrypt(json.dumps(data, separators=(",", ":")).encode("utf-8"))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, self.path)

    def put(self, logical_path: str, content: bytes):
        data = self._load(); data["files"][logical_path] = base64.b64encode(content).decode("ascii"); self._save(data)

    def get(self, logical_path: str):
        value = self._load()["files"].get(logical_path)
        return base64.b64decode(value) if value is not None else None

    def remove(self, logical_path: str):
        data = self._load(); data["files"].pop(logical_path, None); self._save(data)
