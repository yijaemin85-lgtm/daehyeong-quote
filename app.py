import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
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
USER_HEADER = ["username", "password_hash", "name", "role", "active", "phone"]

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
    df = pd.DataFrame(data[1:], columns=data[0])
    if "phone" not in df.columns:
        df["phone"] = ""
    return df

def init_users_sheet():
    data = get_sheet_data(USER_SHEET)
    is_empty = (not data) or data == [['']] or (len(data) > 0 and data[0] == [''])
    if is_empty:
        append_row(USER_SHEET, USER_HEADER)
        admin_pw = st.secrets.get("admin_init_password", "admin1234")
        append_row(USER_SHEET, ["admin", hash_pw(admin_pw), "관리자", "admin", "True", ""])
        load_users_cached.clear()

def save_user(username, password_hash, name, role="employee", active=True, phone=""):
    data = get_sheet_data(USER_SHEET)
    if not data:
        append_row(USER_SHEET, USER_HEADER)
    append_row(USER_SHEET, [username, password_hash, name, role, str(active), phone])
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
LOG_HEADER = ["log_id","timestamp","username","user_name","client","project","valid_date","items_json","total_amount","contract_done","contract_amount","contract_date","memo"]

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

PRICE_SHEET = "price_settings"
PRICE_HEADER = ["key", "value"]

@st.cache_data(ttl=300)
def load_price_settings_cached():
    return get_sheet_data(PRICE_SHEET)

def load_price_settings():
    load_price_settings_cached.clear()
    data = load_price_settings_cached()
    if len(data) < 2:
        return {}
    result = {}
    for row in data[1:]:
        if len(row) >= 2:
            result[row[0]] = row[1]
    return result

def save_price_setting(key, value):
    data = get_sheet_data(PRICE_SHEET)
    if not data:
        append_row(PRICE_SHEET, PRICE_HEADER)
        data = [PRICE_HEADER]
    for i, row in enumerate(data[1:], start=2):
        if row[0] == key:
            update_cell(PRICE_SHEET, i, 2, str(value))
            load_price_settings_cached.clear()
            return
    append_row(PRICE_SHEET, [key, str(value)])
    load_price_settings_cached.clear()

DEFAULT_WASTE_DATA = {
    "폐콘크리트": 31142,
    "폐아스팔트콘크리트": 32166,
    "건설폐재류": 49571,
    "건설오니": 60891,
    "혼합건설폐기물(5%이하)": 72721,
    "불연성+가연성(5%이하)": 188715,
    "기타+가연성(5%이하)": 192887,
}
DEFAULT_TRANSPORT_TABLE = {
    "30km": 20340, "35km": 22270, "40km": 24130,
    "50km": 27940, "60km": 31690
}
DEFAULT_RECYCLED_GOV_PRICE = 11700
DEFAULT_RECYCLED_PRIVATE_PRICE = 9500
DEFAULT_DUMP_VOLUME = 17.0
DEFAULT_EXTRA_KM_RATE = 375

def get_waste_data():
    settings = load_price_settings()
    result = {}
    for k, default in DEFAULT_WASTE_DATA.items():
        key = f"waste_{k}"
        result[k] = int(settings.get(key, default))
    return result

def get_transport_table():
    settings = load_price_settings()
    result = {}
    for k, default in DEFAULT_TRANSPORT_TABLE.items():
        key = f"transport_{k}"
        result[k] = int(settings.get(key, default))
    return result

def get_recycled_gov_price():
    settings = load_price_settings()
    return int(settings.get("recycled_gov_price", DEFAULT_RECYCLED_GOV_PRICE))

def get_recycled_private_price():
    settings = load_price_settings()
    return int(settings.get("recycled_private_price", DEFAULT_RECYCLED_PRIVATE_PRICE))

def get_dump_volume():
    settings = load_price_settings()
    return float(settings.get("dump_volume", DEFAULT_DUMP_VOLUME))

def get_extra_km_rate():
    settings = load_price_settings()
    return int(settings.get("extra_km_rate", DEFAULT_EXTRA_KM_RATE))

def calculate_transport(mode, m_dist=0):
    transport_table = get_transport_table()
    extra_km_rate = get_extra_km_rate()
    if mode == "60km 초과":
        return transport_table.get("60km", 31690) + (extra_km_rate * max(0, m_dist - 60))
    return transport_table.get(mode, transport_table.get("30km", 20340))

def num_to_kor(num):
    if num == 0:
        return "영원정"
    units = ["","십","백","천","만","십만","백만","천만","억"]
    nums = ["","일","이","삼","사","오","육","칠","팔","구"]
    n = int(num)
    result = ""
    digits = str(n)
    for i, d in enumerate(reversed(digits)):
        if d != "0":
            result = nums[int(d)] + units[i] + result
    return result + "원정"


