"""Tests for the ThinkDome Sandbox SDK programmatic interface."""

import pytest
from thinkdome import Sandbox


def test_sandbox_basic():
    """Test basic execution using Sandbox context manager."""
    with Sandbox(backend="subprocess") as dome:
        result = dome.run("print('Hello from ThinkDome SDK')")
        assert result.success
        assert "Hello from ThinkDome SDK" in result.output
        assert result.exit_code == 0
        assert not result.timed_out


def test_sandbox_timeout():
    """Test sandbox timeout enforcement."""
    with Sandbox(backend="subprocess", timeout=1) as dome:
        result = dome.run("import time; time.sleep(2)")
        assert not result.success
        assert result.timed_out


def test_sandbox_files():
    """Test workspace file management helper methods."""
    with Sandbox(backend="subprocess") as dome:
        # Test writing
        dome.write_file("test.txt", "hello workspace")
        assert dome.read_file("test.txt") == "hello workspace"

        # Check listing
        files = dome.list_files()
        assert "test.txt" in files


def test_sandbox_binary_files():
    """Test reading and writing binary media files in the workspace."""
    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    with Sandbox(backend="subprocess") as dome:
        # Write binary file
        dome.write_file("image.png", binary_data)
        
        # Read it back as bytes
        read_data = dome.read_file_bytes("image.png")
        assert read_data == binary_data
        
        # Run execution that outputs a copy
        dome.run("open('copy.png', 'wb').write(open('image.png', 'rb').read())")
        assert dome.read_file_bytes("copy.png") == binary_data
