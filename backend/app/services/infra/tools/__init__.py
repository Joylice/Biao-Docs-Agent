"""外部工具系统服务包 — presets / http_tool_client / registry / tools_service.

模块划分（依赖方向单向：presets → http_tool_client → registry → tools_service）：
- ``presets``：工具预设定义（Tavily/Brave/SearXNG），auth_style 与 response_path 映射；
- ``http_tool_client``：异步 HTTP 调用外部搜索 API，按 auth_style 注入密钥，
  超时/SSRF/JSON 解析失败均降级为 [{"error": ...}]，不抛异常；
- ``registry``：阶段白名单 + 双闸校验 + 30s TTL 缓存，动态组装 OpenAI function schema；
- ``tools_service``：CRUD + 密钥三态 + 乐观锁 + 绑定管理 + 缓存失效；
- ``prefetch``：各阶段 LLM 调用前的「取证前置」统一入口（绑定即生效，无绑定零变更）。
"""
