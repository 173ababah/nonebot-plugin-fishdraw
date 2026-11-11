"""配置项（全部走 .env，前缀 FISHDRAW_）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Config(BaseModel):
    """nonebot-plugin-fishdraw 的配置。"""

    fishdraw_enabled: bool = Field(default=True, description="总开关")
    fishdraw_gateway: str = Field(
        default="http://127.0.0.1:18188",
        description="ComfyUI 网关地址（无限画布那套 /v1/images/* 接口）")
    fishdraw_token: str = Field(default="", description="网关 Token（网关没设就留空）")
    fishdraw_timeout: int = Field(default=600, description="单次出图超时（秒）")
    fishdraw_steps: int = Field(default=8, description="采样步数（turbo 8 步够用，4~50）")
    fishdraw_size: str = Field(default="1024x1024", description="默认画布")
    fishdraw_max_refs: int = Field(default=4, description="最多几张参考图（网关上限）")
    fishdraw_max_mb: float = Field(default=8.0, description="单张参考图大小上限（MB）")
    fishdraw_styles_file: str = Field(
        default="", description="画风模板文件；留空 = <插件数据目录>/draw_styles.json")
    fishdraw_nsfw_default: bool = Field(
        default=False, description="新会话默认是否允许 NSFW（可被 /nsfw 覆盖）")
    fishdraw_send_delay: float = Field(default=0.0, description="发图前额外等待（秒）")
