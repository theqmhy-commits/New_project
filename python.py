# investment_app.py - Phiên bản HOÀN CHỈNH (Sửa lỗi Rerun và Thêm Chỉnh sửa Thủ công)

import streamlit as st
import pandas as pd
import numpy as np
import numpy_financial as npf 
from google import genai
from google.genai.errors import APIError
from docx import Document
import io
import re

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Đánh Giá Phương Án Kinh Doanh",
    layout="wide"
)

st.title("Ứng dụng Đánh giá Phương án Kinh doanh 📈")

# --- Hàm đọc file Word ---
def read_docx_file(uploaded_file):
    """Đọc nội dung văn bản từ file Word."""
    try:
        doc = Document(io.BytesIO(uploaded_file.read()))
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        return f"Lỗi đọc file Word: {e}"

# --- Hàm gọi API Gemini để trích xuất thông tin (Yêu cầu 1) ---
@st.cache_data
def extract_financial_data(doc_text, api_key):
    """Sử dụng Gemini để trích xuất các thông số tài chính từ văn bản."""
    
    if not api_key:
        raise ValueError("Khóa API không được cung cấp.")
        
    client = genai.Client(api_key=api_key)
    model_name = 'gemini-2.5-flash'
    
    prompt = f"""
    Bạn là một chuyên gia tài chính và phân tích dự án. Nhiệm vụ của bạn là trích xuất các thông số sau từ nội dung văn bản kinh doanh bên dưới. 
    Các thông số này phải là GIÁ TRỊ SỐ, không có đơn vị (ví dụ: 1000000). 
    
    Vốn đầu tư (Initial Investment - C0): Giá trị tuyệt đối của vốn ban đầu cần bỏ ra.
    Dòng đời dự án (Project Life - N): Số năm hoạt động của dự án.
    WACC (Cost of Capital - k): Tỷ lệ chiết khấu (dạng thập phân, ví dụ: 0.10 cho 10%).
    Thuế suất (Tax Rate - t): Tỷ lệ thuế thu nhập doanh nghiệp (dạng thập phân, ví dụ: 0.20 cho 20%).
    
    Doanh thu hàng năm (Annual Revenue - R): Nếu không có thông tin chi tiết từng năm, hãy ước tính một con số đại diện cho doanh thu hàng năm.
    Chi phí hoạt động hàng năm (Annual Operating Cost - C): Nếu không có thông tin chi tiết từng năm, hãy ước tính một con số đại diện cho chi phí hoạt động hàng năm (chưa bao gồm Khấu hao).
    
    Nếu không tìm thấy thông tin cụ thể, hãy trả về 0 cho giá trị số (trừ WACC và Thuế suất nên là 0.2 nếu không tìm thấy).

    Định dạng đầu ra **bắt buộc** là JSON nguyên mẫu (RAW JSON), không có bất kỳ giải thích hay văn bản nào khác.
    
    {{
      "Vốn đầu tư": <Giá trị số>,
      "Dòng đời dự án": <Giá trị số năm>,
      "Doanh thu hàng năm": <Giá trị số>,
      "Chi phí hoạt động hàng năm": <Giá trị số>,
      "WACC": <Giá trị số thập phân>,
      "Thuế suất": <Giá trị số thập phân>
    }}

    Nội dung file Word:
    ---
    {doc_text}
    """

    response = client.models.generate_content(
        model=model_name,
        contents=prompt
    )
    
    json_str = response.text.strip().replace("```json", "").replace("```", "").strip()
    return pd.read_json(io.StringIO(json_str), typ='series')


