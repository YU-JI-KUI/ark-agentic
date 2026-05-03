"""Hexagonal storage abstraction.

业务层只依赖 protocols/ 中的接口；backends/ 提供具体实现。
PR1 默认后端：backends/file/。未来可加 backends/sqlite/、postgres/、redis/、s3/。
"""
