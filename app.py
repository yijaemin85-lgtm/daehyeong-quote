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

# ─────────────────────────────────────────
# [Apps Script 연동 헬퍼]
# ─────────────────────────────────────────
def gas_post(payload: dict) -> dict:
    try:
        GAS_URL = st.secrets["apps_script_url"]
        resp = requests.post(GAS_URL, json=payload, timeout=30)
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_sheet_data(sheet_name: str) -> list:
    res = gas_post({"action": "get_sheet", "sheet_name": sheet_name})
    if res.get("status") == "ok":
        return res.get("data", [])
    return []

def append_row(sheet_name: str, row: list):
    gas_post({"action": "append_row", "sheet_name": sheet_name, "row": row})

def update_cell(sheet_name: str, row_index: int, col_index: int, value):
    gas_post({
        "action": "update_cell",
        "sheet_name": sheet_name,
        "row_index": row_index,
        "col_index": col_index,
        "value": str(value)
    })

# ─────────────────────────────────────────
# [유저 관련]
# ─────────────────────────────────────────
USER_SHEET = "users"
USER_HEADER = ["username", "password_hash", "name", "role", "active"]

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def load_users() -> pd.DataFrame:
    data = get_sheet_data(USER_SHEET)
    if len(data) < 2:
        return pd.DataFrame(columns=USER_HEADER)
    headers = data[0]
    rows = data[1:]
    return pd.DataFrame(rows, columns=headers)

def init_users_sheet():
    data = get_sheet_data(USER_SHEET)
    if not data:
        append_row(USER_SHEET, USER_HEADER)
        admin_pw = st.secrets.get("admin_init_password", "admin1234")
        append_row(USER_SHEET, ["admin", hash_pw(admin_pw), "관리자", "admin", "True"])

def save_user(username, password_hash, name, role="employee", active=True):
    data = get_sheet_data(USER_SHEET)
    if not data:
        append_row(USER_SHEET, USER_HEADER)
    append_row(USER_SHEET, [username, password_hash, name, role, str(active)])

def update_user_field(username: str, field: str, value):
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

def authenticate(username, password):
    df = load_users()
    if df.empty:
        return None
    row = df[(df["username"] == username) & (df["active"].astype(str) == "True")]
    if row.empty:
        return None
    user = row.iloc[0]
    if user["password_hash"] == hash_pw(password):
        return user.to_dict()
    return None

# ─────────────────────────────────────────
# [견적 이력 로그]
# ─────────────────────────────────────────
LOG_SHEET = "quote_logs"
LOG_HEADER = [
    "log_id", "timestamp", "username", "user_name",
    "client", "project", "valid_date",
    "items_json", "total_amount",
    "contract_done", "contract_amount", "contract_date", "memo"
]

def load_logs() -> pd.DataFrame:
    data = get_sheet_data(LOG_SHEET)
    if len(data) < 2:
        return pd.DataFrame(columns=LOG_HEADER)
    headers = data[0]
    rows = data[1:]
    return pd.DataFrame(rows, columns=headers)

def append_log(user: dict, client: str, project: str, valid_date: str,
               items: list, total: float):
    data = get_sheet_data(LOG_SHEET)
    if not data:
        append_row(LOG_SHEET, LOG_HEADER)
    log_id = str(uuid.uuid4())[:8]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items_json = json.dumps(items, ensure_ascii=False)
    append_row(LOG_SHEET, [
        log_id, ts,
        user["username"], user["name"],
        client, project, valid_date,
        items_json, total,
        "미계약", "", "", ""
    ])

def update_log_field(log_id: str, field: str, value):
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

# ─────────────────────────────────────────
# [단가 데이터]
# ─────────────────────────────────────────
WASTE_DATA = {
    "폐콘크리트": 31142,
    "폐아스팔트콘크리트": 32166,
    "건설폐재류": 49571,
    "건설오니": 60891,
    "혼합건설폐기물(5%이하)": 72721,
    "불연성+가연성(5%이하)": 188715,
    "기타+가연성(5%이하)": 192887,
}
TRANSPORT_TABLE = {
    "30km": 20340, "35km": 22270,
    "40km": 24130, "50km": 27940, "60km": 31690
}

def calculate_transport(mode, m_dist=0):
    if mode == "60km 초과":
        return 31690 + (375 * max(0, m_dist - 60))
    return TRANSPORT_TABLE.get(mode, 20340)

def num_to_kor(num):
    units = ["", "십", "백", "천", "만", "십", "백", "천", "억"]
    nums  = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
    result = ""
    for i, n in enumerate(str(int(num))[::-1]):
        if n != "0":
            result = nums[int(n)] + units[i] + result
    return result + "원정"

