import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
import io
import os

# [데이터] 2026년 기준 성상별 처리단가
WASTE_DATA = {
    "폐콘크리트": 31142,
    "폐아스팔트콘크리트": 32166,
    "건설폐재류": 49571,
    "건설오니": 60891,
    "혼합건설폐기물(5%이하)": 72721,
    "불연성+가연성(5%이하)": 188715,
    "기타+가연성(5%이하)": 192887
}

# [데이터] 2026년 수집운반비 (24톤 덤프 기준)
TRANSPORT_TABLE = {"30km": 20340, "35km": 22270, "40km": 24130, "50km": 27940, "60km": 31690}

def calculate_transport(mode, m_dist=0):
    if mode == "60km 초과":
        extra = max(0, m_dist - 60)
        return 31690 + (375 * extra) 
    return TRANSPORT_TABLE.get(mode, 20340)

def num_to_kor(num):
    units = ["", "십", "백", "천", "만", "십", "백", "천", "억"]
    nums = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
    result = ""
    for i, n in enumerate(str(int(num))[::-1]):
        if n != '0': result = nums[int(n)] + units[i] + result
    return result + "원정"

def generate_pdf(client, project, items, remark, valid_date, total_sum):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    font = 'Helvetica'
    p = "C:/Windows/Fonts/malgun.ttf"
    if os.path.exists(p):
        pdfmetrics.registerFont(TTFont('Malgun', p))
        font = 'Malgun'
    
    c.setFont(font, 25); c.drawCentredString(300, 800, "견    적    서")
    c.setFont(font, 10)
    c.drawString(50, 750, f"일자: {datetime.now().strftime('%Y-%m-%d')}")
    c.drawString(50, 735, f"유효기간: {valid_date}까지")
    c.drawString(50, 715, f"{client if client else '입력하세요'} 귀중")
    c.drawString(50, 695, f"공사명: {project if project else '입력하세요'}")
    
    c.rect(340, 680, 210, 100)
    c.drawString(345, 765, "등록번호: 308-81-09656")
    c.drawString(345, 745, "상  호 : 대형환경(주)")
    c.drawString(345, 725, "대  표 : 이 관 형 (인)")
    if os.path.exists("stamp.png"): c.drawImage("stamp.png", 440, 715, width=35, height=35, mask='auto')
    c.drawString(345, 705, "주  소 : 충남 논산시 벌곡면 대둔로 1290-23")
    
    c.setFont(font, 12); c.drawString(50, 650, f"합계금액: 일금 {num_to_kor(total_sum)} (W {total_sum:,.0f} / VAT별도)")
    c.setFont(font, 10); c.rect(50, 280, 500, 350); c.line(50, 610, 550, 610)
    x = [60, 180, 280, 330, 380, 470]
    for h, xp in zip(["품명", "규격", "수량", "단위", "단가", "금액"], x): c.drawString(xp, 615, h)
    
    y = 590
    for it in items:
        c.drawString(60, y, str(it['품명'])); c.drawString(180, y, str(it['규격']))
        c.drawString(280, y, f"{it['수량']:,.2f}"); c.drawString(330, y, str(it['단위']))
        c.drawString(380, y, f"{it['단가']:,.0f}"); c.drawString(470, y, f"{it['금액']:,.0f}")
        y -= 25
    if remark:
        c.drawString(50, 260, "[備考]")
        for i, line in enumerate(remark.split('\n')): c.drawString(50, 240 - (i*15), line)
    c.showPage(); c.save(); buffer.seek(0)
    return buffer

# --- UI ---
st.set_page_config(page_title="대형환경(주) 견적 시스템", layout="wide")
if 'q_items' not in st.session_state: st.session_state['q_items'] = []

st.title("📄 대형환경(주) 통합 견적 시스템")
col_l, col_r = st.columns([1, 1.2])

with col_l:
    st.subheader("🛠️ 견적 데이터 입력")
    client = st.text_input("수신처", placeholder="입력하세요 (예: OO설계사무소)")
    project = st.text_input("공사명", placeholder="입력하세요 (예: 세종시 OO공사)")
    valid_date = st.text_input("유효기간", (datetime.now() + timedelta(days=180)).strftime("%Y년 %m월 %d일"))

    t_w, t_a = st.tabs(["♻️ 폐기물 처리", "🪨 순환골재 납품"])
    with t_w:
        w_type = st.selectbox("폐기물 성상", list(WASTE_DATA.keys()))
        w_qty = st.number_input("수량(ton)", min_value=0.0, value=1.00, step=0.01, format="%.2f", key="wq_input")
        dist_mode = st.selectbox("운반거리", ["30km", "35km", "40km", "50km", "60km", "60km 초과"], key="dist_input")
        m_dist = st.number_input("실제거리(km)", min_value=61, value=70) if dist_mode == "60km 초과" else 0
        holiday = st.checkbox("휴일/야간 할증(15%)")
        
        if st.button("➕ 폐기물 항목 추가"):
            unit = (WASTE_DATA[w_type] * (1.15 if holiday else 1.0)) + calculate_transport(dist_mode, m_dist)
            st.session_state['q_items'].append({
                "품명": w_type, "규격": f"L={m_dist if dist_mode=='60km 초과' else dist_mode}",
                "수량": w_qty, "단위": "ton", "단가": unit, "금액": unit * w_qty
            })

    with t_a:
        a_spec = st.text_input("골재 규격", value="40mm (도로기층용)")
        a_qty = st.number_input("수량(m³)", min_value=0.0, value=1.00, step=0.01, format="%.2f")
        a_price = st.number_input("단가(제품+운반)", min_value=0, value=20000)
        if st.button("➕ 골재 항목 추가"):
            st.session_state['q_items'].append({
                "품명": "순환골재", "규격": a_spec, "수량": a_qty, "단위": "m³", "단가": a_price, "금액": a_qty * a_price
            })

    rem_txt = st.text_area("비고 내용", "1. 부가세 별도.\n2. 상차비 별도.\n3. 25.5톤 덤프 용적 17㎡ 적용.")
    if st.button("🗑️ 전체 내역 삭제"):
        st.session_state['q_items'] = []; st.rerun()

with col_r:
    st.subheader("🔍 견적 미리보기")
    if st.session_state['q_items']:
        df = pd.DataFrame(st.session_state['q_items'])
        
        # 개별 삭제 기능 구현
        for i, row in df.iterrows():
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{i+1}. {row['품명']}** ({row['규격']}) : {row['수량']:,.2f} {row['단위']} × {row['단가']:,.0f}원 = **{row['금액']:,.0f}원**")
            if c2.button("삭제", key=f"del_{i}"):
                st.session_state['q_items'].pop(i)
                st.rerun()
        
        total = sum(item['금액'] for item in st.session_state['q_items'])
        with st.container(border=True):
            st.markdown("<h2 style='text-align: center;'>견 적 서</h2>", unsafe_allow_html=True)
            st.write(f"**수신:** {client if client else '(미입력)'} 귀중")
            st.write(f"**합계금액:** 일금 {num_to_kor(total)}")
            st.table(pd.DataFrame(st.session_state['q_items']).style.format({"수량": "{:,.2f}", "단가": "{:,.0f}", "금액": "{:,.0f}"}))
            st.info(rem_txt)
            pdf = generate_pdf(client, project, st.session_state['q_items'], rem_txt, valid_date, total)
            st.download_button("📥 정식 PDF 다운로드", pdf, f"견적서_{client}.pdf")
    else:
        st.info("왼쪽에서 항목을 작성하신 후 **[추가]** 버튼을 눌러주세요.")