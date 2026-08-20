"""E2E 环境维护脚本：重置 BID_ADMIN_USER_IDS 白名单管理员密码（数据漂移修复）.

用法（宿主机）：
  docker cp e2e/scripts/reset-admin-password.py deploy-api-1:/tmp/reset_admin.py
  docker exec -e PYTHONPATH=/app deploy-api-1 python /tmp/reset_admin.py [email] [password]
默认：admin@bidagent.com / E2eAdmin#12345（与 division-subsection.spec.ts 默认值一致）。
仅用于 E2E 测试环境；生产禁用。
"""
import asyncio
import sys

import bcrypt
from sqlalchemy import update

from app.core.database import async_session_factory
from app.models.user import User

EMAIL = sys.argv[1] if len(sys.argv) > 1 else "admin@bidagent.com"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else "E2eAdmin#12345"


async def main() -> None:
    digest = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    async with async_session_factory() as db:
        result = await db.execute(
            update(User).where(User.email == EMAIL).values(password_hash=digest)
        )
        await db.commit()
        print(f"updated rows: {result.rowcount} (email={EMAIL})")


asyncio.run(main())
