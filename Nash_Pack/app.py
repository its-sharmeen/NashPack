import os
import csv
import io
import uuid

from dotenv import load_dotenv

# Load .env before anything reads os.getenv() — must happen before the
# core modules below are imported, since vlm_extractor reads
# GEMINI_API_KEY / GEMINI_VLM_MODEL at call time but auth reads
# LM_AUTH_USERS at import-adjacent time too.
load_dotenv()

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
    jsonify,
    session,
)

from core.vlm_extractor import extract_with_vlm
from core.ocr_fallback_extractor import extract_with_ocr
from core.compliance_engine import run_compliance_check
from core.applicability_engine import evaluate_applicability
from core.calibration_engine import detect_qr_scale
from core.font_measurement import measure_font_sizes, filter_applicable_font_regions
from core.rule_registry import RULE_REGISTRY
from core.annotation_engine import annotate_image
from core.presentation_engine import build_result_view_model
from core.report_generator import generate_pdf_report
from core.db import (
    init_db,
    save_scan,
    get_scan,
    list_scans,
    dashboard_stats,
)
from core.auth import (
    verify_login,
    current_user,
    login_required,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)

REPORT_DIR = os.path.join(
    BASE_DIR,
    "static",
    "reports"
)

ALLOWED_EXT = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "bmp"
}


os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)


app = Flask(__name__)

# Camera/QR calibration needs a normal secure web context; no WebXR permission is used.

app.secret_key = os.getenv("FLASK_SECRET_KEY", "sih-2026-ps26034-prototype")

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


@app.context_processor
def inject_user():
    # Makes {{ current_user }} available in every template (nav bar,
    # role-gated UI elements) without passing it explicitly each time.
    return {"current_user": current_user()}


# Initialize database
init_db()


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXT
    )


# ============================================================
# AUTH
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    role = verify_login(username, password)

    if not role:
        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    session["username"] = username
    session["role"] = role

    flash(f"Signed in as {username} ({role}).", "success")

    next_url = request.args.get("next") or url_for("dashboard")
    return redirect(next_url)


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("index"))


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    stats = dashboard_stats()

    recent = list_scans(limit=8)

    return render_template(
        "index.html",
        stats=stats,
        recent=recent
    )


@app.route("/rules")
def rules_list():
    """Judge/user-facing rule register for the Legal Metrology packaged-commodities framework."""
    groups = []
    order = []
    for item in RULE_REGISTRY:
        group = item.get("group") or "OTHER"
        if group not in order:
            order.append(group)
            groups.append({"name": group.replace("_", " ").title(), "items": []})
        groups[order.index(group)]["items"].append(item)
    return render_template("rules.html", groups=groups)


# ============================================================
# SCAN
# ============================================================

@app.route("/ar-measure")
@login_required
def ar_measure():
    """QR-reference lettering measurement workspace.

    A fixed-size 50 mm QR reference supplies physical scale and four-corner
    perspective calibration; Gemini VLM and CV perform the lettering measurement.
    """
    return render_template("ar_measure.html")