# --- Hàm tính toán Chỉ số Tài chính (Yêu cầu 3) ---
def calculate_project_metrics(df_cashflow, initial_investment, wacc):
    """Tính toán NPV, IRR, PP, DPP."""
    
    cash_flows = df_cashflow['Dòng tiền thuần (CF)'].values
    
    # 1. NPV
    full_cash_flows = np.insert(cash_flows, 0, -initial_investment) 
    npv_value = npf.npv(wacc, full_cash_flows)
    
    # 2. IRR
    try:
        irr_value = npf.irr(full_cash_flows)
    except ValueError:
        irr_value = np.nan 

    # 3. PP (Payback Period - Thời gian hoàn vốn)
    cumulative_cf = np.cumsum(full_cash_flows)
    pp_year = np.where(cumulative_cf >= 0)[0]
    if pp_year.size > 0:
        pp_year = pp_year[0]
        if pp_year == 0: 
             pp = 0 
        else:
             capital_remaining = abs(cumulative_cf[pp_year-1])
             cf_of_payback_year = cash_flows[pp_year-1]
             pp = pp_year - 1 + (capital_remaining / cf_of_payback_year) if cf_of_payback_year != 0 else pp_year 
    else:
        pp = 'Không hoàn vốn'

    # 4. DPP (Discounted Payback Period - Thời gian hoàn vốn có chiết khấu)
    discount_factors = 1 / ((1 + wacc) ** np.arange(0, len(full_cash_flows)))
    discounted_cf = full_cash_flows * discount_factors
    cumulative_dcf = np.cumsum(discounted_cf)
    
    dpp_year = np.where(cumulative_dcf >= 0)[0]
    if dpp_year.size > 0:
        dpp_year = dpp_year[0]
        if dpp_year == 0:
             dpp = 0
        else:
             capital_remaining_d = abs(cumulative_dcf[dpp_year-1])
             dcf_of_payback_year = discounted_cf[dpp_year] 
             dpp = dpp_year - 1 + (capital_remaining_d / dcf_of_payback_year) if dcf_of_payback_year != 0 else dpp_year
    else:
        dpp = 'Không hoàn vốn'
        
    return npv_value, irr_value, pp, dpp

