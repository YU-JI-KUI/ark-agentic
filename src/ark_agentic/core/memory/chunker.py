"""
文档分块

将文档分割成适合向量检索的小块。

参考: openclaw-main/src/memory/internal.ts - chunkMarkdown
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .types import MemoryChunk, MemorySource

logger = logging.getLogger(__name__)


@dataclass
class ChunkConfig:
    """分块配置"""

    # 块大小（字符数）
    chunk_size: int = 500
    # 重叠大小（字符数）
    chunk_overlap: int = 50
    # 最小块大小
    min_chunk_size: int = 50

    # Markdown 分块策略
    split_by_heading: bool = True  # 按标题分割
    heading_levels: list[int] | None = None  # 分割的标题级别，None 表示全部

    # 段落分块
    split_by_paragraph: bool = True  # 按段落分割
    paragraph_separator: str = "\n\n"  # 段落分隔符


def generate_chunk_id(path: str, start_line: int, content: str) -> str:
    """生成 chunk ID"""
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{path}:{start_line}:{content_hash}"


class MarkdownChunker:
    """Markdown 文档分块器"""

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self.config = config or ChunkConfig()

    def chunk_text(
        self,
        text: str,
        path: str = "",
        source: MemorySource = MemorySource.MEMORY,
    ) -> list[MemoryChunk]:
        """分块文本"""
        if not text.strip():
            return []

        # 按行分割，保留行号信息
        lines = text.split("\n")

        # 根据策略分块
        if self.config.split_by_heading:
            chunks = self._chunk_by_headings(lines, path, source)
        elif self.config.split_by_paragraph:
            chunks = self._chunk_by_paragraphs(lines, path, source)
        else:
            chunks = self._chunk_by_size(lines, path, source)

        logger.debug(f"Chunked {path}: {len(lines)} lines -> {len(chunks)} chunks")
        return chunks

    def _chunk_by_headings(
        self,
        lines: list[str],
        path: str,
        source: MemorySource,
    ) -> list[MemoryChunk]:
        """按标题分块"""
        chunks: list[MemoryChunk] = []
        current_lines: list[str] = []
        current_start = 0

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        for i, line in enumerate(lines):
            match = heading_pattern.match(line)

            if match:
                level = len(match.group(1))
                # 检查是否需要在此标题处分割
                should_split = self.config.heading_levels is None or level in self.config.heading_levels

                if should_split and current_lines:
                    # 保存当前块
                    chunk = self._create_chunk(
                        current_lines, current_start, path, source
                    )
                    if chunk:
                        chunks.append(chunk)
                    current_lines = []
                    current_start = i

            current_lines.append(line)

        # 保存最后一块
        if current_lines:
            chunk = self._create_chunk(current_lines, current_start, path, source)
            if chunk:
                chunks.append(chunk)

        # 如果块太大，进一步分割
        final_chunks: list[MemoryChunk] = []
        for chunk in chunks:
            if len(chunk.text) > self.config.chunk_size * 2:
                # 按大小继续分割
                sub_lines = chunk.text.split("\n")
                sub_chunks = self._chunk_by_size(
                    sub_lines, path, source, start_offset=chunk.start_line
                )
                final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        return final_chunks

    def _chunk_by_paragraphs(
        self,
        lines: list[str],
        path: str,
        source: MemorySource,
    ) -> list[MemoryChunk]:
        """按段落分块"""
        text = "\n".join(lines)
        paragraphs = text.split(self.config.paragraph_separator)

        chunks: list[MemoryChunk] = []
        current_text = ""
        current_start = 0
        line_offset = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                line_offset += 1
                continue

            para_lines = para.count("\n") + 1

            if len(current_text) + len(para) > self.config.chunk_size:
                if current_text:
                    chunk = self._create_chunk_from_text(
                        current_text, current_start, path, source
                    )
                    if chunk:
                        chunks.append(chunk)
                current_text = para
                current_start = line_offset
            else:
                if current_text:
                    current_text += "\n\n" + para
                else:
                    current_text = para
                    current_start = line_offset

            line_offset += para_lines + 1

        # 保存最后一块
        if current_text:
            chunk = self._create_chunk_from_text(
                current_text, current_start, path, source
            )
            if chunk:
                chunks.append(chunk)

        return chunks

    def _chunk_by_size(
        self,
        lines: list[str],
        path: str,
        source: MemorySource,
        start_offset: int = 0,
    ) -> list[MemoryChunk]:
        """按大小分块"""
        chunks: list[MemoryChunk] = []
        current_lines: list[str] = []
        current_size = 0
        current_start = start_offset

        for i, line in enumerate(lines):
            line_size = len(line) + 1  # +1 for newline

            if current_size + line_size > self.config.chunk_size and current_lines:
                # 保存当前块
                chunk = self._create_chunk(current_lines, current_start, path, source)
                if chunk:
                    chunks.append(chunk)

                # 开始新块（带重叠）
                overlap_lines = self._get_overlap_lines(current_lines)
                current_lines = overlap_lines + [line]
                current_start = start_offset + i - len(overlap_lines)
                current_size = sum(len(line) + 1 for line in current_lines)
            else:
                current_lines.append(line)
                current_size += line_size

        # 保存最后一块
        if current_lines:
            chunk = self._create_chunk(current_lines, current_start, path, source)
            if chunk:
                chunks.append(chunk)

        return chunks

    def _get_overlap_lines(self, lines: list[str]) -> list[str]:
        """获取重叠部分的行"""
        if self.config.chunk_overlap <= 0:
            return []

        overlap_size = 0
        overlap_lines: list[str] = []

        for line in reversed(lines):
            line_size = len(line) + 1
            if overlap_size + line_size > self.config.chunk_overlap:
                break
            overlap_lines.insert(0, line)
            overlap_size += line_size

        return overlap_lines

    def _create_chunk(
        self,
        lines: list[str],
        start_line: int,
        path: str,
        source: MemorySource,
    ) -> MemoryChunk | None:
        """从行列表创建 chunk"""
        text = "\n".join(lines).strip()
        if len(text) < self.config.min_chunk_size:
            return None

        end_line = start_line + len(lines) - 1
        chunk_id = generate_chunk_id(path, start_line, text)

        return MemoryChunk(
            id=chunk_id,
            path=path,
            start_line=start_line,
            end_line=end_line,
            text=text,
            source=source,
        )

    def _create_chunk_from_text(
        self,
        text: str,
        start_line: int,
        path: str,
        source: MemorySource,
    ) -> MemoryChunk | None:
        """从文本创建 chunk"""
        text = text.strip()
        if len(text) < self.config.min_chunk_size:
            return None

        end_line = start_line + text.count("\n")
        chunk_id = generate_chunk_id(path, start_line, text)

        return MemoryChunk(
            id=chunk_id,
            path=path,
            start_line=start_line,
            end_line=end_line,
            text=text,
            source=source,
        )


def chunk_file(
    file_path: str | Path,
    source: MemorySource = MemorySource.MEMORY,
    config: ChunkConfig | None = None,
) -> list[MemoryChunk]:
    """分块文件"""
    file_path = Path(file_path)

    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return []

    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return []

    chunker = MarkdownChunker(config)
    return chunker.chunk_text(text, str(file_path), source)


def chunk_directory(
    dir_path: str | Path,
    source: MemorySource = MemorySource.MEMORY,
    extensions: list[str] | None = None,
    config: ChunkConfig | None = None,
) -> Iterator[MemoryChunk]:
    """分块目录下的所有文件"""
    dir_path = Path(dir_path)
    extensions = extensions or [".md", ".txt"]

    if not dir_path.exists():
        logger.warning(f"Directory not found: {dir_path}")
        return

    for file_path in dir_path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            chunks = chunk_file(file_path, source, config)
            yield from chunks


# ============ 便捷函数 ============


def create_chunker(
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    split_by_heading: bool = True,
) -> MarkdownChunker:
    """创建文档分块器"""
    config = ChunkConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        split_by_heading=split_by_heading,
    )
    return MarkdownChunker(config)
