from pathlib import Path


def test_placeholder_output_exists():
    path = Path("/task_file/hello.txt")
    assert path.exists()
