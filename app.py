import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
import io
import os
import hashlib
import json
import uuid
import requests

def gas_post(payload):
    try:
        GAS_URL = st.secrets["apps_script_url"]
        resp = requests.post(GAS_URL, json=payload, timeout=30)
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_sheet_data(sheet_name):
    res = gas_post({"action": "get_sheet", "sheet_name": sheet_name})
    if res.get("status") == "ok":
        return res.get("data", [])
    return []

def append_row(sheet_name, row):
    gas_post({"action": "append_row", "sheet_name": sheet_name, "row": row})

def update_cell(sheet_name, row_index, col_index, value):
    gas_post({"action": "update_cell", "sheet_name": sheet_name, "row_index": row_index, "col_index": col_index, "value": str(value)})

def delete_row(sheet_name, row_index):
    gas_post({"action": "delete_row", "sheet_name": sheet_name, "row_index": row_index})

USER_SHEET = "users"
USER_HEADER = ["username", "password_hash", "name", "role", "active"]

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

@st.cache_data(ttl=300)
def load_users_cached():
    return get_sheet_data(USER_SHEET)

def load_users(use_cache=True):
    if use_cache:
        data = load_users_cached()
    else:
        load_users_cached.clear()
        data = get_sheet_data(USER_SHEET)
    if len(data) < 2:
        return pd.DataFrame(columns=USER_HEADER)
    return pd.DataFrame(data[1:], columns=data[0])

def init_users_sheet():
    data = get_sheet_data(USER_SHEET)
    is_empty = (not data) or data == [['']] or (len(data) > 0 and data[0] == [''])
    if is_empty:
        append_row(USER_SHEET, USER_HEADER)
        admin_pw = st.secrets.get("admin_init_password", "admin1234")
        append_row(USER_SHEET, ["admin", hash_pw(admin_pw), "관리자", "admin", "True"])
        load_users_cached.clear()

def save_user(username, password_hash, name, role="employee", active=True):
    data = get_sheet_data(USER_SHEET)
    if not data:
        append_row(USER_SHEET, USER_HEADER)
    append_row(USER_SHEET, [username, password_hash, name, role, str(active)])
    load_users_cached.clear()

def update_user_field(username, field, value):
    data = get_sheet_data(USER_SHEET)
    if not data:
        return
    headers = data[0]
    if field not in headers:
        return
    col_idx = headers.index(field) + 1
    for i, row in enumerate(data[1:], start=2):
        if row[0] == username:
            update_cell(USER_SHEET, i, col_idx, value)
            break
    load_users_cached.clear()

def delete_user(username):
    data = get_sheet_data(USER_SHEET)
    if not data:
        return
    for i, row in enumerate(data[1:], start=2):
        if row[0] == username:
            delete_row(USER_SHEET, i)
            break
    load_users_cached.clear()

def authenticate(username, password):
    df = load_users(use_cache=False)
    if df.empty:
        return None
    row = df[(df["username"] == username) & (df["active"].astype(str) == "True")]
    if row.empty:
        return None
    user = row.iloc[0]
    if user["password_hash"] == hash_pw(password):
        return user.to_dict()
    return None

LOG_SHEET = "quote_logs"
LOG_HEADER = ["log_id", "timestamp", "username", "user_name", "client", "project", "valid_date", "items_json", "total_amount", "contract_done", "contract_amount", "contract_date", "memo"]

def load_logs():
    data = get_sheet_data(LOG_SHEET)
    if len(data) < 2:
        return pd.DataFrame(columns=LOG_HEADER)
    return pd.DataFrame(data[1:], columns=data[0])

def append_log(user, client, project, valid_date, items, total):
    data = get_sheet_data(LOG_SHEET)
    if not data:
        append_row(LOG_SHEET, LOG_HEADER)
    log_id = str(uuid.uuid4())[:8]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items_json = json.dumps(items, ensure_ascii=False)
    append_row(LOG_SHEET, [log_id, ts, user["username"], user["name"], client, project, valid_date, items_json, total, "미계약", "", "", ""])