@app.route("/scan", methods=["GET", "POST"])
@login_required
def scan():
    if request.method == "GET":
        return render_template("scan.html")

    files = [f for f in request.files.getlist("images") if f and f.filename]
    if not files:
        # Backward compatibility with the old single-image form.
        files = [f for f in request.files.getlist("image") if f and f.filename]
    if not files:
        flash("Please add at least one product image.", "error")
        return redirect(url_for("scan"))
    if len(files) > 8:
        flash("A maximum of 8 package images can be analysed in one inspection.", "error")
        return redirect(url_for("scan"))

    product_label = request.form.get("product_label", "").strip()
    saved=[]
    for file in files:
        if not allowed_file(file.filename):
            flash(f"Unsupported image type: {file.filename}", "error")
            return redirect(url_for("scan"))
        ext=file.filename.rsplit(".",1)[1].lower()
        fname=f"{uuid.uuid4().hex}.{ext}"
        fpath=os.path.join(UPLOAD_DIR,fname)
        file.save(fpath)
        saved.append((fname,fpath))

    per_image=[]
    extraction_sources=[]
    errors=[]

    for index,(fname,fpath) in enumerate(saved, start=1):
        print("\n" + "="*70)
        print(f"STARTING GEMINI VLM — IMAGE {index}/{len(saved)}")
        print("="*70)
        vlm_result=None; vlm_error=None; source="GEMINI_VLM"
        try:
            vlm_result=extract_with_vlm(fpath)
            print("VLM SUCCESS")
        except Exception as e:
            print(f"VLM ERROR — OCR fallback: {e}")
            try:
                vlm_result=extract_with_ocr(fpath)
                source="OCR_FALLBACK"
                errors.append(f"Image {index}: Gemini VLM unavailable; local OCR fallback used.")
            except Exception as oe:
                vlm_error=f"VLM error: {e}; OCR fallback error: {oe}"
                errors.append(f"Image {index}: {vlm_error}")

        if not isinstance(vlm_result,dict):
            vlm_result={}
        extraction_sources.append(source)

        calibration=detect_qr_scale(fpath)
        # Font measurement is VLM-only by design. OCR fallback may support
        # declaration continuity, but it never supplies physical font geometry.
        evidence=_mandatory_font_regions(vlm_result, vlm_result.get("evidence_regions",[]) or []) if source == "GEMINI_VLM" else []
        pdp_bbox=vlm_result.get("principal_display_panel_bbox")
        visual=vlm_result.get("visual_analysis") or {}
        formed=bool(vlm_result.get("formed_moulded_embossed_container"))
        medical=bool(vlm_result.get("medical_device_or_drug"))
        scale_source = calibration if calibration.get("available") else None
        font=measure_font_sizes(fpath,evidence,calibration,pdp_bbox=pdp_bbox,formed=formed,medical_device=medical,scale_source=scale_source)

        annotated_rel=f"annotated/{fname}"
        annotated_path=os.path.join(BASE_DIR,"static",annotated_rel)
        try:
            annotation=annotate_image(fpath,annotated_path,evidence,calibration,pdp_bbox=pdp_bbox)
            annotation["web_path"]=annotated_rel.replace(os.sep,"/")
        except Exception as ae:
            annotation={"path":None,"web_path":None,"regions_annotated":0,"error":str(ae)}

        per_image.append({
            "index":index,"filename":fname,"image_path":f"uploads/{fname}",
            "vlm":vlm_result,"vlm_error":vlm_error,"extraction_source":source,
            "calibration":calibration,"scale_source":scale_source,"font_measurement":font,"annotation":annotation,
        })

    # Merge semantic observations across front/back/side images. The VLM is still
    # the only primary perception source; OCR is used only per-image on failure.
    def merge_value(key):
        for item in per_image:
            value=item["vlm"].get(key)
            if value not in (None,"",[],{}):
                return value
        return None

    merged={}
    schema_keys=set()
    for item in per_image: schema_keys.update(item["vlm"].keys())
    for key in schema_keys:
        vals=[item["vlm"].get(key) for item in per_image]
        if key in {"fssai_numbers"}:
            out=[]
            for v in vals:
                if isinstance(v,list):
                    for x in v:
                        if x and x not in out: out.append(x)
            merged[key]=out
        elif key in {"evidence","visual_warnings"}:
            out=[]
            for v in vals:
                if isinstance(v,list):
                    for x in v:
                        if x and x not in out: out.append(x)
            merged[key]=out
        elif key == "evidence_regions":
            # Per-image coordinates are kept separately; they are not mixed.
            merged[key]=[]
        elif key == "visual_analysis":
            # A declaration visible on ANY image is not lost.
            vis={}
            all_visual=[item["vlm"].get("visual_analysis") or {} for item in per_image]
            for vk in set().union(*(v.keys() for v in all_visual)):
                vv=[v.get(vk) for v in all_visual]
                if vk.endswith("_visibility"):
                    order={"CLEAR":5,"BLURRED":3,"OBSCURED":2,"NOT_VISIBLE":1,"UNKNOWN":0}
                    vis[vk]=max(vv,key=lambda x:order.get(str(x).upper(),0)) if vv else "UNKNOWN"
                elif vk=="visual_warnings":
                    vis[vk]=[x for v in vv if isinstance(v,list) for x in v]
                elif vk in {"blur_detected","occlusion_detected","possible_font_size_issue"}:
                    vis[vk]=any(bool(x) for x in vv)
                else:
                    # For overall/readability, retain strongest clear signal.
                    vis[vk]=next((x for x in vv if str(x).upper()=="CLEAR"), vv[0] if vv else "UNKNOWN")
            merged[key]=vis
        elif all(isinstance(v,bool) for v in vals if v is not None) and any(v is not None for v in vals):
            merged[key]=any(vals)
        else:
            merged[key]=merge_value(key)

    # Preserve PDP geometry from the image that supplied it for the aggregate
    # record, while all real measurements remain image-specific.
    merged["source_images"]=[x["image_path"] for x in per_image]
    merged["image_count"]=len(per_image)

    all_failed = not any(isinstance(x.get("vlm"), dict) and x.get("vlm") for x in per_image)
    compliance_result=run_compliance_check(merged,vlm_error=("; ".join(errors) if all_failed else None))
    applicability=evaluate_applicability(merged)
    compliance_result["calibration"]={
        "available":any(x["calibration"].get("available") for x in per_image),
        "multi_image":len(per_image)>1,
        "images": [x["calibration"] for x in per_image],
    }
    compliance_result["font_measurement"]={
        "status":"MEASURED" if any(x["font_measurement"].get("items") for x in per_image) else "REVIEW_REQUIRED",
        "calibration_available":any(x["font_measurement"].get("calibration_available") for x in per_image),
        "items":[dict(item, image_index=x["index"]) for x in per_image for item in x["font_measurement"].get("items",[])],
        "images":[x["font_measurement"] for x in per_image],
        "reason":"Measurements are image-specific because each image has its own camera geometry and calibration reference.",
    }
    compliance_result["annotation"]={"multi_image":len(per_image)>1,"images":[x["annotation"] for x in per_image]}
    compliance_result["images"]=per_image
    compliance_result["additional_information"]=compliance_result.get("additional_information") or {}
    compliance_result["additional_information"]["classification"]=applicability["classification"]
    compliance_result["additional_information"]["applicability_checks"]=applicability["checks"]
    compliance_result["additional_information"]["extraction_source"]=("GEMINI_VLM" if all(x=="GEMINI_VLM" for x in extraction_sources) else "MIXED_IMAGES")
    compliance_result["additional_information"]["image_count"]=len(per_image)
    flags=applicability["classification"]
    if flags.get("rule3_exclusion_candidate") or flags.get("rule26_exemption_candidate"):
        applicability_summary="CONDITIONAL / REVIEW"
    elif flags.get("prepackaged_candidate"):
        applicability_summary="IN-SCOPE CANDIDATE"
    else:
        applicability_summary="REVIEW"
    compliance_result["additional_information"]["applicability_summary"]=applicability_summary
    compliance_result["additional_information"]["inspection_mode"]="MULTI-IMAGE PACKAGE INSPECTION" if len(per_image)>1 else "SINGLE-IMAGE INSPECTION"
    compliance_result["evidence"]=merged.get("evidence",[])
    compliance_result["warnings"]=compliance_result.get("warnings") or []
    compliance_result["warning_messages"]=compliance_result.get("warning_messages") or []
    compliance_result["warning_messages"].extend(errors)

    scan_id=save_scan(product_label,saved[0][0] and f"uploads/{saved[0][0]}",compliance_result)
    return redirect(url_for("result",scan_id=scan_id))


