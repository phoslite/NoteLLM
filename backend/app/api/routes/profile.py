"""画像 API（M9 三层画像）：查看三层画像、重置、阈值查看/保存/自动学习。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import ok
from app.services.profile_learning import (
    get_thresholds,
    learn_thresholds,
    learning_state,
    save_thresholds,
)
from app.services.profile_service import (
    calibrate_knowledge_level,
    get_all_profiles,
    refresh_profiles,
    reset_profiles,
)
from app.services.profile_service import (
    update_cold_profile as update_cold_profile_service,
)
from app.services.recommendation_service import generate_recommendations

router = APIRouter(prefix="/api", tags=["profile"])


class ColdProfileIn(BaseModel):
    domain_preferences: dict[str, int] | None = None
    long_term_interests: list[str] | None = None
    knowledge_level: str | None = None


class ThresholdsIn(BaseModel):
    warm_threshold: int | None = None
    related_strength: float | None = None
    review_days: int | None = None


@router.patch("/profile/cold")
def update_cold_profile(body: ColdProfileIn, db: Session = Depends(get_db)):
    """手动编辑冷画像（方案 A：仅冷画像可编辑——领域偏好 / 长期兴趣 / 知识水平）。"""
    try:
        return ok(
            update_cold_profile_service(
                db,
                domain_preferences=body.domain_preferences,
                long_term_interests=body.long_term_interests,
                knowledge_level=body.knowledge_level,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/profile")
def read_profile(db: Session = Depends(get_db)):
    """读取三层画像：{cold, warm, hot}（热>暖>冷 读取优先级）。"""
    return ok(get_all_profiles(db))


@router.get("/profile/thresholds")
def read_thresholds(db: Session = Depends(get_db)):
    """读取画像阈值与学习状态（需求 3.4.1：阈值可查看、可手动调整）。"""
    return ok({**get_thresholds(db), "learning": learning_state(db)})


@router.patch("/profile/thresholds")
def update_thresholds(body: ThresholdsIn, db: Session = Depends(get_db)):
    """手动覆盖画像阈值（系统按跨书节奏自动学习，可手动调整；学习状态不开放手动改）。"""
    return ok(
        save_thresholds(
            db,
            warm_threshold=body.warm_threshold,
            related_strength=body.related_strength,
            review_days=body.review_days,
        ),
        "画像阈值已保存",
    )


@router.post("/profile/learn")
def run_learning(db: Session = Depends(get_db)):
    """立即按归档节奏/确认关联样本重新学习画像阈值（样本不足时保持现值）。"""
    return ok(learn_thresholds(db), "画像阈值学习完成")


@router.get("/profile/recommendations")
def profile_recommendations(db: Session = Depends(get_db)):
    """阅读建议基础版：习惯统计、薄弱概念、复习提醒、阅读节奏（需求 3.4.6）。"""
    return ok(generate_recommendations(db))


@router.post("/profile/reset")
def reset_profile(db: Session = Depends(get_db)):
    """清空三层画像（重新从用户阅读行为积累）。"""
    reset_profiles(db)
    return ok(None, "画像已重置")


@router.post("/profile/refresh")
def refresh_profile(db: Session = Depends(get_db)):
    """重新生成画像（v1.132）：暖主题重算 + 冷画像脏词清洗，不清空任何层。"""
    stats = refresh_profiles(db)
    return ok(stats, "画像已重新生成")


@router.get("/profile/calibrate")
def calibrate_profile(db: Session = Depends(get_db)):
    """知识水平校准建议（v1.135）：按行为证据打分，只建议不写入；由用户确认后手动应用。"""
    return ok(calibrate_knowledge_level(db))