def generate_pdf(client, project, items, remark, valid_date, total_sum, author_name, author_phone="", show_author=False):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    W, H = A4  # 595, 842

    # 폰트 등록
    font_r = "Helvetica"
    font_b = "Helvetica-Bold"
    if os.path.exists("NanumSquareR.ttf"):
        pdfmetrics.registerFont(TTFont("NanumR", "NanumSquareR.ttf"))
        font_r = "NanumR"
    if os.path.exists("NanumSquareB.ttf"):
        pdfmetrics.registerFont(TTFont("NanumB", "NanumSquareB.ttf"))
        font_b = "NanumB"
    if os.path.exists("NanumSquareEB.ttf"):
        pdfmetrics.registerFont(TTFont("NanumEB", "NanumSquareEB.ttf"))
    if os.path.exists("NanumSquareL.ttf"):
        pdfmetrics.registerFont(TTFont("NanumL", "NanumSquareL.ttf"))

    margin_l = 30 * mm
    margin_r = W - 30 * mm
    page_w = margin_r - margin_l

    # ── 제목 ──
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 22)
    c.drawCentredString(W / 2, H - 25 * mm, "견     적     서")
    c.setLineWidth(1.5)
    c.line(margin_l, H - 28 * mm, margin_r, H - 28 * mm)

    # ── 좌측: 날짜 / 수신처 / 공사명 ──
    left_x = margin_l
    right_col_x = margin_l + page_w * 0.52
    info_box_w = page_w * 0.46

    # 날짜 파싱
    now = datetime.now()
    date_str = f"서기  {now.year} 년  {now.month} 월  {now.day} 일"
    c.setFont(font_r, 10)
    c.drawString(left_x, H - 34 * mm, date_str)
    # 날짜 밑줄
    date_w = c.stringWidth(date_str, font_r, 10)
    c.setLineWidth(0.5)
    c.line(left_x, H - 35 * mm, left_x + date_w, H - 35 * mm)

    # 수신처 박스
    c.setLineWidth(1.0)
    c.rect(left_x, H - 46 * mm, page_w * 0.48, 8 * mm)
    client_text = f"  {client if client else '(수신처)'}  귀중"
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 11)
    c.drawString(left_x + 3, H - 42 * mm, client_text)

    c.setFont(font_r, 10)
    c.drawString(left_x, H - 51 * mm, "내역을 하기와 같이 제출합니다.")

    c.drawString(left_x, H - 57 * mm, f"유효견적기간   {valid_date}한")

    proj_lines = []
    if project:
        words = project
        if len(words) > 22:
            proj_lines = [words[:22], words[22:44], words[44:]]
            proj_lines = [l for l in proj_lines if l]
        else:
            proj_lines = [words]
    else:
        proj_lines = ["(공사명)"]

    c.drawString(left_x, H - 63 * mm, "공사명 :  " + proj_lines[0])
    for idx, line in enumerate(proj_lines[1:], 1):
        c.drawString(left_x + 18 * mm, H - (63 + idx * 5) * mm, line)

    # ── 우측: 회사 정보 테이블 ──
    info_x = right_col_x
    info_y_top = H - 30 * mm
    info_row_h = 7.5 * mm
    info_rows = [
        ("등  록  번  호", "308-81-09656"),
        ("상          호", "대  형  환  경  (주)"),
        ("성          명", "이  관  형"),
        ("업          태", "서비스 제조"),
        ("주          소", "충남 논산시 벌곡면 대둔로 1290-23"),
        ("전          화", "☎ 041)732-0620  Fax 732-0622"),
    ]

    c.setLineWidth(0.8)
    c.rect(info_x, info_y_top - len(info_rows) * info_row_h, info_box_w, len(info_rows) * info_row_h)
    for i, (label, value) in enumerate(info_rows):
        row_y = info_y_top - (i + 1) * info_row_h
        if i > 0:
            c.line(info_x, row_y + info_row_h, info_x + info_box_w, row_y + info_row_h)
        c.setLineWidth(0.3)
        c.line(info_x + 28 * mm, row_y, info_x + 28 * mm, row_y + info_row_h)
        c.setFont(font_r, 8.5)
        c.drawString(info_x + 2 * mm, row_y + 2 * mm, label)
        if label == "성          명":
            c.drawString(info_x + 30 * mm, row_y + 2 * mm, value)
            if os.path.exists("stamp.png"):
                c.drawImage("stamp.png", info_x + info_box_w - 15 * mm, row_y, width=13 * mm, height=13 * mm, mask="auto")
        elif label == "업          태":
            c.drawString(info_x + 30 * mm, row_y + 4 * mm, value)
            c.setFont(font_r, 7)
            c.drawString(info_x + 46 * mm, row_y + 4 * mm, "종목")
            c.drawString(info_x + 53 * mm, row_y + 4.5 * mm, "건설 폐기물 수집 및 운반,")
            c.drawString(info_x + 53 * mm, row_y + 1 * mm, "중간처리,비계철거,순환골재판매")
        else:
            c.setFont(font_r, 8.5)
            c.drawString(info_x + 30 * mm, row_y + 2 * mm, value)

    # ── 합계금액 행 ──
    total_y = H - 30 * mm - len(info_rows) * info_row_h - 8 * mm
    c.setLineWidth(1.0)
    c.rect(margin_l, total_y - 7 * mm, page_w, 7 * mm)
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 10)
    if total_sum and total_sum > 0:
        total_kor = num_to_kor(total_sum)
        total_str = f"합  계  금  액  :    일금  {total_kor}    ( ₩  {total_sum:,.0f}  )"
    else:
        total_str = "합  계  금  액  :    본 견적은 단위 단가 견적임    ( ₩  -  )"
    c.drawString(margin_l + 5 * mm, total_y - 4.5 * mm, total_str)

    # ── 품목 테이블 ──
    table_y_top = total_y - 7 * mm
    col_no = margin_l
    col_name = margin_l + 10 * mm
    col_spec = margin_l + 55 * mm
    col_qty = margin_l + 82 * mm
    col_unit = margin_l + 96 * mm
    col_trans = margin_l + 110 * mm
    col_price = margin_l + 130 * mm
    col_amount = margin_l + 153 * mm
    col_remark = margin_l + 175 * mm
    col_end = margin_r

    row_h = 7 * mm
    header_h = 12 * mm

    # 헤더
    c.setLineWidth(0.8)
    c.rect(col_no, table_y_top - header_h, page_w, header_h)
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 8.5)

    headers_info = [
        (col_no, col_name, "No"),
        (col_name, col_spec, "품     명"),
        (col_spec, col_qty, "규     격"),
        (col_qty, col_unit, "수량"),
        (col_unit, col_trans, "단위"),
        (col_trans, col_price, "운반비"),
        (col_price, col_amount, "처리비/제품비"),
        (col_amount, col_remark, "금     액"),
        (col_remark, col_end, "비고"),
    ]
    for i, (x_start, x_end, label) in enumerate(headers_info):
        mid_x = (x_start + x_end) / 2
        if i == 5 or i == 6:
            c.setFont(font_r, 7)
            c.drawCentredString(mid_x, table_y_top - 5 * mm, label)
        else:
            c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 8.5)
            c.drawCentredString(mid_x, table_y_top - 7 * mm, label)
        if i > 0:
            c.setLineWidth(0.3)
            c.line(x_start, table_y_top - header_h, x_start, table_y_top)

    # "단 가" 상단 헤더
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 8.5)
    c.drawCentredString((col_trans + col_amount) / 2, table_y_top - 3 * mm, "단     가")
    c.setLineWidth(0.3)
    c.line(col_trans, table_y_top - header_h / 2, col_amount, table_y_top - header_h / 2)

    # 데이터 행
    max_data_rows = 15
    data_rows_y = table_y_top - header_h
    c.setLineWidth(0.8)
    c.rect(col_no, data_rows_y - max_data_rows * row_h, page_w, max_data_rows * row_h)

    blank_after = False
    for row_i, item in enumerate(items[:max_data_rows]):
        row_y = data_rows_y - (row_i + 1) * row_h
        c.setLineWidth(0.3)
        c.line(col_no, row_y + row_h, col_end, row_y + row_h)
        for x_start, x_end, _ in headers_info[1:]:
            c.line(x_start, row_y, x_start, row_y + row_h)

        c.setFont(font_r, 9)
        c.drawCentredString((col_no + col_name) / 2, row_y + 2 * mm, str(row_i + 1) + ".")
        # 품명 (글자 잘림 처리)
        name_str = str(item.get("품명", ""))
        c.drawString(col_name + 1 * mm, row_y + 2 * mm, name_str[:12])
        c.drawString(col_spec + 1 * mm, row_y + 2 * mm, str(item.get("규격", ""))[:8])
        c.drawCentredString((col_qty + col_unit) / 2, row_y + 2 * mm, f"{item.get('수량', 0):,.2f}")
        c.drawCentredString((col_unit + col_trans) / 2, row_y + 2 * mm, str(item.get("단위", "")))

        trans_val = item.get("운반비", 0)
        price_val = item.get("처리비", item.get("제품비", item.get("단가", 0)))
        amount_val = item.get("금액", 0)
        remark_val = item.get("비고", "")

        if trans_val and int(trans_val) > 0:
            c.drawRightString(col_price - 1 * mm, row_y + 2 * mm, f"{int(trans_val):,}")
        else:
            c.drawCentredString((col_trans + col_price) / 2, row_y + 2 * mm, "-")
        c.drawRightString(col_amount - 1 * mm, row_y + 2 * mm, f"{int(price_val):,}")
        c.drawRightString(col_remark - 1 * mm, row_y + 2 * mm, f"{int(amount_val):,}")
        c.drawCentredString((col_remark + col_end) / 2, row_y + 2 * mm, str(remark_val))

    # 이하여백
    next_row = len(items)
    if next_row < max_data_rows:
        blank_row_y = data_rows_y - (next_row + 1) * row_h
        c.setFont(font_r, 9)
        c.drawCentredString(W / 2, blank_row_y + 2 * mm, "—  이  하  여  백  —")
        for extra_i in range(next_row + 1, max_data_rows):
            row_y = data_rows_y - (extra_i + 1) * row_h
            c.setLineWidth(0.2)
            c.line(col_no, row_y + row_h, col_end, row_y + row_h)

    # 합계 행
    sum_row_y = data_rows_y - max_data_rows * row_h
    c.setLineWidth(0.8)
    c.rect(col_no, sum_row_y - row_h, page_w, row_h)
    for x_start, x_end, _ in headers_info[1:]:
        c.setLineWidth(0.3)
        c.line(x_start, sum_row_y - row_h, x_start, sum_row_y)
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 9)
    c.drawCentredString(col_name + (col_spec - col_name) * 0.3, sum_row_y - row_h + 2 * mm, "[  합      계  ]")
    if total_sum and total_sum > 0:
        c.drawRightString(col_remark - 1 * mm, sum_row_y - row_h + 2 * mm, f"{int(total_sum):,}")

    # 비고
    remark_y = sum_row_y - row_h - 5 * mm
    c.setFont(font_b if font_b != "Helvetica-Bold" else font_r, 9)
    c.drawString(margin_l, remark_y, "§ 備 考 §")
    c.setFont(font_r, 9)
    for i, line in enumerate(remark.split("\n")):
        c.drawString(margin_l, remark_y - (i + 1) * 5 * mm, line)

    # 담당자
    if show_author and author_name:
        bottom_y = 15 * mm
        c.setFont(font_r, 9)
        contact_str = f"담당자 : {author_name}"
        if author_phone:
            contact_str += f"  (Tel : {author_phone})"
        c.drawRightString(margin_r, bottom_y, contact_str)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


