import pytest

from orqest.io_utils.load_sys_prompt import load_sys_prompt


class TestLoadSysPrompt:
    def test_loads_from_system_prompts_dir(self, tmp_path):
        prompts_dir = tmp_path / "system_prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test.txt"
        prompt_file.write_text("You are a test agent.", encoding="utf-8")

        result = load_sys_prompt("test.txt", start=tmp_path)
        assert result == "You are a test agent."

    def test_raises_when_dir_not_found(self, tmp_path):
        with pytest.raises(RuntimeError, match="Could not find"):
            load_sys_prompt("test.txt", start=tmp_path)

    def test_raises_when_file_not_found(self, tmp_path):
        prompts_dir = tmp_path / "system_prompts"
        prompts_dir.mkdir()

        with pytest.raises(RuntimeError, match="not found"):
            load_sys_prompt("nonexistent.txt", start=tmp_path)

    def test_start_as_file_resolves_to_parent(self, tmp_path):
        prompts_dir = tmp_path / "system_prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "agent.txt"
        prompt_file.write_text("prompt content", encoding="utf-8")

        # Pass a file path as start — should resolve to its parent dir
        dummy_file = tmp_path / "some_script.py"
        dummy_file.write_text("pass", encoding="utf-8")

        result = load_sys_prompt("agent.txt", start=dummy_file)
        assert result == "prompt content"

    def test_searches_upward(self, tmp_path):
        # Create system_prompts at the top level
        prompts_dir = tmp_path / "system_prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "deep.txt"
        prompt_file.write_text("found it", encoding="utf-8")

        # Search from a nested directory
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        result = load_sys_prompt("deep.txt", start=nested)
        assert result == "found it"
