"""应用配置：读取 .env / 环境变量，禁止硬编码密钥。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "读书阅读助手"
    app_host: str = "127.0.0.1"
    app_port: int = 8321
    data_dir: Path = Path("data")
    domain_terms_file: Path = Path("domain_terms.txt")  # 专业术语词库（与 .env 同级，用户可编辑）
    db_url: str = "sqlite:///./data/llmnotebook.db"

    ai_base_url: str = "https://api.deepseek.com"
    ai_api_key: str = ""
    ai_model: str = "deepseek-v4-flash"
    ai_mode: str = "responses"  # responses | chat
    ai_timeout: int = 120
    ai_verify_ssl: bool = True
    ai_enable_body_send: bool = True  # 隐私开关：是否向模型发送书籍正文
    ai_send_page_image: bool = False  # 扫描版 PDF：提问时是否附带当前页图片（需模型支持视觉输入）
    ai_temperature: float | None = None
    # 文本 AI 精细参数（DeepSeek 思考模式等；chat 模式生效，responses 模式部分待定稿）
    ai_max_tokens: int | None = None  # 输出 token 上限（DeepSeek 默认 32K，最大 64K，含思考 token）
    ai_thinking_type: str = ""  # enabled / disabled（DeepSeek 思考模式开关；留空不传）
    ai_reasoning_effort: str = ""  # low / medium / high / max（推理强度；thinking=disabled 时不生效）
    ai_top_p: float | None = None
    ai_frequency_penalty: float | None = None
    ai_presence_penalty: float | None = None
    ai_stop: str = ""  # 停止词，多个用英文逗号分隔

    # 多模态视觉配置（M7）：PDF 页面信息提取用，独立于文本 AI，无需额度管理
    vision_base_url: str = ""
    vision_api_key: str = ""
    vision_model: str = ""
    vision_timeout: int = 120
    vision_verify_ssl: bool = True
    vision_max_tokens: int = 4096  # SiliconFlow 建议设置生成 token 上限
    vision_temperature: float | None = None
    vision_top_p: float | None = None
    vision_frequency_penalty: float | None = None
    vision_presence_penalty: float | None = None
    vision_enable_thinking: bool | None = None  # SiliconFlow 推理模型（DeepSeek/Zhipu 系）开关；非推理模型勿开
    vision_thinking_budget: int | None = None  # SiliconFlow 思维链 token 上限（仅推理模型）


settings = Settings()