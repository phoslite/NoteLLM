# -*- coding: utf-8 -*-
"""本地模拟 AI 接口（OpenAI 兼容，无需 API Key）。

同时支持两种接口：
- POST /v1/chat/completions  （Chat Completions，messages）
- POST /v1/responses       （Responses API，instructions/input，DeepSeek 官方用法）

用法：先运行本脚本，再把「设置」中的 Base URL 改为
http://127.0.0.1:18999/v1（或 http://127.0.0.1:18999），模型名任意，API Key 留空。
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 18999
MOCK = {
    "思维导图": "高效阅读术\n\t阅读准备\n\t\t明确目标\n\t核心技巧\n\t\t速读\n\t\t精读\n\t输出与复盘\n\t\t笔记\n\t\t讲述",
    "画像": ('{"reader_name":"体验用户","preferences":["喜欢比喻式讲解","偏爱短段落"],'
             '"thinking_style":"发散联想型","knowledge_base":"有基础阅读经验",'
             '"reading_depth":"精读偏好","favorite_topics":["记忆法","学习方法"],'
             '"weaknesses":["总结能力待提升"],"style":"多用比喻和例子","recent_focus":["高效阅读"]}'),
    "解读": "## 核心要义\n阅读是主动的认知训练，而不是被动接收。\n\n## 逐段解读\n作者强调带着问题阅读……",
    "概论": "## 内容概述\n本书系统介绍从阅读准备到知识内化的完整方法。\n\n## 核心观点\n- 主动阅读\n- 输出倒逼输入",
    "逻辑": "## 论证链条\n明确目的 → 预览结构 → 精读内化 → 输出巩固\n\n## 关键假设\n读者有自主提升阅读能力的意愿",
    "正常": "正常",
}


def _content_text(content) -> str:
    """消息内容转纯文本：字符串原样；多模态 parts 列表仅取 text（兼容扫描版页面图片附件）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def pick_reply(sys_text: str, user_text: str) -> str:
    if "输出思维导图 JSON" in user_text:
        return json.dumps({
            "title": "高效阅读术",
            "children": [
                {"name": "阅读准备", "nodeType": "大纲", "ref": None, "children": [
                    {"name": "明确目标", "nodeType": "细节", "ref": None, "children": []}]},
                {"name": "核心技巧", "nodeType": "大纲", "ref": None, "children": [
                    {"name": "速读", "nodeType": "细节", "ref": None, "children": []},
                    {"name": "精读", "nodeType": "细节", "ref": None, "children": []}]},
                {"name": "输出与复盘", "nodeType": "大纲", "ref": None, "children": [
                    {"name": "笔记", "nodeType": "细节", "ref": None, "children": []},
                    {"name": "讲述", "nodeType": "细节", "ref": None, "children": []}]},
            ],
        }, ensure_ascii=False)
    if "知识整理专家" in sys_text:
        return ('{"tags": ["高效阅读", "学习方法"],'
                '"summary": "本书系统讲解从阅读准备到知识内化的完整方法，核心是主动阅读与输出倒逼输入。",'
                '"concepts": ["精读四步法：提问-划线-复述-联结", "间隔重复：按递增间隔复习", "提取练习：凭记忆输出"],'
                '"key_points": ["阅读是主动认知训练而非被动接收", "带着问题阅读能显著提升吸收率", "速读的本质是选择性阅读", "笔记要包含行动项", "费曼学习法：能讲清楚才算懂"],'
                '"skills": ["精读四步法：适用于任何非虚构书籍的精读场景，步骤为提问、划线、复述、联结",'
                '"三栏笔记法：适用于读书笔记整理，左摘录、中理解、右行动",'
                '"结构预览：适用于新书上手，先看目录、序言与结语建立地图",'
                '"问题卡片复习：适用于长期记忆，把重点做成卡片按间隔重复复习"]}')
    if "阅读辅导专家" in sys_text:
        return MOCK["画像"]
    return next((v for k, v in MOCK.items() if k in user_text),
                "（模拟回复：请配置真实 AI 接口以获得完整能力）")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")

        if self.path.endswith("/responses"):
            # Responses API：instructions/input
            sys_text = body.get("instructions") or ""
            raw_input = body.get("input") or ""
            user_text = raw_input if isinstance(raw_input, str) else json.dumps(raw_input, ensure_ascii=False)
        else:
            # Chat Completions：messages
            messages = body.get("messages", [])
            sys_text = "".join(_content_text(m.get("content", "")) for m in messages if m["role"] == "system")
            user_text = "".join(_content_text(m.get("content", "")) for m in messages if m["role"] == "user")

        reply = pick_reply(sys_text, user_text)

        if body.get("stream"):
            if self.path.endswith("/responses"):
                payload = json.dumps({"type": "response.output_text.delta", "delta": reply}, ensure_ascii=False)
                done = "data: {\"type\": \"response.completed\"}\n\n"
            else:
                payload = json.dumps({"choices": [{"delta": {"content": reply}}]}, ensure_ascii=False)
                done = ""
            out = f"data: {payload}\n\n{done}data: [DONE]\n\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        else:
            if self.path.endswith("/responses"):
                out = json.dumps({"output": [{"type": "message",
                                              "content": [{"type": "output_text", "text": reply}]}]},
                                 ensure_ascii=False).encode("utf-8")
            else:
                out = json.dumps({"choices": [{"message": {"content": reply}}]}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)


if __name__ == "__main__":
    print(f"mock LLM 服务运行于 http://127.0.0.1:{PORT}/v1 （Ctrl+C 停止）")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()