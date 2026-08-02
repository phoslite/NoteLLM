"""画像 API（M9 三层画像）：查看三层画像、重置、阈值查看/保存/自动学习。"""
from fastapi import APIRouter, Depends
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
from app.services.profile_service import get_all_profiles, reset_profiles
from app.services.recommendation_service import generate_recommendations

router = APIRouter(prefix="/api", tags=["profile"])


class ThresholdsIn(BaseModel):
    warm_threshold: int | None = None
    related_strength: float | None = None
    review_days: int | None = None


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