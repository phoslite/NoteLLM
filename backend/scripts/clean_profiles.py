"""一次性清洗三层画像中的脏术语（2026-08-11 冷记忆分词修复配套）。

背景：v1.69 之前画像 `_terms` 直接使用 extract_keywords 的原始二元组，
导致冷/暖画像混入跨词碎片（类客/题骑）、虚词碎片（的稳/德的）、
泛化词（定义/任意/函数）与 LaTeX 残留（mathrm/frac）。

清洗范围：
- warm.themes：按画像术语规则剔除（recent_books 保留原文，不清洗）；
- cold.domain_preferences / long_term_interests：剔除 + 别名折叠。

用法（在 backend 目录下执行）：
    python scripts/clean_profiles.py            # dry-run，只打印前后统计
    python scripts/clean_profiles.py --apply    # 落库
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.services.graph.terms import sanitize_profile_term_freq  # noqa: E402
from app.services.profile_service import COLD, WARM, _load, _save  # noqa: E402


def _clean_warm_themes(value: dict, apply: bool) -> dict:
    themes = value.get("themes") or {}
    cleaned = sanitize_profile_term_freq({str(k): float(v) for k, v in themes.items()})
    removed = sorted(set(themes) - set(cleaned), key=lambda k: -float(themes.get(k, 0)))[:12]
    print(f"  warm.themes: {len(themes)} -> {len(cleaned)} 词条（移除样例：{'、'.join(removed) or '无'}）")
    if apply:
        value["themes"] = cleaned
    return value


def _clean_cold(value: dict, apply: bool) -> dict:
    prefs = value.get("domain_preferences") or {}
    cleaned = sanitize_profile_term_freq({str(k): float(v) for k, v in prefs.items()})
    removed = sorted(set(prefs) - set(cleaned), key=lambda k: -float(prefs.get(k, 0)))[:12]
    print(f"  cold.domain_preferences: {len(prefs)} -> {len(cleaned)} 词条（移除样例：{'、'.join(removed) or '无'}）")
    interests = value.get("long_term_interests") or []
    if interests:
        c_interests = list(sanitize_profile_term_freq({str(t): 1.0 for t in interests}))
        print(f"  cold.long_term_interests: {len(interests)} -> {len(c_interests)} 词条")
    else:
        c_interests = interests
    if apply:
        value["domain_preferences"] = cleaned
        value["long_term_interests"] = c_interests
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗冷/暖画像脏术语")
    parser.add_argument("--apply", action="store_true", help="落库（默认 dry-run）")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        for layer in (WARM, COLD):
            value = _load(db, layer, "default", {})
            if not value:
                print(f"{layer}: 空，跳过")
                continue
            print(f"{layer}:")
            value = _clean_warm_themes(value, args.apply) if layer == WARM else _clean_cold(value, args.apply)
            if args.apply:
                _save(db, layer, "default", value)
        print("已落库" if args.apply else "dry-run（加 --apply 落库）")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
