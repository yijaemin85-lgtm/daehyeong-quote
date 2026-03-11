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
        result[k] = int(settings.get(f"waste_{k}", default))
    return result

def get_transport_table():
    settings = load_price_settings()
    result = {}
    for k, default in DEFAULT_TRANSPORT_TABLE.items():
        result[k] = int(settings.get(f"transport_{k}", default))
    return result

def get_recycled_gov_price():
    return int(load_price_settings().get("recycled_gov_price", DEFAULT_RECYCLED_GOV_PRICE))

def get_recycled_private_price():
    return int(load_price_settings().get("recycled_private_price", DEFAULT_RECYCLED_PRIVATE_PRICE))

def get_dump_volume():
    return float(load_price_settings().get("dump_volume", DEFAULT_DUMP_VOLUME))

def get_extra_km_rate():
    return int(load_price_settings().get("extra_km_rate", DEFAULT_EXTRA_KM_RATE))

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
    for i, d in enumerate(reversed(str(n))):
        if d != "0":
            result = nums[int(d)] + units[i] + result
    return result + "원정"


def generate_pdf(client, project, items, remark, valid_date, total_sum,
                 author_name="", author_phone="", show_author=False):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    W, H = A4  # 595.27 x 841.89 pt

    # ── 폰트 등록 ──
    fn_r, fn_b = "Helvetica", "Helvetica-Bold"
    if os.path.exists("NanumSquareR.ttf"):
        pdfmetrics.registerFont(TTFont("NR", "NanumSquareR.ttf"))
        fn_r = "NR"
    if os.path.exists("NanumSquareB.ttf"):
        pdfmetrics.registerFont(TTFont("NB", "NanumSquareB.ttf"))
        fn_b = "NB"
    if os.path.exists("NanumSquareEB.ttf"):
        pdfmetrics.registerFont(TTFont("NEB", "NanumSquareEB.ttf"))
    if os.path.exists("NanumSquareL.ttf"):
        pdfmetrics.registerFont(TTFont("NL", "NanumSquareL.ttf"))

    # ── 여백 ──
    ML = 25 * mm   # left margin  (25mm)
    MR = W - 20 * mm  # right margin (20mm from right edge)
    PW = MR - ML      # usable width ~150mm = 425pt

    # ══════════════════════════════
    # 1. 제목
    # ══════════════════════════════
    c.setFont(fn_b, 20)
    c.drawCentredString(W / 2, H - 20 * mm, "견     적     서")
    c.setLineWidth(1.2)
    c.line(ML, H - 23 * mm, MR, H - 23 * mm)

    # ══════════════════════════════
    # 2. 좌측 정보 / 우측 회사정보 테이블
    # ══════════════════════════════
    LEFT_W = PW * 0.50   # 좌측 너비
    RIGHT_W = PW * 0.48  # 우측 너비
    right_x = ML + LEFT_W + PW * 0.02  # 우측 시작 x

    # ── 우측 회사 정보 테이블 ──
    info_top_y = H - 26 * mm
    row_h = 7.2 * mm
    info_rows = [
        ("등  록  번  호", "308-81-09656"),
        ("상          호", "대  형  환  경  (주)"),
        ("성          명", "이  관  형"),
        ("업          태", None),   # 특별 처리
        ("주          소", "충남 논산시 벌곡면 대둔로 1290-23"),
        ("전          화", "041)732-0620  Fax 732-0622"),
    ]
    n_rows = len(info_rows)
    label_col_w = 26 * mm
    value_col_w = RIGHT_W - label_col_w

    c.setLineWidth(0.7)
    c.rect(right_x, info_top_y - n_rows * row_h, RIGHT_W, n_rows * row_h)
    for i, (label, value) in enumerate(info_rows):
        ry = info_top_y - (i + 1) * row_h
        if i > 0:
            c.setLineWidth(0.4)
            c.line(right_x, ry + row_h, right_x + RIGHT_W, ry + row_h)
        c.setLineWidth(0.4)
        c.line(right_x + label_col_w, ry, right_x + label_col_w, ry + row_h)
        c.setFont(fn_r, 8)
        c.drawString(right_x + 1.5 * mm, ry + 2 * mm, label)
        vx = right_x + label_col_w + 1.5 * mm
        if label == "성          명":
            c.setFont(fn_b, 9)
            c.drawString(vx, ry + 2 * mm, value)
            if os.path.exists("stamp.png"):
                c.drawImage("stamp.png", right_x + RIGHT_W - 14 * mm,
                            ry + 0.5 * mm, width=12 * mm, height=12 * mm, mask="auto")
        elif label == "업          태":
            c.setFont(fn_r, 7.5)
            c.drawString(vx, ry + 4 * mm, "서비스 제조")
            c.setFont(fn_r, 6.5)
            biz_x = vx + 22 * mm
            c.drawString(biz_x, ry + 4.5 * mm, "건설폐기물 수집·운반,")
            c.drawString(biz_x, ry + 1.5 * mm, "중간처리,비계철거,순환골재판매")
            # 종목 라인
            c.setLineWidth(0.3)
            c.line(vx + 20 * mm, ry, vx + 20 * mm, ry + row_h)
            c.setFont(fn_r, 7)
            c.drawString(vx + 20.5 * mm, ry + 2 * mm, "종목")
        elif label == "전          화":
            c.setFont(fn_r, 8)
            c.drawString(vx, ry + 2 * mm, "☎ " + value)
        else:
            c.setFont(fn_r, 8.5)
            c.drawString(vx, ry + 2 * mm, value)

    # ── 좌측: 날짜 / 수신처 / 공사명 ──
    now = datetime.now()
    date_str = f"서기  {now.year} 년  {now.month} 월  {now.day} 일"
    c.setFont(fn_r, 10)
    c.drawString(ML, info_top_y - 5 * mm, date_str)
    dw = c.stringWidth(date_str, fn_r, 10)
    c.setLineWidth(0.5)
    c.line(ML, info_top_y - 6 * mm, ML + dw, info_top_y - 6 * mm)

    # 수신처 박스
    box_y = info_top_y - 15 * mm
    c.setLineWidth(0.8)
    c.rect(ML, box_y, LEFT_W * 0.9, 8 * mm)
    c.setFont(fn_b, 11)
    client_disp = (client if client else "(수신처)") + "  귀중"
    c.drawString(ML + 2 * mm, box_y + 2 * mm, client_disp)

    c.setFont(fn_r, 9.5)
    c.drawString(ML, info_top_y - 27 * mm, "내역을 하기와 같이 제출합니다.")
    c.drawString(ML, info_top_y - 33 * mm, f"유효견적기간   {valid_date}한")

    proj_full = project if project else "(공사명)"
    proj_label = "공사명 :  "
    pw_avail = LEFT_W - c.stringWidth(proj_label, fn_r, 9.5)
    c.drawString(ML, info_top_y - 39 * mm, proj_label + proj_full[:int(pw_avail / 5)])
    if len(proj_full) > int(pw_avail / 5):
        c.drawString(ML + c.stringWidth(proj_label, fn_r, 9.5),
                     info_top_y - 44 * mm, proj_full[int(pw_avail / 5):])

    # ══════════════════════════════
    # 3. 합계금액 행
    # ══════════════════════════════
    sum_bar_top = info_top_y - n_rows * row_h - 3 * mm
    sum_bar_h = 8 * mm
    c.setLineWidth(0.8)
    c.rect(ML, sum_bar_top - sum_bar_h, PW, sum_bar_h)
    c.setFont(fn_b, 10)
    if total_sum and total_sum > 0:
        ts = f"합  계  금  액  :    일금  {num_to_kor(total_sum)}   ( \u20a9  {total_sum:,.0f}  )"
    else:
        ts = "합  계  금  액  :    본 견적은 단위 단가 견적임   ( \u20a9  -  )"
    c.drawString(ML + 3 * mm, sum_bar_top - sum_bar_h + 2.5 * mm, ts)

    # ══════════════════════════════
    # 4. 품목 테이블
    # ══════════════════════════════
    # 컬럼 너비 (mm) : No(8) | 품명(38) | 규격(20) | 수량(12) | 단위(11) | 운반비(20) | 처리/제품비(20) | 금액(21)
    # 비고는 테이블 내 마지막 컬럼 없이 → 금액 다음에 비고 넣기
    # 전체 PW = 150mm 정도
    CN = [8, 38, 20, 12, 11, 20, 20, 21]  # mm단위
    # 비고 추가
    # 전체 합: 8+38+20+12+11+20+20+21 = 150mm
    # 비고는 없이 금액이 마지막. 비고는 테이블 밖에 별도.
    # → 비고를 테이블 안에 포함: 조정
    # No(7) | 품명(35) | 규격(18) | 수량(11) | 단위(10) | 운반비(18) | 처리비(18) | 금액(19) | 비고(14) = 150
    CN = [7, 35, 18, 11, 10, 18, 18, 19, 14]  # 총 150mm
    col_xs = [ML]
    for w in CN[:-1]:
        col_xs.append(col_xs[-1] + w * mm)
    col_xs.append(MR)  # 마지막 끝

    tbl_top = sum_bar_top - sum_bar_h - 1 * mm
    hdr_h = 11 * mm
    row_h_tbl = 6.5 * mm
    max_rows = 15

    # 헤더 외곽
    c.setLineWidth(0.7)
    c.rect(ML, tbl_top - hdr_h, PW, hdr_h)

    # 헤더 세로선
    for cx in col_xs[1:-1]:
        c.setLineWidth(0.3)
        c.line(cx, tbl_top - hdr_h, cx, tbl_top)

    # "단 가" 상단 병합
    danga_x1 = col_xs[5]
    danga_x2 = col_xs[7]
    c.setFont(fn_b, 8.5)
    c.drawCentredString((danga_x1 + danga_x2) / 2, tbl_top - 4.5 * mm, "단   가")
    c.setLineWidth(0.3)
    c.line(danga_x1, tbl_top - hdr_h / 2, danga_x2, tbl_top - hdr_h / 2)

    hdr_labels = ["No", "품     명", "규     격", "수량", "단위", "운반비", "처리비\n/제품비", "금     액", "비고"]
    for i, (x1, x2, lbl) in enumerate(zip(col_xs, col_xs[1:], hdr_labels)):
        mid = (x1 + x2) / 2
        if i in [5, 6]:  # 단가 하위 헤더
            c.setFont(fn_r, 7)
            c.drawCentredString(mid, tbl_top - hdr_h + 2 * mm, lbl.replace("\n", " "))
        elif "\n" in lbl:
            parts = lbl.split("\n")
            c.setFont(fn_b if i not in [3,4] else fn_r, 8)
            c.drawCentredString(mid, tbl_top - 6 * mm, parts[0])
            c.drawCentredString(mid, tbl_top - 9.5 * mm, parts[1])
        elif i in [3, 4]:
            c.setFont(fn_r, 7.5)
            c.drawCentredString(mid, tbl_top - 6.5 * mm, lbl)
        else:
            c.setFont(fn_b, 8.5)
            c.drawCentredString(mid, tbl_top - 7 * mm, lbl)

    # 데이터 행
    data_top = tbl_top - hdr_h
    c.setLineWidth(0.7)
    c.rect(ML, data_top - max_rows * row_h_tbl, PW, max_rows * row_h_tbl)

    used_rows = len(items[:max_rows])
    for ri, item in enumerate(items[:max_rows]):
        ry = data_top - (ri + 1) * row_h_tbl
        c.setLineWidth(0.25)
        c.line(ML, ry + row_h_tbl, MR, ry + row_h_tbl)
        for cx in col_xs[1:-1]:
            c.line(cx, ry, cx, ry + row_h_tbl)

        c.setFont(fn_r, 8.5)
        def mc(x1, x2, txt, bold=False):
            c.setFont(fn_b if bold else fn_r, 8.5)
            c.drawCentredString((x1 + x2) / 2, ry + 1.8 * mm, str(txt))
        def ml(x1, txt):
            c.setFont(fn_r, 8.5)
            c.drawString(x1 + 1 * mm, ry + 1.8 * mm, str(txt))
        def mr2(x2, txt):
            c.setFont(fn_r, 8.5)
            c.drawRightString(x2 - 1 * mm, ry + 1.8 * mm, str(txt))

        mc(col_xs[0], col_xs[1], f"{ri+1}.")
        ml(col_xs[1], str(item.get("품명",""))[:13])
        ml(col_xs[2], str(item.get("규격",""))[:9])
        mc(col_xs[3], col_xs[4], f"{item.get('수량',0):,.2f}")
        mc(col_xs[4], col_xs[5], str(item.get("단위","")))

        tv = int(item.get("운반비", 0))
        pv = int(item.get("제품비", item.get("처리비", item.get("단가", 0))))
        av = int(item.get("금액", 0))
        bv = str(item.get("비고", ""))

        if tv > 0:
            mr2(col_xs[6], f"{tv:,}")
        else:
            mc(col_xs[5], col_xs[6], "-")
        mr2(col_xs[7], f"{pv:,}")
        mr2(col_xs[8], f"{av:,}")
        mc(col_xs[8], col_xs[9], bv)

    # 이하여백
    if used_rows < max_rows:
        blank_ry = data_top - (used_rows + 1) * row_h_tbl
        c.setFont(fn_r, 9)
        c.drawCentredString(W / 2, blank_ry + 1.8 * mm, "—  이  하  여  백  —")
        for extra in range(used_rows + 1, max_rows):
            ery = data_top - (extra + 1) * row_h_tbl
            c.setLineWidth(0.2)
            c.line(ML, ery + row_h_tbl, MR, ery + row_h_tbl)

    # 합계 행
    sum_ry = data_top - max_rows * row_h_tbl
    c.setLineWidth(0.7)
    c.rect(ML, sum_ry - row_h_tbl, PW, row_h_tbl)
    for cx in col_xs[1:-1]:
        c.setLineWidth(0.25)
        c.line(cx, sum_ry - row_h_tbl, cx, sum_ry)
    c.setFont(fn_b, 9)
    c.drawCentredString((col_xs[1] + col_xs[3]) / 2, sum_ry - row_h_tbl + 2 * mm, "[  합      계  ]")
    if total_sum and total_sum > 0:
        c.drawRightString(col_xs[8] - 1 * mm, sum_ry - row_h_tbl + 2 * mm, f"{int(total_sum):,}")

    # ══════════════════════════════
    # 5. 비고 섹션
    # ══════════════════════════════
    remark_y = sum_ry - row_h_tbl - 6 * mm
    c.setFont(fn_b, 9)
    c.drawString(ML, remark_y, "§ 비 고 §")
    c.setFont(fn_r, 9)
    for i, line in enumerate(remark.split("\n")):
        c.drawString(ML, remark_y - (i + 1) * 5 * mm, line)

    # 담당자
    if show_author and author_name:
        contact = f"담당자 : {author_name}"
        if author_phone:
            contact += f"  (Tel : {author_phone})"
        c.setFont(fn_r, 9)
        c.drawRightString(MR, 15 * mm, contact)

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
                phone_str = f" | {row.get('phone','')}" if row.get('phone') else ""
                col1.write(f"**{row['name']}** ({row['username']}){phone_str}")
                col2.write(role_label)
                col3.write("활성" if str(row["active"]) == "True" else "비활성")
                if row["username"] != "admin":
                    uname = str(row["username"])
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
            new_role = st.selectbox("권한", ["employee", "admin"],
                                    format_func=lambda x: "일반" if x == "employee" else "관리자")
            if st.form_submit_button("추가"):
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
                amt = int(float(log.get("total_amount", 0) or 0))
                with st.expander(f"[{log.get('timestamp','')}] {log.get('user_name','')} - {log.get('client','')} / {log.get('project','')} (₩{amt:,})"):
                    st.write(f"**견적 ID:** {lid}")
                    st.write(f"**작성자:** {log.get('user_name','')} ({log.get('username','')})")
                    st.write(f"**수신처:** {log.get('client','')}")
                    st.write(f"**공사명:** {log.get('project','')}")
                    st.write(f"**유효기간:** {log.get('valid_date','')}")
                    st.write(f"**합계금액:** ₩{amt:,}")
                    options = ["미계약","계약완료","무산"]
                    cur = log.get("contract_done","미계약")
                    if cur not in options:
                        cur = "미계약"
                    sel = st.selectbox("계약 상태", options, index=options.index(cur),
                                       key=f"status_{lid}_{log_i}")
                    ca = st.text_input("실계약 금액", value=str(log.get("contract_amount","")),
                                       key=f"amount_{lid}_{log_i}")
                    memo = st.text_input("메모", value=str(log.get("memo","")),
                                         key=f"memo_{lid}_{log_i}")
                    if st.button("저장", key=f"save_{lid}_{log_i}"):
                        update_log_field(lid, "contract_done", sel)
                        update_log_field(lid, "contract_amount", ca)
                        update_log_field(lid, "memo", memo)
                        st.success("저장되었습니다.")

    with tab3:
        st.subheader("💰 단가 관리")
        st.markdown("#### 건설폐기물 처리비 단가 (원/ton)")
        wd = get_waste_data()
        with st.form("waste_price_form"):
            nw = {}
            cols = st.columns(2)
            for i, (k, v) in enumerate(wd.items()):
                nw[k] = cols[i % 2].number_input(k, min_value=0, value=v, step=100, key=f"wp_{k}")
            if st.form_submit_button("폐기물 단가 저장"):
                for k, v in nw.items():
                    save_price_setting(f"waste_{k}", v)
                st.success("저장되었습니다.")
                st.rerun()

        st.markdown("#### 운반비 단가표 (원/ton)")
        tt = get_transport_table()
        with st.form("transport_price_form"):
            nt = {}
            cols2 = st.columns(3)
            for i, (k, v) in enumerate(tt.items()):
                nt[k] = cols2[i % 3].number_input(k, min_value=0, value=v, step=100, key=f"tp_{k}")
            er = get_extra_km_rate()
            ner = st.number_input("60km 초과 km당 추가 단가(원/km)", min_value=0, value=er, step=10)
            if st.form_submit_button("운반비 단가 저장"):
                for k, v in nt.items():
                    save_price_setting(f"transport_{k}", v)
                save_price_setting("extra_km_rate", ner)
                st.success("저장되었습니다.")
                st.rerun()

        st.markdown("#### 순환골재 제품비 단가")
        with st.form("recycled_price_form"):
            gp = get_recycled_gov_price()
            pp = get_recycled_private_price()
            dv = get_dump_volume()
            ng = st.number_input("관급/설계 단가 (원/m³)", min_value=0, value=gp, step=100)
            np2 = st.number_input("사급 단가 (원/m³)", min_value=0, value=pp, step=100)
            ndv = st.number_input("덤프트럭 적재용적 (m³/대)", min_value=1.0, value=dv, step=0.5, format="%.1f")
            st.info(f"대당 관급: {int(ng*ndv):,}원  |  대당 사급: {int(np2*ndv):,}원")
            if st.form_submit_button("순환골재 단가 저장"):
                save_price_setting("recycled_gov_price", ng)
                save_price_setting("recycled_private_price", np2)
                save_price_setting("dump_volume", ndv)
                st.success("저장되었습니다.")
                st.rerun()