# ============================================================
# RESULT
# ============================================================

@app.route("/result/<int:scan_id>")
@login_required
def result(scan_id):

    scan_data = get_scan(scan_id)

    if not scan_data:

        flash(
            "Scan not found.",
            "error"
        )

        return redirect(
            url_for("index")
        )

    result_data = scan_data["result"]
    presentation = build_result_view_model(result_data, scan_data)

    return render_template(
        "result.html",
        scan=scan_data,
        result=result_data,
        presentation=presentation,
    )


# ============================================================
# PDF REPORT
# ============================================================

@app.route("/report/<int:scan_id>.pdf")
@login_required
def download_report(scan_id):

    scan_data = get_scan(scan_id)

    if not scan_data:
        return "Not found", 404

    out_path = os.path.join(
        REPORT_DIR,
        f"compliance_report_{scan_id}.pdf"
    )

    generate_pdf_report(
        scan_id,
        scan_data["product_label"],
        scan_data["result"],
        out_path
    )

    return send_file(
        out_path,
        as_attachment=True,
        download_name=f"compliance_report_{scan_id}.pdf"
    )


# ============================================================
# EDITABLE (CSV) REPORT — satisfies "export to PDF and editable formats"
# ============================================================

@app.route("/report/<int:scan_id>.csv")
@login_required
def download_report_csv(scan_id):
    scan_data = get_scan(scan_id)
    if not scan_data:
        return "Not found", 404

    result = scan_data["result"]
    presentation = build_result_view_model(result, scan_data)
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["LEGAL METROLOGY COMPLIANCE REPORT", f"Inspection #{scan_id:04d}"])
    writer.writerow(["Product", scan_data.get("product_label") or ""])
    writer.writerow(["Status", presentation["header"]["verdict_label"]])
    writer.writerow(["Score", result.get("score") or ""])
    writer.writerow(["Applicable declarations", presentation["font_summary"]["applicable"]])
    writer.writerow(["Font requirements passed", f"{presentation['font_summary']['passed']}/{presentation['font_summary']['applicable']}"])
    writer.writerow(["Views analysed", len(presentation["views"])])
    writer.writerow([])

    writer.writerow(["APPLICABLE LEGAL METROLOGY DECLARATIONS + RULE 7"])
    writer.writerow([
        "RULE", "DECLARATION", "VALUE", "STATUS", "APPLICABILITY",
        "FINAL_HEIGHT_MM", "RULE7_MINIMUM_MM", "RULE7_STATUS",
        "MEASUREMENT_VIEWS", "MEASUREMENT_METHOD", "REASON"
    ])
    for row in presentation["declarations"]:
        font = row.get("font") or {}
        writer.writerow([
            row["rule"],
            row["label"],
            row["value"] if row["value"] not in (None, "") else "",
            row["status_label"],
            row["applicability"],
            font.get("height_mm", ""),
            font.get("minimum_mm", ""),
            font.get("rule7_status_label", "REVIEW"),
            font.get("view_count", 0),
            font.get("method", ""),
            font.get("status_reason") or row["evidence"],
        ])

    writer.writerow([])
    writer.writerow(["VISUAL PRESENTATION"])
    writer.writerow(["OVERALL_READABILITY", "OVERALL_PLACEMENT", "VISUAL_STATUS", "REASON"])
    v = presentation["visual_summary"]
    writer.writerow([v["readability"], v["placement"], v["status_label"], v["reason"]])

    writer.writerow([])
    writer.writerow(["OTHER RULES"])
    writer.writerow(["RULE", "STATUS", "APPLICABILITY", "DETECTED VALUE", "REASON"])
    for row in presentation["other_rules"]:
        writer.writerow([
            row["rule"], row["status_label"], row["applicability"],
            row["value"] if row["value"] not in (None, "") else "", row["reason"]
        ])

    mem = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"compliance_report_{scan_id}.csv",
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    stats = dashboard_stats()

    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    scans = list_scans(
        limit=200,
        query=query or None,
        status=status_filter or None,
    )

    return render_template(
        "dashboard.html",
        stats=stats,
        scans=scans,
        query=query,
        status_filter=status_filter,
    )


