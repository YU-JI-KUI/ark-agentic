"""Tests for chunker — frontmatter stripping and basic chunking."""

from ark_agentic.core.memory.chunker import MarkdownChunker, strip_frontmatter


class TestStripFrontmatter:
    def test_no_frontmatter(self) -> None:
        text = "# Hello\nWorld"
        assert strip_frontmatter(text) == text

    def test_with_frontmatter(self) -> None:
        text = "---\nkey: val\n---\n# Body\nContent"
        assert strip_frontmatter(text) == "# Body\nContent"

    def test_empty_frontmatter(self) -> None:
        text = "---\n---\nBody"
        assert strip_frontmatter(text) == "Body"

    def test_frontmatter_only(self) -> None:
        text = "---\nkey: val\n---"
        assert strip_frontmatter(text) == ""

    def test_no_closing_delimiter(self) -> None:
        text = "---\nkey: val\nno closing"
        assert strip_frontmatter(text) == text

    def test_frontmatter_with_chinese(self) -> None:
        text = "---\n基本信息:\n  姓名: 张三\n---\n# 记忆内容"
        assert strip_frontmatter(text) == "# 记忆内容"


class TestChunkerSkipsFrontmatter:
    def test_chunk_text_strips_frontmatter(self) -> None:
        text = "---\nkey: val\n---\n# Section\nContent here is enough to form a chunk."
        chunker = MarkdownChunker()
        chunks = chunker.chunk_text(text, "test.md")
        for c in chunks:
            assert "key: val" not in c.text
            assert "---" not in c.text.split("\n")[0]

    def test_chunk_text_without_frontmatter_works(self) -> None:
        text = "# Section\nContent here is long enough to be a chunk."
        chunker = MarkdownChunker()
        chunks = chunker.chunk_text(text, "test.md")
        assert len(chunks) >= 1
        assert "Content" in chunks[0].text
