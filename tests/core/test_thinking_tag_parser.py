"""ThinkingTagParser 单元测试

覆盖 6 个核心场景：
1. 正常标签解析
2. 缺失闭合标签
3. 标签跨 chunk 断裂
4. 无标签 fallback（lenient 模式）
5. 嵌套/重复标签
6. strip_tags 静态方法
"""

import pytest

from ark_agentic.core.stream.thinking_tag_parser import ThinkingTagParser


class TestNormalParsing:
    """场景 1: 正常标签解析"""

    def test_think_tag(self) -> None:
        parser = ThinkingTagParser()
        thinking, final = parser.process_chunk("<think>好的查询保单</think>")
        assert thinking == "好的查询保单"
        assert final == ""

    def test_final_tag(self) -> None:
        parser = ThinkingTagParser()
        thinking, final = parser.process_chunk("<final>您的保单如下</final>")
        assert thinking == ""
        assert final == "您的保单如下"

    def test_think_then_final(self) -> None:
        parser = ThinkingTagParser()

        t1, f1 = parser.process_chunk("<think>让我查一下</think>")
        assert t1 == "让我查一下"
        assert f1 == ""

        parser.reset()

        t2, f2 = parser.process_chunk("<final>查询结果如下</final>")
        assert t2 == ""
        assert f2 == "查询结果如下"

    def test_think_and_final_in_same_chunk(self) -> None:
        parser = ThinkingTagParser()
        thinking, final = parser.process_chunk(
            "<think>分析中</think><final>结果</final>"
        )
        assert thinking == "分析中"
        assert final == "结果"

    def test_thinking_variant(self) -> None:
        parser = ThinkingTagParser()
        thinking, final = parser.process_chunk("<thinking>推理过程</thinking>")
        assert thinking == "推理过程"
        assert final == ""


class TestMissingClosingTag:
    """场景 2: 缺失闭合标签"""

    def test_missing_think_close(self) -> None:
        parser = ThinkingTagParser()
        t1, f1 = parser.process_chunk("<think>好的查询保单")
        assert t1 == "好的查询保单"
        assert f1 == ""
        assert parser.in_think is True

        t2, f2 = parser.process_chunk("继续思考")
        assert t2 == "继续思考"
        assert f2 == ""

        t3, f3 = parser.flush()
        assert t3 == ""
        assert f3 == ""

    def test_missing_final_close(self) -> None:
        parser = ThinkingTagParser()
        t1, f1 = parser.process_chunk("<final>保单信息")
        assert t1 == ""
        assert f1 == "保单信息"
        assert parser.in_final is True

    def test_flush_with_pending_in_think(self) -> None:
        parser = ThinkingTagParser()
        parser.process_chunk("<think>开始思考")
        parser.in_think = True
        parser._pending = "尾部内容"
        t, f = parser.flush()
        assert t == "尾部内容"
        assert f == ""


class TestCrossChunkTags:
    """场景 3: 标签跨 chunk 断裂"""

    def test_think_tag_split(self) -> None:
        parser = ThinkingTagParser()

        t1, f1 = parser.process_chunk("前文<thi")
        assert "前文" in f1
        assert parser._pending == "<thi"

        t2, f2 = parser.process_chunk("nk>思考内容</think>后文")
        assert t2 == "思考内容"
        assert "后文" in f2

    def test_closing_tag_split(self) -> None:
        parser = ThinkingTagParser()

        t1, f1 = parser.process_chunk("<think>内容</thi")
        assert "内容" in t1
        assert parser._pending == "</thi"

        t2, f2 = parser.process_chunk("nk>回到正常")
        assert "回到正常" in f2

    def test_lone_lt_at_end(self) -> None:
        parser = ThinkingTagParser()

        t1, f1 = parser.process_chunk("文本<")
        assert parser._pending == "<"
        assert "文本" in f1

    def test_non_tag_lt_not_buffered(self) -> None:
        """price < 100 中的 < 不应被缓冲"""
        parser = ThinkingTagParser()
        t, f = parser.process_chunk("price < 100")
        assert f == "price < 100"
        assert parser._pending == ""

    def test_lt_with_number_not_buffered(self) -> None:
        """<1 不应被缓冲（不是 t/f 开头）"""
        parser = ThinkingTagParser()
        t, f = parser.process_chunk("value <1")
        assert parser._pending == ""


class TestLenientFallback:
    """场景 4: 无标签 fallback（lenient 模式）"""

    def test_no_tags_at_all(self) -> None:
        parser = ThinkingTagParser()
        thinking, final = parser.process_chunk("您的保单如下，保额10万")
        assert thinking == ""
        assert final == "您的保单如下，保额10万"

    def test_untagged_content_goes_to_final(self) -> None:
        parser = ThinkingTagParser()
        t, f = parser.process_chunk("开头文本<think>思考</think>尾部文本")
        assert t == "思考"
        assert "开头文本" in f
        assert "尾部文本" in f

    def test_empty_chunk(self) -> None:
        parser = ThinkingTagParser()
        t, f = parser.process_chunk("")
        assert t == ""
        assert f == ""


class TestNestedTags:
    """场景 5: 嵌套/重复标签"""

    def test_double_think_open(self) -> None:
        parser = ThinkingTagParser()
        t, f = parser.process_chunk("<think><think>内容</think></think>")
        assert "内容" in t

    def test_orphan_close_tag(self) -> None:
        """孤立的 </think> 应被忽略"""
        parser = ThinkingTagParser()
        t, f = parser.process_chunk("正常文本</think>后续")
        assert "正常文本" in f
        assert "后续" in f


class TestStripTags:
    """场景 6: strip_tags 静态方法"""

    def test_strip_think_tags(self) -> None:
        result = ThinkingTagParser.strip_tags("<think>思考</think>")
        assert result == "思考"

    def test_strip_final_tags(self) -> None:
        result = ThinkingTagParser.strip_tags("<final>结果</final>")
        assert result == "结果"

    def test_strip_mixed(self) -> None:
        result = ThinkingTagParser.strip_tags(
            "<think>分析</think><final>答案</final>"
        )
        assert result == "分析答案"

    def test_strip_no_tags(self) -> None:
        result = ThinkingTagParser.strip_tags("普通文本")
        assert result == "普通文本"

    def test_strip_empty(self) -> None:
        assert ThinkingTagParser.strip_tags("") == ""
        assert ThinkingTagParser.strip_tags(None) is None  # type: ignore[arg-type]

    def test_strip_thinking_variant(self) -> None:
        result = ThinkingTagParser.strip_tags("<thinking>推理</thinking>")
        assert result == "推理"


class TestReset:
    """reset 方法"""

    def test_reset_clears_state(self) -> None:
        parser = ThinkingTagParser()
        parser.process_chunk("<think>思考中")
        assert parser.in_think is True

        parser.reset()
        assert parser.in_think is False
        assert parser.in_final is False
        assert parser.ever_in_final is False
        assert parser._pending == ""

    def test_multi_turn_with_reset(self) -> None:
        parser = ThinkingTagParser()

        t1, f1 = parser.process_chunk("<think>第一轮思考</think>")
        assert t1 == "第一轮思考"

        parser.reset()

        t2, f2 = parser.process_chunk("<final>最终回答</final>")
        assert f2 == "最终回答"
        assert t2 == ""
