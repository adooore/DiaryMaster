"""飞书机器人渠道：webhook 接收事件并回复 IM 消息。"""

from backend.channels.feishu.config import get_feishu_config, is_enabled
from backend.channels.feishu.router import router

__all__ = [
    "router",
    "is_enabled",
    "get_feishu_config",
]