# ─────────────────────────────────────────
# [PDF 생성]
# ─────────────────────────────────────────
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
    c.drawString(50, 650, f"합계금액: 일금 {num_to_kor(total_sum)} (\u20a9 {total_sum:,.0f} / VAT별도)")
    c.setFont(font, 10)
    c.rect(50, 280, 500, 350)
    c.line(50, 610, 550, 610)
    x = [60, 180, 280, 330, 380, 470]
    for h, xp in zip(["품명", "규격", "수량", "단위", "단가", "금액"], x):
        c.drawString(xp, 615, h)
    y = 590
    for it in items:
        c.drawString(60,  y, str(it["품명"]))
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

# ─────────────────────────────────────────
# [로그인 화면]
# ─────────────────────────────────────────
def show_login():
    st.title("🔐 대형환경(주) 견적 시스템")
    st.markdown("---")
    with st.form("login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True)
    if submitted:
        with st.spinner("인증 중..."):
            init_users_sheet()
            user = authenticate(username, password)
        if user:
            st.session_state["user"] = user
            st.session_state["q_items"] = []
            st.session_state["page"] = "main"
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

# ─────────────────────────────────────────
# [관리자 페이지]
# ─────────────────────────────────────────
def show_admin():
    user = st.session_state["user"]
    st.sidebar.success(f"👤 {user['name']} (관리자)")
    if st.sidebar.button("📄 견적 작성"):
        st.session_state["page"] = "main"
        st.rerun()
    if st.sidebar.button("🚪 로그아웃"):
        st.session_state.clear()
        st.rerun()

    st.title("⚙️ 관리자 대시보드")
    tab_users, tab_logs, tab_stats = st.tabs(["👥 사원 관리", "📋 견적 이력", "📊 통계 분석"])

    # ── 사원 관리 ──
    with tab_users:
        st.subheader("👥 사원 계정 관리")
        df_users = load_users()

        with st.expander("➕ 신규 사원 추가", expanded=False):
            with st.form("add_user_form"):
                c1, c2 = st.columns(2)
                new_uid  = c1.text_input("아이디 (영문/숫자)")
                new_name = c2.text_input("이름")
                new_pw   = st.text_input("초기 비밀번호", type="password")
                new_role = st.selectbox("권한", ["employee", "admin"])
                if st.form_submit_button("추가"):
                    if new_uid and new_name and new_pw:
                        if new_uid in df_users["username"].values:
                            st.error("이미 존재하는 아이디입니다.")
                        else:
                            save_user(new_uid, hash_pw(new_pw), new_name, new_role)
                            st.success(f"사원 '{new_name}' 추가 완료!")
                            st.rerun()
                    else:
                        st.warning("모든 항목을 입력해주세요.")

        st.markdown("#### 전체 사원 목록")
        if df_users.empty:
            st.info("등록된 사원이 없습니다.")
        else:
            if "reset_target" in st.session_state:
                target = st.session_state["reset_target"]
                with st.form("reset_pw_form"):
                    st.write(f"**{target}** 비밀번호 초기화")
                    new_pw2 = st.text_input("새 비밀번호", type="password")
                    col_ok, col_cancel = st.columns(2)
                    if col_ok.form_submit_button("변경"):
                        update_user_field(target, "password_hash", hash_pw(new_pw2))
                        del st.session_state["reset_target"]
                        st.success("비밀번호가 변경되었습니다.")
                        st.rerun()
                    if col_cancel.form_submit_button("취소"):
                        del st.session_state["reset_target"]
                        st.rerun()

            for _, row in df_users.iterrows():
                active = str(row["active"]) == "True"
                badge = "🟢" if active else "🔴"
                with st.container(border=True):
                    cc1, cc2, cc3, cc4 = st.columns([2, 2, 1, 1])
                    cc1.write(f"{badge} **{row['name']}**  `{row['username']}`")
                    cc2.write(f"권한: {'관리자' if row['role'] == 'admin' else '일반사원'}")
                    if cc3.button("비번초기화", key=f"pw_{row['username']}"):
                        st.session_state["reset_target"] = row["username"]
                        st.rerun()
                    if row["username"] != "admin":
                        label = "비활성화" if active else "활성화"
                        if cc4.button(label, key=f"toggle_{row['username']}"):
                            update_user_field(row["username"], "active", str(not active))
                            st.rerun()

    # ── 견적 이력 ──
    with tab_logs:
        st.subheader("📋 전체 견적 이력")
        df_logs = load_logs()
        if df_logs.empty:
            st.info("견적 이력이 없습니다.")
        else:
            fc1, fc2 = st.columns(2)
            users_list = ["전체"] + sorted(df_logs["user_name"].unique().tolist())
            sel_user = fc1.selectbox("사원 필터", users_list)
            sel_contract = fc2.selectbox("계약 여부", ["전체", "미계약", "계약완료"])
            filtered = df_logs.copy()
            if sel_user != "전체":
                filtered = filtered[filtered["user_name"] == sel_user]
            if sel_contract != "전체":
                filtered = filtered[filtered["contract_done"] == sel_contract]

            for _, row in filtered.sort_values("timestamp", ascending=False).iterrows():
                with st.container(border=True):
                    h1, h2 = st.columns([4, 1])
                    try:
                        amt_str = f"{float(row['total_amount']):,.0f}원"
                    except Exception:
                        amt_str = str(row["total_amount"])
                    h1.markdown(
                        f"**{row['timestamp']}** | 👤 {row['user_name']}  \n"
                        f"📍 수신처: {row['client']} | 🏗️ 공사명: {row['project']}  \n"
                        f"💰 견적금액: **{amt_str}**"
                    )
                    status = row["contract_done"]
                    h2.markdown(f"{'🟢' if status == '계약완료' else '🔴'} **{status}**")

                    if status == "미계약":
                        with st.expander("✅ 계약 완료 처리"):
                            with st.form(f"contract_{row['log_id']}"):
                                ca = st.number_input("실계약금액 (원)", min_value=0, step=1000, key=f"ca_{row['log_id']}")
                                cd = st.text_input("계약일자 (예: 2026-04-01)", key=f"cd_{row['log_id']}")
                                cm = st.text_input("메모", key=f"cm_{row['log_id']}")
                                if st.form_submit_button("저장"):
                                    update_log_field(row["log_id"], "contract_done", "계약완료")
                                    update_log_field(row["log_id"], "contract_amount", ca)
                                    update_log_field(row["log_id"], "contract_date", cd)
                                    update_log_field(row["log_id"], "memo", cm)
                                    st.success("계약 정보가 저장되었습니다.")
                                    st.rerun()
                    elif status == "계약완료":
                        try:
                            ca = float(row["contract_amount"]) if row["contract_amount"] else 0
                            ta = float(row["total_amount"])
                            diff = ca - ta
                            diff_pct = (diff / ta * 100) if ta else 0
                            st.info(f"✅ 계약일: {row['contract_date']} | 실계약금액: {ca:,.0f}원 | 견적 대비 차이: {diff:+,.0f}원 ({diff_pct:+.1f}%)")
                        except Exception:
                            st.info("계약 정보를 불러오는 중 오류가 발생했습니다.")

    # ── 통계 ──
    with tab_stats:
        st.subheader("📊 통계 분석")
        df_logs = load_logs()
        if df_logs.empty:
            st.info("데이터가 없습니다.")
        else:
            df_logs["total_amount"] = pd.to_numeric(df_logs["total_amount"], errors="coerce")
            df_logs["contract_amount"] = pd.to_numeric(df_logs["contract_amount"], errors="coerce")
            df_logs["timestamp"] = pd.to_datetime(df_logs["timestamp"], errors="coerce")

            col1, col2, col3 = st.columns(3)
            col1.metric("총 견적 건수", f"{len(df_logs)}건")
            contract_df = df_logs[df_logs["contract_done"] == "계약완료"]
            col2.metric("계약 완료", f"{len(contract_df)}건")
            rate = len(contract_df) / len(df_logs) * 100 if len(df_logs) else 0
            col3.metric("계약 성공률", f"{rate:.1f}%")

            st.markdown("---")
            st.markdown("#### 월별 견적 건수 추이")
            df_logs["month"] = df_logs["timestamp"].dt.to_period("M").astype(str)
            monthly = df_logs.groupby("month").size().reset_index(name="건수")
            st.bar_chart(monthly.set_index("month"))

            st.markdown("#### 사원별 견적 건수")
            by_user = df_logs.groupby("user_name").size().reset_index(name="건수")
            st.bar_chart(by_user.set_index("user_name"))

            if not contract_df.empty:
                st.markdown("#### 견적 vs 실계약 금액 비교")
                cmp_df = contract_df[["timestamp", "client", "total_amount", "contract_amount"]].copy()
                cmp_df["차이"] = cmp_df["contract_amount"] - cmp_df["total_amount"]
                cmp_df["차이율(%)"] = (cmp_df["차이"] / cmp_df["total_amount"] * 100).round(1)
                st.dataframe(cmp_df[["timestamp", "client", "total_amount", "contract_amount", "차이", "차이율(%)"]], use_container_width=True)

# ─────────────────────────────────────────
# [일반 사원 페이지]
# ─────────────────────────────────────────
def show_main():
    user = st.session_state["user"]
    st.sidebar.success(f"👤 {user['name']} 님")
    if user["role"] == "admin":
        if st.sidebar.button("⚙️ 관리자 페이지"):
            st.session_state["page"] = "admin"
            st.rerun()
    if st.sidebar.button("🚪 로그아웃"):
        st.session_state.clear()
        st.rerun()

    if "q_items" not in st.session_state:
        st.session_state["q_items"] = []

    st.title("📄 대형환경(주) 통합 견적 시스템")
    col_l, col_r = st.columns([1, 1.2])

    with col_l:
        st.subheader("🛠️ 견적 데이터 입력")
        client     = st.text_input("수신처", placeholder="입력하세요 (예: OO설계사무소)")
        project    = st.text_input("공사명", placeholder="입력하세요 (예: 세종시 OO공사)")
        valid_date = st.text_input("유효기간",
            (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))

        t_w, t_a = st.tabs(["♻️ 폐기물 처리", "🪨 순환골재 납품"])
        with t_w:
            w_type    = st.selectbox("폐기물 성상", list(WASTE_DATA.keys()))
            w_qty     = st.number_input("수량(ton)", min_value=0.0, value=1.00, step=0.01, format="%.2f", key="wq_input")
            dist_mode = st.selectbox("운반거리", ["30km", "35km", "40km", "50km", "60km", "60km 초과"], key="dist_input")
            m_dist    = st.number_input("실제거리(km)", min_value=61, value=70) if dist_mode == "60km 초과" else 0
            holiday   = st.checkbox("휴일/야간 할증(15%)")
            if st.button("➕ 폐기물 항목 추가"):
                unit = (WASTE_DATA[w_type] * (1.15 if holiday else 1.0)) + calculate_transport(dist_mode, m_dist)
                st.session_state["q_items"].append({
                    "품명": w_type,
                    "규격": f"L={m_dist if dist_mode == '60km 초과' else dist_mode}",
                    "수량": w_qty, "단위": "ton",
                    "단가": unit, "금액": unit * w_qty,
                })

        with t_a:
            a_spec  = st.text_input("골재 규격", value="40mm (도로기층용)")
            a_qty   = st.number_input("수량(m³)", min_value=0.0, value=1.00, step=0.01, format="%.2f")
            a_price = st.number_input("단가(제품+운반)", min_value=0, value=20000)
            if st.button("➕ 골재 항목 추가"):
                st.session_state["q_items"].append({
                    "품명": "순환골재", "규격": a_spec,
                    "수량": a_qty, "단위": "m³",
                    "단가": a_price, "금액": a_qty * a_price,
                })

        rem_txt = st.text_area("비고 내용", "1. 부가세 별도.\n2. 상차비 별도.\n3. 25.5톤 덤프 용적 17㎡ 적용.")
        if st.button("🗑️ 전체 내역 삭제"):
            st.session_state["q_items"] = []
            st.rerun()

    with col_r:
        st.subheader("🔍 견적 미리보기")
        if st.session_state["q_items"]:
            df = pd.DataFrame(st.session_state["q_items"])
            for i, row in df.iterrows():
                c1, c2 = st.columns([5, 1])
                c1.write(f"**{i+1}. {row['품명']}** ({row['규격']}) : {row['수량']:,.2f} {row['단위']} × {row['단가']:,.0f}원 = **{row['금액']:,.0f}원**")
                if c2.button("삭제", key=f"del_{i}"):
                    st.session_state["q_items"].pop(i)
                    st.rerun()

            total = sum(item["금액"] for item in st.session_state["q_items"])
            with st.container(border=True):
                st.markdown("<h2 style='text-align:center;'>견 적 서</h2>", unsafe_allow_html=True)
                st.write(f"**수신:** {client if client else '(미입력)'} 귀중")
                st.write(f"**합계금액:** 일금 {num_to_kor(total)}")
                st.table(pd.DataFrame(st.session_state["q_items"]).style.format({"수량": "{:,.2f}", "단가": "{:,.0f}", "금액": "{:,.0f}"}))
                st.info(rem_txt)

            pdf = generate_pdf(client, project, st.session_state["q_items"], rem_txt, valid_date, total, user["name"])
            if st.download_button("📥 정식 PDF 다운로드", pdf, f"견적서_{client}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"):
                append_log(user, client, project, valid_date, st.session_state["q_items"], total)
                st.success("✅ 견적 이력이 기록되었습니다.")
        else:
            st.info("왼쪽에서 항목을 작성하신 후 **[추가]** 버튼을 눌러주세요.")

# ─────────────────────────────────────────
# [메인 라우터]
# ─────────────────────────────────────────
if "user" not in st.session_state:
    show_login()
elif st.session_state.get("page") == "admin":
    show_admin()
else:
    show_main()