# ─── 메인 앱 페이지 ───
def show_main_page():
    user = st.session_state["user"]
    with st.sidebar:
        role_label = "관리자" if user["role"] == "admin" else "일반"
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
            client = st.text_input("수신처", value=st.session_state.get("client",""),
                                   placeholder="입력하세요 (예: OO설계사무소)")
            project = st.text_input("공사명", value=st.session_state.get("project",""),
                                    placeholder="입력하세요 (예: 세종시 OO공사)")
            default_valid = st.session_state.get("valid_date",
                (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))
            valid_date = st.text_input("유효기간", value=default_valid)
            if st.form_submit_button("✔ 기본정보 저장", use_container_width=True):
                st.session_state["client"] = client
                st.session_state["project"] = project
                st.session_state["valid_date"] = valid_date

        client = st.session_state.get("client", "")
        project = st.session_state.get("project", "")
        valid_date = st.session_state.get("valid_date",
            (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))

        tab_waste, tab_recycled = st.tabs(["♻️ 폐기물 처리", "🪨 순환골재 납품"])

        # ── 폐기물 처리 탭 ──
        with tab_waste:
            waste_data = get_waste_data()
            with st.form("waste_form", clear_on_submit=False):
                waste_type = st.selectbox("폐기물 성상", list(waste_data.keys()))
                qty = st.number_input("수량(ton)", min_value=0.01, value=1.0, step=0.1, format="%.2f")
                dist_mode = st.selectbox("운반거리", ["30km","35km","40km","50km","60km","60km 초과"])
                extra_dist = 0
                if dist_mode == "60km 초과":
                    extra_dist = st.number_input("실제거리(km)", min_value=61, value=70)
                holiday = st.checkbox("휴일/야간 할증(15%)")
                if st.form_submit_button("➕ 폐기물 항목 추가", use_container_width=True):
                    base = waste_data[waste_type]
                    transport = calculate_transport(dist_mode, extra_dist)
                    unit_price = base + transport
                    if holiday:
                        unit_price = int(unit_price * 1.15)
                    dist_label = dist_mode if dist_mode != "60km 초과" else f"L={extra_dist}km"
                    st.session_state["waste_items"].append({
                        "품명": waste_type, "규격": dist_label,
                        "수량": qty, "단위": "ton",
                        "운반비": transport, "처리비": base,
                        "제품비": 0, "단가": unit_price,
                        "금액": int(unit_price * qty), "비고": ""
                    })
                    st.rerun()

        # ── 순환골재 납품 탭 ──
        with tab_recycled:
            quote_mode = st.radio("견적 모드", ["설계견적","관급견적","사급견적"],
                                  horizontal=True, key="rc_qmode")
            delivery_mode = st.radio("납품 조건", ["상차도","도착도"],
                                     horizontal=True, key="rc_dmode")
            is_gov = quote_mode in ["설계견적","관급견적"]
            gov_price = get_recycled_gov_price()
            priv_price = get_recycled_private_price()
            dump_vol = get_dump_volume()

            with st.form("recycled_form", clear_on_submit=False):
                r_name = st.text_input("품명", placeholder="예: 순환골재(도로기층용)")
                r_spec = st.text_input("규격", placeholder="예: 40mm")
                unit_sel = st.radio("수량 단위", ["m³","대 (25톤 덤프 기준)"],
                                    horizontal=True, key="rc_unit")
                r_qty = st.number_input("수량", min_value=0.01, value=1.0, step=0.1, format="%.2f")

                disp_unit = "m³" if unit_sel == "m³" else "대"
                if unit_sel == "m³":
                    base_p = gov_price if is_gov else priv_price
                    hint = f"관급 기준: {gov_price:,}원/m³" if is_gov else f"사급: {priv_price:,}원/m³"
                    prod_p = st.number_input(f"제품비 단가 (원/m³) [{hint}]",
                                             min_value=0, value=base_p, step=100)
                else:
                    base_p = int((gov_price if is_gov else priv_price) * dump_vol)
                    hint = f"관급: {int(gov_price*dump_vol):,}원/대" if is_gov else f"사급: {int(priv_price*dump_vol):,}원/대"
                    prod_p = st.number_input(f"제품비 단가 (원/대) [{hint}]",
                                             min_value=0, value=base_p, step=1000)

                trans_p = 0
                if delivery_mode == "도착도":
                    tt = get_transport_table()
                    if is_gov:
                        t_opts = list(tt.keys()) + ["60km 초과","직접입력"]
                        t_sel = st.selectbox("운반비 선택", t_opts)
                        if t_sel == "직접입력":
                            trans_p = st.number_input("운반비 직접입력(원)", min_value=0, value=0, step=100)
                        elif t_sel == "60km 초과":
                            ex_km = st.number_input("실제거리(km)", min_value=61, value=70)
                            trans_p = calculate_transport("60km 초과", ex_km)
                            st.info(f"운반비: {trans_p:,}원")
                        else:
                            trans_p = tt.get(t_sel, 0)
                            st.info(f"운반비: {trans_p:,}원")
                    else:
                        trans_p = st.number_input("운반비 직접입력(원)", min_value=0, value=0, step=100)

                if st.form_submit_button("➕ 순환골재 항목 추가", use_container_width=True):
                    amt = int((prod_p + trans_p) * r_qty)
                    st.session_state["recycled_items"].append({
                        "품명": r_name if r_name else "순환골재",
                        "규격": r_spec, "수량": r_qty, "단위": disp_unit,
                        "운반비": trans_p, "처리비": 0, "제품비": prod_p,
                        "단가": prod_p + trans_p, "금액": amt,
                        "비고": delivery_mode
                    })
                    st.rerun()

    # ── 우측: 미리보기 및 출력 ──
    with col_right:
        st.subheader("🔍 견적 미리보기")
        all_items = st.session_state["waste_items"] + st.session_state["recycled_items"]

        for idx, item in enumerate(all_items):
            c1, c2 = st.columns([4, 1])
            c1.write(f"{idx+1}. **{item['품명']}** ({item['규격']}) : "
                     f"{item['수량']:.2f} {item['단위']} × {item['단가']:,.0f}원 = **{item['금액']:,.0f}원**")
            if c2.button("삭제", key=f"del_item_{idx}"):
                wi = len(st.session_state["waste_items"])
                if idx < wi:
                    st.session_state["waste_items"].pop(idx)
                else:
                    st.session_state["recycled_items"].pop(idx - wi)
                st.rerun()

        total = sum(i["금액"] for i in all_items)
        remark_default = "1. 부가세 별도.\n2. 상차비 별도.\n3. 25.5톤 덤프 용적 17㎥ 적용."
        remark = st.text_area("비고", value=st.session_state.get("remark_input", remark_default),
                              height=80, key="remark_input")

        show_author = st.checkbox("담당자 정보 견적서에 포함", value=False, key="show_author_check")
        a_name = user.get("name", "")
        a_phone = user.get("phone", "")
        if show_author:
            ca1, ca2 = st.columns(2)
            a_name = ca1.text_input("담당자 이름", value=a_name, key="author_name_input")
            a_phone = ca2.text_input("담당자 연락처", value=a_phone, key="author_phone_input")

        st.divider()
        if all_items:
            is_unit = any(it.get("비고","") in ["상차도","도착도"] for it in all_items)
            rows_html = "".join([
                f"<tr><td style='padding:2px 4px;text-align:center'>{i+1}</td>"
                f"<td style='padding:2px 4px'>{it['품명']}</td>"
                f"<td style='padding:2px 4px'>{it['규격']}</td>"
                f"<td style='padding:2px 4px;text-align:right'>{it['수량']:,.2f}</td>"
                f"<td style='padding:2px 4px'>{it['단위']}</td>"
                f"<td style='padding:2px 4px;text-align:right'>{int(it.get('운반비',0)):,}</td>"
                f"<td style='padding:2px 4px;text-align:right'>{int(it.get('제품비',it.get('처리비',it.get('단가',0)))):,}</td>"
                f"<td style='padding:2px 4px;text-align:right'>{it['금액']:,.0f}</td>"
                f"<td style='padding:2px 4px;text-align:center'>{it.get('비고','')}</td></tr>"
                for i, it in enumerate(all_items)
            ])
            total_disp = ("본 견적은 단위 단가 견적임  ( ₩ - )"
                          if is_unit else f"일금 {num_to_kor(total)}  ( ₩ {total:,.0f} )")
            st.markdown(f"""
<div style="border:1px solid #444;padding:10px;border-radius:6px;background:#1a1a2e;font-size:11px;">
<h4 style="text-align:center;letter-spacing:8px;margin:0 0 8px">견  적  서</h4>
<p style="margin:2px"><b>수신:</b> {client if client else "(미입력)"} 귀중 &nbsp; <b>공사명:</b> {project if project else "(미입력)"}</p>
<p style="margin:2px"><b>합계금액:</b> {total_disp}</p>
<table style="width:100%;border-collapse:collapse;border:1px solid #555;margin-top:6px">
<thead><tr style="background:#2a2a4a">
<th style="padding:2px 4px;font-size:10px">No</th><th style="padding:2px 4px;font-size:10px">품명</th>
<th style="padding:2px 4px;font-size:10px">규격</th><th style="padding:2px 4px;font-size:10px">수량</th>
<th style="padding:2px 4px;font-size:10px">단위</th><th style="padding:2px 4px;font-size:10px">운반비</th>
<th style="padding:2px 4px;font-size:10px">처리/제품비</th><th style="padding:2px 4px;font-size:10px">금액</th>
<th style="padding:2px 4px;font-size:10px">비고</th></tr></thead>
<tbody>{rows_html}</tbody></table></div>
""", unsafe_allow_html=True)

            pdf_total = 0 if is_unit else total
            actual_remark = st.session_state.get("remark_input", remark_default)
            pdf_buf = generate_pdf(
                client, project, all_items, actual_remark, valid_date,
                pdf_total, a_name, a_phone, show_author
            )
            fname = f"견적서_{client}_{datetime.now().strftime('%Y%m%d')}.pdf"

            # PDF 다운로드 + 자동 저장
            if st.download_button(
                label="📄 PDF 다운로드 (자동저장)",
                data=pdf_buf,
                file_name=fname,
                mime="application/pdf",
                use_container_width=True
            ):
                append_log(user, client, project, valid_date, all_items, total)
                st.success("견적이 로그에 자동 저장되었습니다!")
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
