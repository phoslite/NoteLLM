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
    ai_mode: str = "responses"  # responses | chat | anthropic
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
    ai_anthropic_version: str = "2023-06-01"  # Anthropic Messages API 版本头（仅 anthropic 模式）

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

    # 任务系统与并发（决策 35；任一 =0 表示不限制）
    task_workers: int = 8  # 任务系统全局线程池大小；0=每任务独立线程（旧行为）
    ai_concurrency: int = 4  # 文本 LLM 并发数（信号量，demo 实测 4 为甜点）
    vision_concurrency: int = 4  # 视觉 LLM 并发数（信号量，demo 实测 4~8）
    page_render_concurrency: int = 4  # PDF 页图渲染并发（线程池）
    task_quota_text: int = 4  # 文本类任务全局配额（信号量分池）；0=不限制
    task_quota_vision: int = 4  # 视觉类任务全局配额；0=不限制

    # 性能优化（docs/性能优化路径.md §4 第二/三梯队）
    chat_history_limit: int = 200  # 每会话保留最近 N 条消息（性能决策 1 默认「只留最近 N 条」）；0=不限制
    llm_cache_max_entries: int = 300  # LLM 结果缓存容量上限（脑图/预设模式解读，超限删最旧）；0=不缓存
    llm_cache_ttl_days: int = 30  # LLM 结果缓存 TTL（天）
    fts_search_enabled: bool = True  # FTS5 全书搜索开关；关闭时不建索引、搜索接口返回空


settings = Settings()