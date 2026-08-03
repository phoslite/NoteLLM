# -*- coding: utf-8 -*-
"""并发大模型调用实验脚本（独立于主应用，仅做可行性验证）。

验证目标：
1. 串行 vs 并发（ThreadPoolExecutor）的耗时与加速比；
2. worker 数量扫描对吞吐的影响；
3. 文本模型 + 多模态模型两路异构并行的可行性。

用法：
  python demo/parallel_llm.py --mock                 # 本地 mock（先启动 _mock_llm.py --delay 1）
  python demo/parallel_llm.py --tasks 8              # 真实 API（读 demo/.env）
  python demo/parallel_llm.py --vision-env ../backend/.env  # 场景3：文本+多模态异构并行
"""
import argparse
import json
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_demo import call_llm, load_env_file, mask_key  # noqa: E402

MOCK_URL = "http://127.0.0.1:18999/v1"
PIXEL_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
             "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def client_cfg(env: dict, prefix: str = "AI_") -> dict:
    """从 env 构造调用参数（prefix 可换 VISION_）。"""
    return {
        "base_url": env.get(prefix + "BASE_URL") or MOCK_URL,
        "api_key": env.get(prefix + "API_KEY") or "",
        "model": env.get(prefix + "MODEL") or "demo-model",
        "mode": env.get(prefix + "MODE") or "chat",
        "timeout": int(env.get(prefix + "TIMEOUT") or 120),
        "verify_ssl": (env.get(prefix + "VERIFY_SSL") or "1") not in ("0", "false", "False"),
    }


def build_specs(n: int) -> list:
    """生成 n 个相互独立的任务 prompt（模拟 N 本书/页并发总结）。"""
    return [
        {"id": i, "prompt": f"这是第 {i} 号独立任务：请用一句话总结内容要点，并输出结论。"}
        for i in range(1, n + 1)
    ]


def call_once(spec: dict, cfg: dict, retries: int) -> dict:
    """执行单个任务，失败按指数退避重试，返回耗时与结果。"""
    messages = [
        {"role": "system", "content": "你是并发压测助手，只输出结论文本，不要额外解释。"},
        {"role": "user", "content": spec["prompt"]},
    ]
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        try:
            reply = call_llm(cfg["base_url"], cfg["api_key"], cfg["model"], cfg["mode"],
                             messages, cfg["timeout"], cfg["verify_ssl"])
            return {"id": spec["id"], "ok": True, "latency": time.perf_counter() - t0, "reply": reply}
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
    return {"id": spec["id"], "ok": False, "latency": time.perf_counter() - t0, "error": str(last_err)}


def run_batch(specs: list, workers: int, cfg: dict, retries: int, label: str) -> dict:
    """并发执行一批任务，返回统计结果。"""
    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(call_once, s, cfg, retries): s for s in specs}
        for fut in as_completed(futures):
            results.append(fut.result())
    total = time.perf_counter() - t0
    ok = [r for r in results if r["ok"]]
    lat = [r["latency"] for r in results]
    print(f"[{label}] workers={workers} tasks={len(specs)} 总耗时={total:.2f}s "
          f"成功={len(ok)}/{len(specs)} "
          f"平均单任务={sum(lat) / len(lat) if lat else 0:.2f}s "
          f"最大单任务={max(lat) if lat else 0:.2f}s")
    for r in results:
        if not r["ok"]:
            print(f"    任务 {r['id']} 失败: {r['error']}")
    return {"total": total, "ok": len(ok), "n": len(specs), "label": label, "workers": workers}


def scene1(specs: list, cfg: dict, retries: int, workers: int) -> None:
    """串行 vs 并发对比。"""
    print("\n=== 场景1：串行 vs 并发 ===")
    t0 = time.perf_counter()
    for s in specs:
        call_once(s, cfg, retries)
    serial = time.perf_counter() - t0
    print(f"[串行] tasks={len(specs)} 总耗时={serial:.2f}s")
    par = run_batch(specs, workers, cfg, retries, "并发")
    if par["total"] > 0:
        print(f"加速比 = {serial / par['total']:.2f}x"
              f"  （串行 {serial:.2f}s -> 并发 {par['total']:.2f}s, workers={workers}）")


