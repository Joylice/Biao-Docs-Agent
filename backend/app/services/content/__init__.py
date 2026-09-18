"""Content DSL — 章节内容结构化表示（存储/渲染/编辑/校验统一真源）.

参考 OpenMAIC @openmaic/dsl 的设计理念：DSL JSON 既是存储格式，也是渲染格式，
也是编辑格式。消除 Markdown ↔ HTML 双向转换的有损链路。

Layer 边界：本模块只管"内容怎么表示和处理"，不管"告诉 LLM 什么"（Prompt DSL 已覆盖）。
"""
