from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.auth import get_current_user
from app.database import get_db
from app.models import Ad, User
from app.schemas import AdCreate, AdOut

router = APIRouter(prefix="/ads", tags=["آگهی‌ها"])

@router.get("", response_model=list[AdOut])
def list_ads(q: str | None = None, city: str | None = None, category: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    query = db.query(Ad).filter(Ad.is_active.is_(True))
    if q:
        query = query.filter(Ad.title.contains(q) | Ad.description.contains(q))
    if city:
        query = query.filter(Ad.city == city)
    if category:
        query = query.filter(Ad.category == category)
    return query.order_by(Ad.created_at.desc()).offset(skip).limit(limit).all()

@router.post("", response_model=AdOut, status_code=201)
def create_ad(body: AdCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ad = Ad(**body.model_dump(), owner_id=user.id)
    db.add(ad)
    db.commit()
    db.refresh(ad)
    return ad

@router.delete("/{ad_id}", status_code=204)
def delete_ad(ad_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ad = db.get(Ad, ad_id)
    if ad is None:
        raise HTTPException(status_code=404, detail="آگهی پیدا نشد")
    if ad.owner_id != user.id:
        raise HTTPException(status_code=403, detail="اجازه حذف این آگهی را ندارید")
    ad.is_active = False
    db.commit()
