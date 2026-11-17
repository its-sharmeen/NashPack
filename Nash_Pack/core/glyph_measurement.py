"""Robust small-print glyph measurement inside a VLM-localized ROI.

The VLM answers WHAT/WHERE.  This module answers HOW TALL the visible
characters are.  It deliberately combines MSER text candidates, connected
components and projection-based line detection so it does not assume that a
VLM evidence box is already a tight crop around one character.
"""
from typing import Any, Dict, Optional, Tuple
import cv2
import numpy as np


def _gray(roi):
    g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi.copy()
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(g)


def _upscale(g, factor=6):
    factor = max(2, min(int(factor), 8))
    return cv2.resize(g, None, fx=factor, fy=factor, interpolation=cv2.INTER_LANCZOS4)


def _boxes_from_cc(mask, min_area=4):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out=[]
    H,W=mask.shape
    for i in range(1,n):
        x,y,w,h,a=map(int,stats[i])
        if a < min_area or h < 3: continue
        if h > .75*H or w > .65*W: continue
        if w/h > 12 or h/w > 20: continue
        fill=a/max(1,w*h)
        if fill < .015: continue
        out.append((x,y,w,h,a))
    return out


def _boxes_from_mser(g):
    H,W=g.shape
    try:
        mser=cv2.MSER_create(5, max(3,int(.00001*H*W)), max(30,int(.08*H*W)))
    except Exception:
        try: mser=cv2.MSER_create()
        except Exception: return []
    try:
        regions,_=mser.detectRegions(g)
    except Exception: return []
    out=[]
    for pts in regions:
        x,y,w,h=cv2.boundingRect(pts.reshape(-1,1,2))
        area=len(pts)
        if h < 3 or h > .60*H or w > .40*W: continue
        if w/h > 8 or h/w > 15: continue
        if area < max(4,.015*w*h): continue
        out.append((x,y,w,h,area))
    return out


def _cluster_line_heights(boxes, H):
    if len(boxes)<2: return None, [], 0.0
    hs=np.array([b[3] for b in boxes],dtype=float)
    # Character height should be a stable cluster, not the largest object.
    med=np.median(hs); mad=np.median(np.abs(hs-med))+1e-6
    candidates=hs[(np.abs(hs-med)<=max(2.5*mad,.35*med))]
    if len(candidates)<2: candidates=hs
    q20,q80=np.percentile(candidates,[20,80])
    candidates=candidates[(candidates>=q20)&(candidates<=q80)] if len(candidates)>3 else candidates
    if len(candidates)<2: return None,[],0.0
    value=float(np.median(candidates))
    keep=[]
    tol=max(2.5,.30*value)
    for b in boxes:
        if abs(b[3]-value)<=tol: keep.append(b)
    # Require same-line support where possible.  Cluster y-centres by ~0.7x height.
    ys=np.array([b[1]+b[3]/2 for b in keep],float)
    if len(ys):
        order=np.argsort(ys); groups=[]; cur=[]
        for idx in order:
            if not cur or abs(ys[idx]-ys[cur[-1]]) <= .75*value: cur.append(idx)
            else: groups.append(cur); cur=[idx]
        if cur: groups.append(cur)
        groups.sort(key=len, reverse=True)
        if groups and len(groups[0])>=2:
            keep=[keep[i] for i in groups[0]]
    spread=float(np.median(np.abs(np.array([b[3] for b in keep])-value))) if keep else 99
    return value,keep,spread


def measure_glyph_height(roi: np.ndarray, upscale_factor: int = 6) -> Tuple[Optional[float], Dict[str, Any]]:
    if roi is None or roi.size==0: return None,{"reason":"empty_roi"}
    g=_gray(roi); oh,ow=g.shape
    if oh<8 or ow<8: return None,{"reason":"tiny_roi"}
    up=_upscale(g,upscale_factor); H,W=up.shape
    # Remove a small border so a VLM box edge cannot become a fake character.
    pad=max(2,int(.015*min(H,W))); u=up[pad:H-pad,pad:W-pad] if H>2*pad and W>2*pad else up
    candidates=[]
    for inv in (False,True):
        base=255-u if inv else u
        # MSER is especially useful for tiny printed characters.
        boxes=_boxes_from_mser(base)
        val,keep,spread=_cluster_line_heights(boxes,u.shape[0])
        if val is not None: candidates.append((val,keep,spread,"mser_light" if not inv else "mser_dark"))
        # Connected-component fallback with several threshold styles.
        for mode in (cv2.THRESH_BINARY,cv2.THRESH_BINARY_INV):
            _,m=cv2.threshold(base,0,255,mode+cv2.THRESH_OTSU)
            m=cv2.morphologyEx(m,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
            boxes=_boxes_from_cc(m,max(4,int(.000015*u.shape[0]*u.shape[1])))
            val,keep,spread=_cluster_line_heights(boxes,u.shape[0])
            if val is not None: candidates.append((val,keep,spread,"cc"))
        # Adaptive threshold handles labels with gradients/shadows.
        m=cv2.adaptiveThreshold(base,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,5)
        boxes=_boxes_from_cc(m,max(4,int(.000015*u.shape[0]*u.shape[1])))
        val,keep,spread=_cluster_line_heights(boxes,u.shape[0])
        if val is not None: candidates.append((val,keep,spread,"adaptive"))
    if not candidates:
        return None,{"reason":"no_text_characters_detected","roi_size_px":[ow,oh]}
    vals=np.array([c[0] for c in candidates],float)
    med=float(np.median(vals)); distances=np.abs(vals-med)
    # Prefer methods agreeing with the ensemble median.
    good=[c for c,d in zip(candidates,distances) if d<=max(3,.22*med)]
    if not good: good=[min(candidates,key=lambda c:abs(c[0]-med))]
    best=min(good,key=lambda c:(-len(c[1]), c[2], abs(c[0]-med)))
    measured=med/float(upscale_factor)
    kept=best[1]
    boxes=[]
    for x,y,w,h,a in kept:
        boxes.append([int(round((x+pad)/upscale_factor)),int(round((y+pad)/upscale_factor)),int(round((x+w+pad)/upscale_factor)),int(round((y+h+pad)/upscale_factor))])
    spread=float(np.median(np.abs(vals-med))/upscale_factor) if len(vals) else 99
    count=len(boxes)
    confidence="HIGH" if count>=5 and spread<=max(.8,.12*measured) else ("MEDIUM" if count>=2 else "LOW")
    return measured,{
        "glyph_components_method":"MSER + multi-threshold connected-component ensemble",
        "upscale_factor":upscale_factor,
        "glyph_height_candidates_px":[round(float(v/upscale_factor),3) for v in vals],
        "glyph_height_spread_px":round(spread,3),
        "glyph_count_used":count,
        "glyph_boxes":boxes,
        "measurement_confidence":confidence,
        "detector_note":"VLM ROI was treated as a search region; CV independently isolated character-sized components.",
    }
