"""Hexagonal storage abstraction.

业务层只依赖 ``protocols/`` 中的接口；具体实现按存储介质组织：
- ``file/``      文件后端（默认）
- ``database/``  RDBMS 后端（SQLAlchemy 通用基础设施 + dialect 子目录，
                 目前只有 ``sqlite/``，未来可加 ``pg/`` / ``mysql/``）

存储模式选择由 ``mode.py`` 统一(``DB_TYPE`` 环境变量)。
"""
