"""Hexagonal storage abstraction.

业务层只依赖 protocols/ 中的接口；repository/ 提供具体实现。
PR1 默认后端：repository/file/。未来可加 repository/sqlite/、postgres/、redis/、s3/。
"""