# ─── 로그인 페이지 ───
def show_login_page():
    st.title("🔐 대형환경(주) 통합 견적 시스템")
    st.subheader("로그인")
    with st.form("login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
        if submitted:
            if not username or not password:
                st.error("아이디와 비밀번호를 입력하세요.")
            else:
                user = authenticate(username, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

# ─── 관리자 페이지 ───
def show_admin_page():
    st.title("⚙️ 관리자 페이지")
    if st.button("← 메인으로 돌아가기"):
        st.session_state["page"] = "main"
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["👥 사원 관리", "📋 견적 이력", "💰 단가 관리"])

    with tab1:
        st.subheader("사원 목록")
        df = load_users(use_cache=False)
        if df.empty:
            st.info("등록된 사원이 없습니다.")
        else:
            for _, row in df.iterrows():
                role_label = "관리자" if row["role"] == "admin" else "일반"
                col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
                col1.write(f"**{row['name']}** ({row['username']})" + (f" | {row.get('phone','')}" if row.get('phone') else ""))
                col2.write(role_label)
                col3.write("활성" if str(row["active"]) == "True" else "비활성")
                if row["username"] != "admin":
                    uname = row["username"]
                    if col4.button("탈퇴", key=f"del_{uname}"):
                        st.session_state[f"confirm_del_{uname}"] = True
                    if st.session_state.get(f"confirm_del_{uname}"):
                        st.warning(f"정말 **{row['name']} ({uname})**을 삭제하시겠습니까?")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ 확인 삭제", key=f"confirm_yes_{uname}"):
                            delete_user(uname)
                            st.session_state.pop(f"confirm_del_{uname}", None)
                            st.success(f"{row['name']} 계정이 삭제되었습니다.")
                            st.rerun()
                        if c2.button("❌ 취소", key=f"confirm_no_{uname}"):
                            st.session_state.pop(f"confirm_del_{uname}", None)
                            st.rerun()
        st.divider()
        st.subheader("신규 사원 추가")
        with st.form("add_user_form"):
            new_username = st.text_input("아이디")
            new_name = st.text_input("이름")
            new_phone = st.text_input("휴대전화번호", placeholder="예: 010-1234-5678")
            new_password = st.text_input("비밀번호", type="password")
            new_role = st.selectbox("권한", ["employee", "admin"], format_func=lambda x: "일반" if x == "employee" else "관리자")
            add_submitted = st.form_submit_button("추가")
            if add_submitted:
                if not new_username or not new_name or not new_password:
                    st.error("아이디, 이름, 비밀번호는 필수 항목입니다.")
                else:
                    existing = load_users(use_cache=False)
                    if not existing.empty and new_username in existing["username"].values:
                        st.error("이미 존재하는 아이디입니다.")
                    else:
                        save_user(new_username, hash_pw(new_password), new_name, new_role, phone=new_phone)
                        st.success(f"{new_name} ({new_username}) 계정이 추가되었습니다.")
                        st.rerun()

    with tab2:
        st.subheader("견적 이력")
        logs = load_logs()
        if logs.empty:
            st.info("견적 이력이 없습니다.")
        else:
            for log_i, (_, log) in enumerate(logs.iterrows()):
                lid = log.get("log_id", str(log_i))
                with st.expander(f"[{log.get('timestamp','')}] {log.get('user_name','')} - {log.get('client','')} / {log.get('project','')} (₩{int(float(log.get('total_amount',0) or 0)):,})"):
                    st.write(f"**견적 ID:** {lid}")
                    st.write(f"**작성자:** {log.get('user_name','')} ({log.get('username','')})")
                    st.write(f"**수신처:** {log.get('client','')}")
                    st.write(f"**공사명:** {log.get('project','')}")
                    st.write(f"**유효기간:** {log.get('valid_date','')}")
                    st.write(f"**합계금액:** ₩{int(float(log.get('total_amount',0) or 0)):,}")
                    st.write(f"**계약여부:** {log.get('contract_done','미계약')}")
                    contract_options = ["미계약","계약완료","무산"]
                    cur_status = log.get("contract_done","미계약")
                    if cur_status not in contract_options:
                        cur_status = "미계약"
                    contract_status = st.selectbox(
                        "계약 상태 업데이트",
                        contract_options,
                        index=contract_options.index(cur_status),
                        key=f"status_{lid}_{log_i}"
                    )
                    contract_amount = st.text_input("실계약 금액", value=str(log.get("contract_amount","")), key=f"amount_{lid}_{log_i}")
                    memo = st.text_input("메모", value=str(log.get("memo","")), key=f"memo_{lid}_{log_i}")
                    if st.button("저장", key=f"save_{lid}_{log_i}"):
                        update_log_field(lid, "contract_done", contract_status)
                        update_log_field(lid, "contract_amount", contract_amount)
                        update_log_field(lid, "memo", memo)
                        st.success("저장되었습니다.")
                        st.rerun()

    with tab3:
        st.subheader("💰 단가 관리")
        settings = load_price_settings()

        st.markdown("#### 건설폐기물 처리비 단가 (원/ton)")
        waste_data = get_waste_data()
        with st.form("waste_price_form"):
            new_waste = {}
            cols = st.columns(2)
            for i, (wtype, wprice) in enumerate(waste_data.items()):
                new_waste[wtype] = cols[i % 2].number_input(wtype, min_value=0, value=wprice, step=100, key=f"wp_{wtype}")
            if st.form_submit_button("폐기물 단가 저장"):
                for wtype, wprice in new_waste.items():
                    save_price_setting(f"waste_{wtype}", wprice)
                st.success("폐기물 처리비 단가가 저장되었습니다.")
                st.rerun()

        st.markdown("#### 운반비 단가표 (원/ton)")
        transport_table = get_transport_table()
        with st.form("transport_price_form"):
            new_transport = {}
            cols2 = st.columns(3)
            for i, (dist, tprice) in enumerate(transport_table.items()):
                new_transport[dist] = cols2[i % 3].number_input(dist, min_value=0, value=tprice, step=100, key=f"tp_{dist}")
            extra_rate = int(settings.get("extra_km_rate", DEFAULT_EXTRA_KM_RATE))
            new_extra_rate = st.number_input("60km 초과 시 km당 추가 단가 (원/km)", min_value=0, value=extra_rate, step=10)
            if st.form_submit_button("운반비 단가 저장"):
                for dist, tprice in new_transport.items():
                    save_price_setting(f"transport_{dist}", tprice)
                save_price_setting("extra_km_rate", new_extra_rate)
                st.success("운반비 단가가 저장되었습니다.")
                st.rerun()

        st.markdown("#### 순환골재 제품비 단가")
        with st.form("recycled_price_form"):
            gov_price = get_recycled_gov_price()
            private_price = get_recycled_private_price()
            dump_vol = get_dump_volume()
            new_gov = st.number_input("관급/설계 단가 (원/m³)", min_value=0, value=gov_price, step=100)
            new_private = st.number_input("사급 단가 (원/m³)", min_value=0, value=private_price, step=100)
            new_dump_vol = st.number_input("25톤 덤프트럭 기준 적재용적 (m³/대)", min_value=1.0, value=dump_vol, step=0.5, format="%.1f")
            st.info(f"대당 관급 단가: {int(new_gov * new_dump_vol):,}원  |  대당 사급 단가: {int(new_private * new_dump_vol):,}원")
            if st.form_submit_button("순환골재 단가 저장"):
                save_price_setting("recycled_gov_price", new_gov)
                save_price_setting("recycled_private_price", new_private)
                save_price_setting("dump_volume", new_dump_vol)
                st.success("순환골재 단가가 저장되었습니다.")
                st.rerun()


# ─── 메인 앱 페이지 ───
def show_main_page():
    user = st.session_state["user"]
    role_label = "관리자" if user["role"] == "admin" else "일반"

    with st.sidebar:
        st.markdown(f"### {'🟢' if user['role']=='admin' else '🔵'} {user['name']} 님")
        st.caption(f"권한: {role_label}")
        if user["role"] == "admin":
            if st.button("⚙️ 관리자 페이지"):
                st.session_state["page"] = "admin"
                st.rerun()
        if st.button("🔴 로그아웃"):
            st.session_state.clear()
            st.rerun()

    st.title("📋 대형환경(주) 통합 견적 시스템")

    if "waste_items" not in st.session_state:
        st.session_state["waste_items"] = []
    if "recycled_items" not in st.session_state:
        st.session_state["recycled_items"] = []

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("🔧 견적 데이터 입력")
        with st.form("basic_info_form", clear_on_submit=False):
            client = st.text_input("수신처", value=st.session_state.get("client",""), placeholder="입력하세요 (예: OO설계사무소)")
            project = st.text_input("공사명", value=st.session_state.get("project",""), placeholder="입력하세요 (예: 세종시 OO공사)")
            default_valid = st.session_state.get("valid_date", (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))
            valid_date = st.text_input("유효기간", value=default_valid)
            info_submitted = st.form_submit_button("✔ 기본정보 저장", use_container_width=True)
            if info_submitted:
                st.session_state["client"] = client
                st.session_state["project"] = project
                st.session_state["valid_date"] = valid_date

        client = st.session_state.get("client", "")
        project = st.session_state.get("project", "")
        valid_date = st.session_state.get("valid_date", (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))

        tab_waste, tab_recycled = st.tabs(["♻️ 폐기물 처리", "🪨 순환골재 납품"])

        # ── 폐기물 처리 탭 ──
        with tab_waste:
            waste_data = get_waste_data()
            with st.form("waste_form", clear_on_submit=False):
                waste_type = st.selectbox("폐기물 성상", list(waste_data.keys()))
                qty = st.number_input("수량(ton)", min_value=0.01, value=1.0, step=0.1, format="%.2f")
                dist_mode = st.selectbox("운반거리", ["30km","35km","40km","50km","60km","60km 초과"])
                if dist_mode == "60km 초과":
                    extra_dist = st.number_input("실제거리(km, 60km 초과시)", min_value=61, value=70)
                else:
                    extra_dist = 0
                holiday = st.checkbox("휴일/야간 할증(15%)")
                waste_add = st.form_submit_button("➕ 폐기물 항목 추가", use_container_width=True)
                if waste_add:
                    base = waste_data[waste_type]
                    transport = calculate_transport(dist_mode, extra_dist)
                    unit_price = base + transport
                    if holiday:
                        unit_price = int(unit_price * 1.15)
                    amount = int(unit_price * qty)
                    dist_label = dist_mode if dist_mode != "60km 초과" else f"L={extra_dist}km"
                    st.session_state["waste_items"].append({
                        "품명": waste_type,
                        "규격": dist_label,
                        "수량": qty,
                        "단위": "ton",
                        "운반비": transport,
                        "처리비": base,
                        "단가": unit_price,
                        "금액": amount,
                        "비고": ""
                    })
                    st.rerun()

        # ── 순환골재 납품 탭 ──
        with tab_recycled:
            quote_mode = st.radio(
                "견적 모드",
                ["설계견적", "관급견적", "사급견적"],
                horizontal=True,
                key="recycled_quote_mode"
            )
            delivery_mode = st.radio(
                "납품 조건",
                ["상차도", "도착도"],
                horizontal=True,
                key="recycled_delivery_mode"
            )

            gov_price = get_recycled_gov_price()
            private_price = get_recycled_private_price()
            dump_vol = get_dump_volume()

            is_gov = quote_mode in ["설계견적", "관급견적"]
            auto_unit_price = gov_price if is_gov else private_price

            with st.form("recycled_form", clear_on_submit=False):
                recycled_name = st.text_input("품명", placeholder="예: 순환골재(도로기층용)")
                recycled_spec = st.text_input("규격", placeholder="예: 40mm")

                unit_type = st.radio("수량 단위", ["m³", "대 (25톤 덤프 기준)"], horizontal=True, key="recycled_unit_type")

                recycled_qty = st.number_input("수량", min_value=0.01, value=1.0, step=0.1, format="%.2f")

                if unit_type == "m³":
                    display_unit = "m³"
                    if is_gov:
                        product_price = st.number_input(
                            f"제품비 단가 (원/m³) [관급 기준: {gov_price:,}원]",
                            min_value=0, value=gov_price, step=100
                        )
                    else:
                        product_price = st.number_input("제품비 단가 (원/m³)", min_value=0, value=private_price, step=100)
                else:
                    display_unit = "대"
                    per_truck_gov = int(gov_price * dump_vol)
                    per_truck_pri = int(private_price * dump_vol)
                    if is_gov:
                        product_price = st.number_input(
                            f"제품비 단가 (원/대) [관급 기준: {per_truck_gov:,}원, {dump_vol}m³×{gov_price:,}원]",
                            min_value=0, value=per_truck_gov, step=1000
                        )
                    else:
                        product_price = st.number_input(
                            f"제품비 단가 (원/대) [사급 기준: {per_truck_pri:,}원]",
                            min_value=0, value=per_truck_pri, step=1000
                        )

                # 운반비 (도착도만)
                transport_price = 0
                if delivery_mode == "도착도":
                    transport_table = get_transport_table()
                    if is_gov:
                        transport_options = list(transport_table.keys()) + ["60km 초과", "직접입력"]
                        trans_select = st.selectbox("운반비 단가 선택", transport_options)
                        if trans_select == "직접입력":
                            transport_price = st.number_input("운반비 직접입력 (원)", min_value=0, value=0, step=100)
                        elif trans_select == "60km 초과":
                            extra_km = st.number_input("실제거리(km)", min_value=61, value=70)
                            transport_price = calculate_transport("60km 초과", extra_km)
                            st.info(f"계산된 운반비: {transport_price:,}원")
                        else:
                            transport_price = transport_table.get(trans_select, 0)
                            st.info(f"적용 운반비: {transport_price:,}원")
                    else:
                        transport_price = st.number_input("운반비 단가 직접입력 (원)", min_value=0, value=0, step=100)

                recycled_add = st.form_submit_button("➕ 순환골재 항목 추가", use_container_width=True)
                if recycled_add:
                    amount = int((product_price + transport_price) * recycled_qty)
                    remark_note = delivery_mode
                    st.session_state["recycled_items"].append({
                        "품명": recycled_name if recycled_name else "순환골재",
                        "규격": recycled_spec,
                        "수량": recycled_qty,
                        "단위": display_unit,
                        "운반비": transport_price,
                        "처리비": 0,
                        "제품비": product_price,
                        "단가": product_price + transport_price,
                        "금액": amount,
                        "비고": remark_note
                    })
                    st.rerun()

    # ── 우측: 미리보기 ──
    with col_right:
        st.subheader("🔍 견적 미리보기")
        all_items = st.session_state["waste_items"] + st.session_state["recycled_items"]

        for idx, item in enumerate(all_items):
            c1, c2 = st.columns([4, 1])
            trans_v = item.get("운반비", 0)
            price_v = item.get("제품비", item.get("처리비", item.get("단가", 0)))
            c1.write(f"{idx+1}. **{item['품명']}** ({item['규격']}) : {item['수량']:.2f} {item['단위']} × {item['단가']:,.0f}원 = **{item['금액']:,.0f}원**")
            if c2.button("삭제", key=f"del_item_{idx}"):
                wi = len(st.session_state["waste_items"])
                if idx < wi:
                    st.session_state["waste_items"].pop(idx)
                else:
                    st.session_state["recycled_items"].pop(idx - wi)
                st.rerun()

        total = sum(i["금액"] for i in all_items)
        remark_default = "1. 부가세 별도.\n2. 상차비 별도.\n3. 25.5톤 덤프 용적 17㎥ 적용."
        remark = st.text_area("비고", value=st.session_state.get("remark_input", remark_default), height=80, key="remark_input")

        # 담당자 옵션
        show_author = st.checkbox("담당자 정보 견적서에 포함", value=False, key="show_author_check")
        author_name_default = user.get("name", "")
        author_phone_default = user.get("phone", "")
        if show_author:
            col_a1, col_a2 = st.columns(2)
            author_name = col_a1.text_input("담당자 이름", value=author_name_default, key="author_name_input")
            author_phone = col_a2.text_input("담당자 연락처", value=author_phone_default, key="author_phone_input")
        else:
            author_name = author_name_default
            author_phone = author_phone_default

        st.divider()

        if all_items:
            # 미리보기 HTML
            rows_html = "".join([
                f"<tr><td style='padding:3px 5px;text-align:center'>{i+1}</td>"
                f"<td style='padding:3px 5px'>{it['품명']}</td>"
                f"<td style='padding:3px 5px'>{it['규격']}</td>"
                f"<td style='padding:3px 5px;text-align:right'>{it['수량']:,.2f}</td>"
                f"<td style='padding:3px 5px'>{it['단위']}</td>"
                f"<td style='padding:3px 5px;text-align:right'>{int(it.get('운반비',0)):,}" + ("" if it.get('운반비',0)==0 else "") + "</td>"
                f"<td style='padding:3px 5px;text-align:right'>{int(it.get('제품비',it.get('처리비',it.get('단가',0)))):,}</td>"
                f"<td style='padding:3px 5px;text-align:right'>{it['금액']:,.0f}</td>"
                f"<td style='padding:3px 5px;text-align:center'>{it.get('비고','')}</td></tr>"
                for i, it in enumerate(all_items)
            ])
            is_unit_quote = all(it.get("비고","") in ["상차도","도착도",""] for it in all_items) and any(it.get("비고") in ["상차도","도착도"] for it in all_items)
            total_display = f"본 견적은 단위 단가 견적임  ( ₩ - )" if is_unit_quote else f"일금 {num_to_kor(total)}  ( ₩ {total:,.0f} )"

            st.markdown(f"""
<div style="border:1px solid #444;padding:12px;border-radius:6px;background:#1a1a2e;font-size:12px;">
<h4 style="text-align:center;margin-top:0;letter-spacing:8px">견  적  서</h4>
<p><b>수신:</b> {client if client else "(미입력)"} 귀중 &nbsp;&nbsp; <b>공사명:</b> {project if project else "(미입력)"}</p>
<p><b>합계금액:</b> {total_display}</p>
<table style="width:100%;border-collapse:collapse;border:1px solid #555;font-size:11px;">
<thead><tr style="background:#2a2a4a;border-bottom:1px solid #555;">
<th style="padding:3px 5px">No</th><th style="padding:3px 5px">품명</th><th style="padding:3px 5px">규격</th>
<th style="padding:3px 5px">수량</th><th style="padding:3px 5px">단위</th>
<th style="padding:3px 5px">운반비</th><th style="padding:3px 5px">처리/제품비</th>
<th style="padding:3px 5px">금액</th><th style="padding:3px 5px">비고</th></tr></thead>
<tbody>{rows_html}</tbody></table>
</div>
""", unsafe_allow_html=True)

            actual_remark = st.session_state.get("remark_input", remark_default)
            # PDF 합계금액: 단위 단가 견적이면 0으로 처리
            pdf_total = 0 if is_unit_quote else total
            pdf_buf = generate_pdf(
                client, project, all_items, actual_remark, valid_date, pdf_total,
                user["name"], author_phone if show_author else "",
                show_author=show_author
            )
            fname = f"견적서_{client}_{datetime.now().strftime('%Y%m%d')}.pdf"
            col_pdf, col_log = st.columns(2)
            with col_pdf:
                st.download_button(
                    label="📄 PDF 다운로드",
                    data=pdf_buf,
                    file_name=fname,
                    mime="application/pdf",
                    use_container_width=True
                )
            with col_log:
                if st.button("📝 견적 저장(로그기록)", use_container_width=True):
                    append_log(user, client, project, valid_date, all_items, total)
                    st.success("견적이 로그에 저장되었습니다!")
        else:
            st.info("항목을 추가하면 견적서 미리보기가 표시됩니다.")

# ─── 메인 진입점 ───
def main():
    init_users_sheet()
    if "user" not in st.session_state:
        show_login_page()
        return
    if st.session_state.get("page") == "admin" and st.session_state["user"]["role"] == "admin":
        show_admin_page()
    else:
        st.session_state["page"] = "main"
        show_main_page()

if __name__ == "__main__":
    main()