def update_log_field(log_id, field, value):
    data = get_sheet_data(LOG_SHEET)
    if not data:
        return
    headers = data[0]
    if field not in headers:
        return
    col_idx = headers.index(field) + 1
    for i, row in enumerate(data[1:], start=2):
        if row[0] == log_id:
            update_cell(LOG_SHEET, i, col_idx, value)
            break

WASTE_DATA = {
    "폐콘크리트": 31142,
    "폐아스팔트콘크리트": 32166,
    "건설폐재류": 49571,
    "건설오니": 60891,
    "혼합건설폐기물(5%이하)": 72721,
    "불연성+가연성(5%이하)": 188715,
    "기타+가연성(5%이하)": 192887,
}
TRANSPORT_TABLE = {"30km": 20340, "35km": 22270, "40km": 24130, "50km": 27940, "60km": 31690}

def calculate_transport(mode, m_dist=0):
    if mode == "60km 초과":
        return 31690 + (375 * max(0, m_dist - 60))
    return TRANSPORT_TABLE.get(mode, 20340)

def num_to_kor(num):
    units = ["", "십", "백", "천", "만", "십", "백", "천", "억"]
    nums = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
    result = ""
    for i, n in enumerate(str(int(num))[::-1]):
        if n != "0":
            result = nums[int(n)] + units[i] + result
    return result + "원정"

def generate_pdf(client, project, items, remark, valid_date, total_sum, author_name):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    font = "Helvetica"
    p = "NanumSquareR.ttf"
    if os.path.exists(p):
        pdfmetrics.registerFont(TTFont("NanumFont", p))
        font = "NanumFont"
    c.setFont(font, 25)
    c.drawCentredString(300, 800, "곬 적 서")
    c.setFont(font, 10)
    c.drawString(50, 750, f"일자: {datetime.now().strftime('%Y-%m-%d')}")
    c.drawString(50, 735, f"유효기간: {valid_date}까지")
    c.drawString(50, 715, f"{client if client else '입력하세요'} 귀중")
    c.drawString(50, 695, f"공사명: {project if project else '입력하세요'}")
    c.rect(340, 680, 210, 100)
    c.drawString(345, 765, "등록번호: 308-81-09656")
    c.drawString(345, 745, "상 호 : 대형환경(주)")
    c.drawString(345, 725, "대 표 : 이 관 형 (인)")
    if os.path.exists("stamp.png"):
        c.drawImage("stamp.png", 440, 715, width=35, height=35, mask="auto")
    c.drawString(345, 705, "주 소 : 충남 논산시 벌곡면 대둔로 1290-23")
    c.drawString(345, 688, f"작성자 : {author_name}")
    c.setFont(font, 12)
    c.drawString(50, 650, f"합계금액: 일금 {num_to_kor(total_sum)} (₩ {total_sum:,.0f} / VAT별도)")
    c.setFont(font, 10)
    c.rect(50, 280, 500, 350)
    c.line(50, 610, 550, 610)
    x = [60, 180, 280, 330, 380, 470]
    for h, xp in zip(["품명", "규격", "수량", "단위", "단가", "금액"], x):
        c.drawString(xp, 615, h)
    y = 590
    for it in items:
        c.drawString(60, y, str(it["품명"]))
        c.drawString(180, y, str(it["규격"]))
        c.drawString(280, y, f"{it['수량']:,.2f}")
        c.drawString(330, y, str(it["단위"]))
        c.drawString(380, y, f"{it['단가']:,.0f}")
        c.drawString(470, y, f"{it['금액']:,.0f}")
        y -= 25
    if remark:
        c.drawString(50, 260, "[備考]")
        for i, line in enumerate(remark.split("\n")):
            c.drawString(50, 240 - i * 15, line)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