def scene2(specs: list, cfg: dict, retries: int, skip: bool) -> None:
    """worker 数量扫描。"""
    if skip:
        print("\n=== 场景2：已跳过（--skip-scan） ===")
        return
    print("\n=== 场景2：worker 数量扫描（真实 API 建议 --skip-scan 省额度） ===")
    for w in (1, 2, 4, 8):
        run_batch(specs, w, cfg, retries, "扫描")


def call_vision(cfg: dict, prompt: str, image_url: str) -> str:
    """以 OpenAI 兼容 chat.completions 发送图片附件（SiliconFlow 多模态格式）。"""
    payload = {"model": cfg["model"], "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]}]}
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = "Bearer " + cfg["api_key"]
    ctx = ssl.create_default_context()
    if not cfg["verify_ssl"]:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=cfg["timeout"], context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def scene3(text_cfg: dict, vision_cfg: dict) -> None:
    """文本 + 多模态两路异构并行（视觉任务带图片附件）。"""
    print("\n=== 场景3：文本模型 + 多模态模型 异构并行 ===")
    if vision_cfg["mode"] != "chat":
        print(f"    跳过：多模态仅支持 chat 模式，当前 VISION_MODE={vision_cfg['mode']}")
        return
    texts = [{"id": f"text-{i}", "prompt": f"文本任务 {i}：总结第 {i} 章要点"} for i in (1, 2, 3)]
    visions = [{"id": f"vision-{i}", "prompt": f"视觉任务 {i}：请描述这张扫描页的内容"} for i in (1, 2, 3)]

    def do_text(t):
        messages = [{"role": "user", "content": t["prompt"]}]
        return call_llm(text_cfg["base_url"], text_cfg["api_key"], text_cfg["model"],
                        text_cfg["mode"], messages, text_cfg["timeout"], text_cfg["verify_ssl"])

    def do_vision(v):
        return call_vision(vision_cfg, v["prompt"], PIXEL_PNG)

    t0 = time.perf_counter()
    ok = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(do_text, t) for t in texts] + [pool.submit(do_vision, v) for v in visions]
        for fut in as_completed(futures):
            try:
                fut.result()
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"    子任务失败: {exc}")
    total = time.perf_counter() - t0
    print(f"[异构并行] 文本x{len(texts)} + 视觉x{len(visions)} 总耗时={total:.2f}s 成功={ok}/{len(texts) + len(visions)}")


def main() -> int:
    p = argparse.ArgumentParser(description="并发大模型调用实验（独立于主应用）")
    p.add_argument("--mock", action="store_true", help="使用本地 mock 服务（需先启动 _mock_llm.py --delay 1）")
    p.add_argument("--env", default=None, help="文本模型 .env 路径（默认 demo/.env）")
    p.add_argument("--vision-env", default=None, help="多模态模型 .env 路径（如 backend/.env，提供后启用场景3）")
    p.add_argument("--tasks", type=int, default=8, help="任务数量（默认 8）")
    p.add_argument("--workers", type=int, default=4, help="场景1并发 worker 数（默认 4）")
    p.add_argument("--retries", type=int, default=1, help="每个任务失败重试次数（默认 1）")
    p.add_argument("--skip-scan", action="store_true", help="跳过场景2 worker 扫描")
    args = p.parse_args()

    env_path = Path(args.env) if args.env else Path(__file__).resolve().parent / ".env"
    text_cfg = client_cfg(load_env_file(env_path), "AI_")
    if args.mock:
        text_cfg.update(base_url=MOCK_URL, api_key="", model="mock-model")
    print(f"[文本配置] base_url={text_cfg['base_url']} model={text_cfg['model']} "
          f"mode={text_cfg['mode']} api_key={mask_key(text_cfg['api_key'])}")

    vision_cfg = None
    if args.vision_env:
        vpath = Path(args.vision_env)
        if not vpath.exists():
            print(f"多模态 .env 不存在: {vpath}")
            return 2
        vision_cfg = client_cfg(load_env_file(vpath), "VISION_")
        print(f"[视觉配置] base_url={vision_cfg['base_url']} model={vision_cfg['model']} "
              f"api_key={mask_key(vision_cfg['api_key'])}")

    specs = build_specs(args.tasks)
    scene1(specs, text_cfg, args.retries, args.workers)
    scene2(specs, text_cfg, args.retries, args.skip_scan)
    if vision_cfg:
        scene3(text_cfg, vision_cfg)
    print("\n实验完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())