# ============================================================
# API
# ============================================================

@app.route("/api/scans")
@login_required
def api_scans():

    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    return jsonify(
        list_scans(limit=200, query=query or None, status=status_filter or None)
    )


# ============================================================
# START SERVER
# ============================================================

# ============================================================
# PRECISION AR FONT MEASUREMENT API
# ============================================================

@app.route("/api/qr-calibrate", methods=["POST"])
@login_required
def api_qr_calibrate():
    """Detect the fixed-size 50 mm QR physical reference from a camera frame."""
    upload = request.files.get("image")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "No calibration image was supplied."}), 400
    ext = (upload.filename.rsplit(".", 1)[1].lower() if "." in upload.filename else "jpg")
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "Unsupported image type."}), 400
    fname = f"qr_cal_{uuid.uuid4().hex}.{ext}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    upload.save(fpath)
    try:
        calibration = detect_qr_scale(fpath)
        if not calibration.get("available"):
            return jsonify({"ok": False, "calibration": calibration, "error": calibration.get("reason")}), 422
        return jsonify({"ok": True, "calibration": calibration})
    finally:
        try:
            os.remove(fpath)
        except OSError:
            pass


def _mandatory_font_regions(vlm, evidence_regions):
    """Backward-compatible wrapper around the centralized applicability filter."""
    return filter_applicable_font_regions(vlm, evidence_regions)


