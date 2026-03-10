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
    c.drawCentredString(300, 800, "견 적 서")
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

    tab1, tab2 = st.tabs(["👥 사원 관리", "📋 견적 이력"])

    with tab1:
        st.subheader("사원 목록")
        df = load_users(use_cache=False)
        if df.empty:
            st.info("등록된 사원이 없습니다.")
        else:
            for _, row in df.iterrows():
                role_label = "관리자" if row["role"] == "admin" else "일반"
                col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
                col1.write(f"**{row['name']}** ({row['username']})")
                col2.write(role_label)
                col3.write("활성" if str(row["active"]) == "True" else "비활성")
                if row["username"] != "admin":
                    if col4.button("탈퇴", key=f"del_{row['username']}"):
                        st.session_state[f"confirm_del_{row['username']}"] = True
                    if st.session_state.get(f"confirm_del_{row['username']}"):
                        st.warning(f"정말 **{row['name']} ({row['username']})**을 삭제하시겠습니까?")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ 확인 삭제", key=f"confirm_yes_{row['username']}"):
                            delete_user(row["username"])
                            st.session_state.pop(f"confirm_del_{row['username']}", None)
                            st.success(f"{row['name']} 계정이 삭제되었습니다.")
                            st.rerun()
                        if c2.button("❌ 취소", key=f"confirm_no_{row['username']}"):
                            st.session_state.pop(f"confirm_del_{row['username']}", None)
                            st.rerun()

        st.divider()
        st.subheader("신규 사원 추가")
        with st.form("add_user_form"):
            new_username = st.text_input("아이디")
            new_name = st.text_input("이름")
            new_password = st.text_input("비밀번호", type="password")
            new_role = st.selectbox("권한", ["employee", "admin"], format_func=lambda x: "일반" if x == "employee" else "관리자")
            add_submitted = st.form_submit_button("추가")
            if add_submitted:
                if not new_username or not new_name or not new_password:
                    st.error("모든 항목을 입력하세요.")
                else:
                    existing = load_users(use_cache=False)
                    if not existing.empty and new_username in existing["username"].values:
                        st.error("이미 존재하는 아이디입니다.")
                    else:
                        save_user(new_username, hash_pw(new_password), new_name, new_role)
                        st.success(f"{new_name} ({new_username}) 계정이 추가되었습니다.")
                        st.rerun()

    with tab2:
        st.subheader("견적 이력")
        logs = load_logs()
        if logs.empty:
            st.info("견적 이력이 없습니다.")
        else:
            for _, log in logs.iterrows():
                with st.expander(f"[{log.get('timestamp','')}] {log.get('user_name','')} - {log.get('client','')} / {log.get('project','')} (₩{int(float(log.get('total_amount',0))):,})"):
                    st.write(f"**견적 ID:** {log.get('log_id','')}")
                    st.write(f"**작성자:** {log.get('user_name','')} ({log.get('username','')})")
                    st.write(f"**수신처:** {log.get('client','')}")
                    st.write(f"**공사명:** {log.get('project','')}")
                    st.write(f"**유효기간:** {log.get('valid_date','')}")
                    st.write(f"**합계금액:** ₩{int(float(log.get('total_amount',0))):,}")
                    st.write(f"**계약여부:** {log.get('contract_done','미계약')}")
                    if log.get("contract_amount"):
                        st.write(f"**계약금액:** ₩{int(float(log.get('contract_amount',0))):,}")
                    contract_status = st.selectbox(
                        "계약 상태 업데이트",
                        ["미계약", "계약완료", "무산"],
                        index=["미계약","계약완료","무산"].index(log.get("contract_done","미계약")) if log.get("contract_done","미계약") in ["미계약","계약완료","무산"] else 0,
                        key=f"status_{log.get('log_id','')}"
                    )
                    contract_amount = st.text_input("실계약 금액", value=str(log.get("contract_amount","")), key=f"amount_{log.get('log_id','')}")
                    memo = st.text_input("메모", value=str(log.get("memo","")), key=f"memo_{log.get('log_id','')}")
                    if st.button("저장", key=f"save_{log.get('log_id','')}"):
                        update_log_field(log["log_id"], "contract_done", contract_status)
                        update_log_field(log["log_id"], "contract_amount", contract_amount)
                        update_log_field(log["log_id"], "memo", memo)
                        st.success("저장되었습니다.")
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

        # 기본 정보 - form으로 묶어서 rerun 최소화
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

        # 실제 표시용 값
        client = st.session_state.get("client", "")
        project = st.session_state.get("project", "")
        valid_date = st.session_state.get("valid_date", (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))

        tab_waste, tab_recycled = st.tabs(["♻️ 폐기물 처리", "🪨 순환골재 납품"])

        with tab_waste:
            with st.form("waste_form", clear_on_submit=False):
                waste_type = st.selectbox("폐기물 성상", list(WASTE_DATA.keys()))
                qty = st.number_input("수량(ton)", min_value=0.01, value=1.0, step=0.1, format="%.2f")
                dist_mode = st.selectbox("운반거리", ["30km","35km","40km","50km","60km","60km 초과"])
                extra_dist = st.number_input("실제거리(km, 60km 초과시)", min_value=61, value=70)
                holiday = st.checkbox("휴일/야간 할증(15%)")
                waste_add = st.form_submit_button("➕ 폐기물 항목 추가", use_container_width=True)
                if waste_add:
                    base = WASTE_DATA[waste_type]
                    transport = calculate_transport(dist_mode, extra_dist)
                    unit_price = base + transport
                    if holiday:
                        unit_price = int(unit_price * 1.15)
                    amount = int(unit_price * qty)
                    dist_label = dist_mode if dist_mode != "60km 초과" else f"L={extra_dist}km"
                    st.session_state["waste_items"].append({
                        "품명": waste_type, "규격": dist_label, "수량": qty,
                        "단위": "ton", "단가": unit_price, "금액": amount
                    })
                    st.rerun()

        with tab_recycled:
            with st.form("recycled_form", clear_on_submit=True):
                recycled_name = st.text_input("품명", placeholder="예: 순환골재(40mm이하)")
                recycled_spec = st.text_input("규격", placeholder="예: KS F 2574")
                recycled_qty = st.number_input("수량", min_value=0.01, value=1.0, step=0.1, format="%.2f")
                recycled_unit = st.selectbox("단위", ["ton","m³","㎥","개"])
                recycled_price = st.number_input("단가(원)", min_value=0, value=10000, step=100)
                recycled_add = st.form_submit_button("➕ 순환골재 항목 추가", use_container_width=True)
                if recycled_add:
                    amount = int(recycled_price * recycled_qty)
                    st.session_state["recycled_items"].append({
                        "품명": recycled_name, "규격": recycled_spec, "수량": recycled_qty,
                        "단위": recycled_unit, "단가": recycled_price, "금액": amount
                    })
                    st.rerun()

    with col_right:
        st.subheader("🔍 견적 미리보기")
        all_items = st.session_state["waste_items"] + st.session_state["recycled_items"]

        for idx, item in enumerate(all_items):
            c1, c2 = st.columns([4, 1])
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
        remark = st.text_area("비고", value=st.session_state.get("remark", remark_default), height=80, key="remark_input")
        if remark != st.session_state.get("remark", remark_default):
            st.session_state["remark"] = remark

        st.divider()

        if all_items:
            rows_html = "".join([
                f"<tr><td style='padding:4px 8px'>{i['품명']}</td><td style='padding:4px 8px'>{i['규격']}</td>"
                f"<td style='padding:4px 8px;text-align:right'>{i['수량']:,.2f}</td><td style='padding:4px 8px'>{i['단위']}</td>"
                f"<td style='padding:4px 8px;text-align:right'>{i['단가']:,.0f}</td>"
                f"<td style='padding:4px 8px;text-align:right'>{i['금액']:,.0f}</td></tr>"
                for i in all_items
            ])
            st.markdown(f"""
<div style="border:1px solid #444;padding:16px;border-radius:6px;background:#1a1a2e;font-size:13px;">
<h4 style="text-align:center;margin-top:0">견 적 서</h4>
<p><b>수신:</b> {client if client else "(미입력)"} 귀중 &nbsp;&nbsp; <b>공사명:</b> {project if project else "(미입력)"}</p>
<p><b>합계금액:</b> 일금 {num_to_kor(total)} <span style="color:#aaa">(₩{total:,.0f} / VAT별도)</span></p>
<table style="width:100%;border-collapse:collapse;border:1px solid #555;">
<thead><tr style="background:#2a2a4a;border-bottom:1px solid #555;">
<th style="padding:4px 8px">품명</th><th style="padding:4px 8px">규격</th>
<th style="padding:4px 8px">수량</th><th style="padding:4px 8px">단위</th>
<th style="padding:4px 8px">단가</th><th style="padding:4px 8px">금액</th></tr></thead>
<tbody>{rows_html}</tbody></table>
</div>
""", unsafe_allow_html=True)

            # PDF 미리 생성해서 바로 다운로드 버튼 제공 (클릭 1번으로 바로 저장)
            pdf_buf = generate_pdf(client, project, all_items, remark, valid_date, total, user["name"])
            fname = f"견적서_{client}_{datetime.now().strftime('%Y%m%d')}.pdf"

            if st.download_button(
                label="📄 정식 PDF 다운로드",
                data=pdf_buf,
                file_name=fname,
                mime="application/pdf",
                use_container_width=True
            ):
                append_log(user, client, project, valid_date, all_items, total)

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