# --- Hàm gọi AI phân tích chỉ số (Yêu cầu 4) ---
def get_ai_evaluation(metrics_data, wacc_rate, api_key):
    """Gửi các chỉ số đánh giá dự án đến Gemini API và nhận phân tích."""
    
    if not api_key:
        return "Lỗi: Khóa API không được cung cấp."

    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'  

        prompt = f"""
        Bạn là một chuyên gia phân tích dự án đầu tư có kinh nghiệm. Dựa trên các chỉ số hiệu quả dự án sau, hãy đưa ra nhận xét ngắn gọn, khách quan (khoảng 3-4 đoạn) về khả năng chấp nhận và rủi ro của dự án. 
        
        Các chỉ số cần phân tích:
        - NPV: {metrics_data['NPV']:.2f}
        - IRR: {metrics_data['IRR']:.2%}
        - WACC (Tỷ lệ chiết khấu): {wacc_rate:.2%}
        - PP (Thời gian hoàn vốn): {metrics_data['PP']} năm
        - DPP (Thời gian hoàn vốn có chiết khấu): {metrics_data['DPP']} năm
        
        Chú ý:
        1. Đánh giá tính khả thi (NPV > 0 và IRR > WACC).
        2. Nhận xét về tốc độ hoàn vốn (PP và DPP).
        3. Kết luận tổng thể về việc chấp nhận hay từ chối dự án.
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định: {e}"

# --- Giao diện và Luồng chính ---

# Lấy API Key
api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
     st.error("⚠️ Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets để sử dụng chức năng AI.")

uploaded_file = st.file_uploader(
    "1. Tải file Word (.docx) chứa Phương án Kinh doanh:",
    type=['docx']
)

# Khởi tạo state để lưu trữ dữ liệu đã trích xuất VÀ dữ liệu người dùng đã xác nhận
if 'extracted_data' not in st.session_state:
    st.session_state['extracted_data'] = None
if 'confirmed_data' not in st.session_state:
    st.session_state['confirmed_data'] = None

# --- Chức năng 1: Lọc dữ liệu bằng AI ---
if uploaded_file is not None:
    doc_text = read_docx_file(uploaded_file)
    
    if st.button("Trích xuất Dữ liệu Tài chính bằng AI 🤖"):
        st.session_state['confirmed_data'] = None # Reset dữ liệu xác nhận khi trích xuất mới
        if api_key:
            with st.spinner('Đang đọc và trích xuất thông số tài chính bằng Gemini...'):
                try:
                    raw_data = extract_financial_data(doc_text, api_key)
                    
                    # ****************** Tiền xử lý dữ liệu trích xuất ******************
                    # Đảm bảo các giá trị là float/int hợp lệ, dùng 0 nếu lỗi
                    data_dict = {
                        'Vốn đầu tư': float(raw_data.get('Vốn đầu tư', 0)),
                        'Dòng đời dự án': int(raw_data.get('Dòng đời dự án', 0)),
                        'Doanh thu hàng năm': float(raw_data.get('Doanh thu hàng năm', 0)),
                        'Chi phí hoạt động hàng năm': float(raw_data.get('Chi phí hoạt động hàng năm', 0)),
                        'WACC': float(raw_data.get('WACC', 0.1)),
                        'Thuế suất': float(raw_data.get('Thuế suất', 0.2))
                    }
                    
                    # Chuẩn hóa WACC và Thuế suất về dạng thập phân nếu > 1
                    if data_dict['WACC'] > 1: data_dict['WACC'] /= 100
                    if data_dict['Thuế suất'] > 1: data_dict['Thuế suất'] /= 100
                    
                    st.session_state['extracted_data'] = data_dict
                    st.success("Trích xuất dữ liệu thành công! Vui lòng kiểm tra và xác nhận các thông số bên dưới.")
                except Exception as e:
                    st.error(f"Lỗi trích xuất hoặc định dạng dữ liệu: {e}")
        else:
            st.error("Vui lòng cung cấp Khóa API.")

# --- Chức năng 2: Hiển thị và Cập nhật Thủ công ---
if st.session_state['extracted_data'] is not None:
    data = st.session_state['extracted_data']
    st.subheader("2. Kiểm tra và Cập nhật Thông số Dự án (Thủ công)")
    st.info("💡 Các thông số đã được AI trích xuất (hoặc gán giá trị mặc định) sẽ được điền vào ô bên dưới. **Vui lòng kiểm tra và sửa lại** nếu cần.")
    
    # Tạo Form để người dùng dễ dàng xác nhận/sửa dữ liệu
    with st.form("data_correction_form"):
        col1, col2, col3 = st.columns(3)
        
        # Cột 1: Vốn & Doanh thu
        with col1:
            initial_investment = st.number_input(
                "Vốn Đầu tư (C₀) (VNĐ)", 
                min_value=0.0, 
                value=data['Vốn đầu tư'],
                step=1000000.0,
                format="%.0f"
            )
            annual_revenue = st.number_input(
                "Doanh thu Hàng năm (R) (VNĐ)", 
                min_value=0.0, 
                value=data['Doanh thu hàng năm'],
                step=1000000.0,
                format="%.0f"
            )

        # Cột 2: Dòng đời & Chi phí
        with col2:
            # Đảm bảo Dòng đời dự án ít nhất là 1 để tránh lỗi chia cho 0
            project_life = st.number_input(
                "Dòng đời dự án (N) (Năm)", 
                min_value=1, 
                value=data['Dòng đời dự án'] if data['Dòng đời dự án'] >= 1 else 1
            )
            annual_cost = st.number_input(
                "Chi phí HĐ Hàng năm (C) (VNĐ)", 
                min_value=0.0, 
                value=data['Chi phí hoạt động hàng năm'],
                step=1000000.0,
                format="%.0f"
            )
            
        # Cột 3: WACC & Thuế suất
        with col3:
            wacc = st.number_input(
                "WACC (k) (%)", 
                min_value=0.01, # Đảm bảo WACC tối thiểu 1%
                max_value=100.0, 
                value=data['WACC'] * 100,
                step=0.1,
                format="%.2f"
            ) / 100.0 # Chuyển lại về dạng thập phân
            tax_rate = st.number_input(
                "Thuế suất (t) (%)", 
                min_value=0.0, 
                max_value=100.0, 
                value=data['Thuế suất'] * 100,
                step=0.1,
                format="%.2f"
            ) / 100.0 # Chuyển lại về dạng thập phân
        
        # Nút xác nhận
        submitted = st.form_submit_button("Xác nhận & Tính toán 🚀")
        
        if submitted:
            if project_life <= 0 or initial_investment < 0 or wacc <= 0:
                st.error("Lỗi: Dòng đời dự án và WACC phải lớn hơn 0 để tính toán.")
            else:
                st.session_state['confirmed_data'] = {
                    'Vốn đầu tư': initial_investment,
                    'Dòng đời dự án': project_life,
                    'Doanh thu hàng năm': annual_revenue,
                    'Chi phí hoạt động hàng năm': annual_cost,
                    'WACC': wacc,
                    'Thuế suất': tax_rate
                }
                # SỬA LỖI: Thay st.experimental_rerun() bằng st.rerun()
                st.rerun() 

# --- Bắt đầu tính toán (Chức năng 3, 4, 5) ---
if st.session_state['confirmed_data'] is not None:
    
    # Lấy dữ liệu đã được người dùng xác nhận
    data = st.session_state['confirmed_data']
    initial_investment = data['Vốn đầu tư']
    project_life = data['Dòng đời dự án']
    annual_revenue = data['Doanh thu hàng năm']
    annual_cost = data['Chi phí hoạt động hàng năm']
    wacc = data['WACC']
    tax_rate = data['Thuế suất']
    
    # ****************** Bảng Dòng tiền (Yêu cầu 3) ******************
    st.subheader("3. Bảng Dòng tiền (Cash Flow)")
    
    # Tính Khấu hao và Dòng tiền
    depreciation = initial_investment / project_life 
    years = np.arange(1, project_life + 1)
    
    EBT = annual_revenue - annual_cost - depreciation
    Tax = EBT * tax_rate if EBT > 0 else 0
    EAT = EBT - Tax
    CF = EAT + depreciation
    
    cashflow_data = {
        'Năm': years,
        'Doanh thu (R)': [annual_revenue] * project_life,
        'Chi phí HĐ (C)': [annual_cost] * project_life,
        'Khấu hao (D)': [depreciation] * project_life,
        'Lợi nhuận trước thuế (EBT)': [EBT] * project_life,
        'Thuế (Tax)': [Tax] * project_life,
        'Lợi nhuận sau thuế (EAT)': [EAT] * project_life,
        'Dòng tiền thuần (CF)': [CF] * project_life
    }
    
    df_cashflow = pd.DataFrame(cashflow_data)
    
    st.dataframe(
        df_cashflow.style.format({
            col: '{:,.0f}' for col in df_cashflow.columns if col not in ['Năm']
        }), 
        use_container_width=True
    )

    st.markdown("---")
    
    # ****************** Tính toán Chỉ số (Yêu cầu 4) ******************
    st.subheader("4. Các Chỉ số Đánh giá Hiệu quả Dự án")
    
    try:
        npv, irr, pp, dpp = calculate_project_metrics(df_cashflow, initial_investment, wacc)
        
        metrics_data = {
            'NPV': npv,
            'IRR': irr if not np.isnan(irr) else 0,
            'PP': pp,
            'DPP': dpp
        }
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("NPV (Giá trị hiện tại thuần)", f"{npv:,.0f} VNĐ", delta=("Dự án có lời" if npv > 0 else "Dự án lỗ"))
        col2.metric("IRR (Tỷ suất sinh lời nội tại)", f"{irr:.2%}" if not np.isnan(irr) else "Không tính được")
        col3.metric("PP (Thời gian hoàn vốn)", f"{pp:.2f} năm" if isinstance(pp, float) or isinstance(pp, np.float64) else pp)
        col4.metric("DPP (Hoàn vốn có chiết khấu)", f"{dpp:.2f} năm" if isinstance(dpp, float) or isinstance(dpp, np.float64) else dpp)

        # ****************** Phân tích AI (Yêu cầu 5) ******************
        st.markdown("---")
        st.subheader("5. Phân tích Hiệu quả Dự án (AI)")
        
        if st.button("Yêu cầu AI Phân tích Chỉ số 🧠"):
            if api_key:
                with st.spinner('Đang gửi dữ liệu và chờ Gemini phân tích...'):
                    ai_result = get_ai_evaluation(metrics_data, wacc, api_key)
                    st.markdown("**Kết quả Phân tích từ Gemini AI:**")
                    st.info(ai_result)
            else:
                 st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng kiểm tra cấu hình Secrets.")

    except Exception as e:
        st.error(f"Có lỗi xảy ra khi tính toán chỉ số: {e}. Vui lòng kiểm tra lại các thông số đầu vào đã xác nhận.")

# Hiển thị hướng dẫn nếu chưa tải file
if uploaded_file is None:
    st.info("Vui lòng tải lên file Word và nhấn nút 'Trích xuất Dữ liệu Tài chính bằng AI' để bắt đầu.")