@app.route("/api/measure-font", methods=["POST"])
@login_required
def api_measure_font():
    """Process 1-8 camera captures with independent QR metric calibration."""
    uploads = [f for f in request.files.getlist("images") if f and f.filename]
    if not uploads:
        uploads = [f for f in request.files.getlist("image") if f and f.filename]
    if not uploads:
        return jsonify({"ok": False, "error": "No images were supplied."}), 400
    if len(uploads) > 8:
        return jsonify({"ok": False, "error": "A maximum of 8 QR captures can be measured in one inspection."}), 400

    selected = request.form.get("field", "").strip().lower()
    saved=[]
    for upload in uploads:
        ext = (upload.filename.rsplit(".",1)[1].lower() if "." in upload.filename else "jpg")
        if ext not in ALLOWED_EXT:
            return jsonify({"ok": False, "error": f"Unsupported image type: {upload.filename}"}), 400
        fname=f"ar_{uuid.uuid4().hex}.{ext}"
        fpath=os.path.join(UPLOAD_DIR,fname)
        upload.save(fpath)
        saved.append((fname,fpath))

    per_image=[]; errors=[]; sources=[]
    try:
        from core.measurement_quality import assess_image_quality
        import cv2
        for index,(fname,fpath) in enumerate(saved,1):
            try:
                img=cv2.imread(fpath)
                quality=assess_image_quality(img,min_blur=35.0)
                try:
                    vlm=extract_with_vlm(fpath); source="GEMINI_VLM"
                except Exception as e:
                    vlm=extract_with_ocr(fpath); source="OCR_FALLBACK"
                    errors.append(f"Image {index}: primary visual extraction unavailable; fallback used.")
                if not isinstance(vlm,dict): vlm={}
                calibration=detect_qr_scale(fpath)
                scale_source=calibration if calibration.get("available") else None
                evidence=_mandatory_font_regions(vlm, vlm.get("evidence_regions",[]) or [])
                if selected:
                    evidence=[r for r in evidence if str(r.get("field","")).strip().lower()==selected]
                # Font measurement is only physically defensible when the QR is
                # present in THIS image. Never reuse another image's scale.
                font=measure_font_sizes(
                    fpath,evidence,calibration,
                    pdp_bbox=vlm.get("principal_display_panel_bbox"),
                    formed=bool(vlm.get("formed_moulded_embossed_container")),
                    medical_device=bool(vlm.get("medical_device_or_drug")),
                    scale_source=scale_source,
                ) if evidence and calibration.get("available") else {
                    "status":"REVIEW_REQUIRED","calibration_available":False,"items":[],
                    "images":[],"reason":"A readable 50 mm QR reference was not detected in this capture."
                }
                annotated_rel=f"annotated/{fname}"
                annotated_path=os.path.join(BASE_DIR,"static",annotated_rel)
                try:
                    annotation=annotate_image(fpath,annotated_path,evidence,calibration,pdp_bbox=vlm.get("principal_display_panel_bbox"))
                    annotation["web_path"]=annotated_rel.replace(os.sep,"/")
                except Exception as ae:
                    annotation={"path":None,"web_path":None,"regions_annotated":0,"error":str(ae)}
                per_image.append({"index":index,"filename":fname,"image_path":f"uploads/{fname}",
                    "vlm":vlm,"vlm_error":None,"extraction_source":source,"quality":quality,
                    "calibration":calibration,"scale_source":scale_source,"font_measurement":font,"annotation":annotation})
                sources.append(source)
            except Exception as e:
                errors.append(f"Image {index}: {e}")
                per_image.append({"index":index,"filename":fname,"image_path":f"uploads/{fname}","vlm":{},"vlm_error":str(e),
                    "extraction_source":"ERROR","quality":{},"calibration":{"available":False},"scale_source":None,
                    "font_measurement":{"items":[],"calibration_available":False,"reason":str(e)},"annotation":{}})

        # Aggregate semantic data without mixing coordinate systems.
        merged={}
        keys=set().union(*(x.get("vlm",{}).keys() for x in per_image))
        def first_value(key):
            for x in per_image:
                v=x.get("vlm",{}).get(key)
                if v not in (None,"",[],{}): return v
            return None
        for key in keys:
            vals=[x.get("vlm",{}).get(key) for x in per_image]
            if key=="fssai_numbers":
                out=[]
                for v in vals:
                    if isinstance(v,list):
                        for z in v:
                            if z and z not in out: out.append(z)
                merged[key]=out
            elif key=="evidence_regions": merged[key]=[]
            elif key=="visual_analysis":
                allv=[x.get("vlm",{}).get("visual_analysis") or {} for x in per_image]
                vis={}
                for vk in set().union(*(v.keys() for v in allv)):
                    vv=[v.get(vk) for v in allv]
                    if vk.endswith("_visibility"):
                        order={"CLEAR":5,"BLURRED":3,"OBSCURED":2,"NOT_VISIBLE":1,"UNKNOWN":0}
                        vis[vk]=max(vv,key=lambda z:order.get(str(z).upper(),0)) if vv else "UNKNOWN"
                    elif vk in {"blur_detected","occlusion_detected","possible_font_size_issue"}:
                        vis[vk]=any(bool(z) for z in vv)
                    elif vk=="visual_warnings":
                        vis[vk]=[z for v in vv if isinstance(v,list) for z in v]
                    else:
                        vis[vk]=next((z for z in vv if str(z).upper()=="CLEAR"), vv[0] if vv else "UNKNOWN")
                merged[key]=vis
            elif all(isinstance(v,bool) for v in vals if v is not None) and any(v is not None for v in vals): merged[key]=any(vals)
            else: merged[key]=first_value(key)
        merged["source_images"]=[x["image_path"] for x in per_image]
        merged["image_count"]=len(per_image)
        compliance_result=run_compliance_check(merged,vlm_error=("; ".join(errors) if errors else None))
        applicability=evaluate_applicability(merged)
        compliance_result["calibration"]={"available":any(x["calibration"].get("available") for x in per_image),"multi_image":len(per_image)>1,"images":[x["calibration"] for x in per_image]}
        compliance_result["font_measurement"]={
            "status":"MEASURED" if any(x["font_measurement"].get("items") for x in per_image) else "REVIEW_REQUIRED",
            "calibration_available":any(x["font_measurement"].get("calibration_available") for x in per_image),
            "items":[dict(i,image_index=x["index"]) for x in per_image for i in x["font_measurement"].get("items",[])],
            "images":[x["font_measurement"] for x in per_image],
            "reason":"Each captured view was calibrated independently from its own 50 mm QR reference."
        }
        compliance_result["annotation"]={"multi_image":len(per_image)>1,"images":[x["annotation"] for x in per_image]}
        compliance_result["images"]=per_image
        ai=compliance_result.get("additional_information") or {}
        ai.update({"classification":applicability["classification"],"applicability_checks":applicability["checks"],
                   "image_count":len(per_image),"extraction_source":("GEMINI_VLM" if all(s=="GEMINI_VLM" for s in sources) else "MIXED_IMAGES"),
                   "inspection_mode":"QR-CALIBRATED MULTI-IMAGE INSPECTION" if len(per_image)>1 else "QR-CALIBRATED FONT INSPECTION"})
        compliance_result["additional_information"]=ai
        compliance_result["evidence"]=merged.get("evidence",[]) or []
        compliance_result["warning_messages"]=list(compliance_result.get("warning_messages") or [])+errors
        product_label=merged.get("product_name") or merged.get("common_name") or "QR-calibrated package inspection"
        scan_id=save_scan(product_label,saved[0][0] and f"uploads/{saved[0][0]}",compliance_result)
        return jsonify({"ok":True,"image_count":len(per_image),"calibrated_images":sum(bool(x["calibration"].get("available")) for x in per_image),
                        "font_measurement":compliance_result["font_measurement"],"scan_id":scan_id,"result_url":url_for("result",scan_id=scan_id)})
    except Exception as exc:
        return jsonify({"ok":False,"error":str(exc)}),500


if __name__ == "__main__":

    model = os.getenv(
        "GEMINI_VLM_MODEL",
        "gemini-3.6-flash"
    )

    print()
    print("=" * 70)
    print("LEGAL METROLOGY — VLM SYSTEM")
    print("=" * 70)
    print("Analysis engine : GEMINI VLM")
    print("OCR fallback    : ENABLED (only if Gemini VLM fails)")
    print(f"Model           : {model}")
    print("URL             : http://127.0.0.1:5000")
    print("=" * 70)
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
