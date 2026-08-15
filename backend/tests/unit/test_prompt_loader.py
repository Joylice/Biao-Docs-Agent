"""提示词模板加载器测试."""

from unittest.mock import patch

import pytest

from app.core.exceptions import BizError
from app.services.prompt_loader import load_parse_prompt


class TestLoadParsePrompt:
    """提示词加载测试."""

    def test_load_parse_prompt_success(self) -> None:
        """正常加载 parse.yaml 模板."""
        system, user = load_parse_prompt("这是招标文本")
        assert "招投标" in system or "评分" in system
        assert "这是招标文本" in user

    def test_template_not_found(self) -> None:
        """模板文件不存在时抛出 BizError."""
        with patch("app.services.prompt_loader._PROMPTS_DIR") as mock_dir:
            mock_path = mock_dir / "parse.yaml"
            mock_path.read_text.side_effect = FileNotFoundError
            with pytest.raises(BizError, match="提示词模板"):
                load_parse_prompt("text")
