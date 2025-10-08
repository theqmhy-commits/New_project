import streamlit as st
import pandas as pd
import numpy as np
import io
import json
from google import genai
from google.genai.errors import APIError

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="Phân Tích Hiệu Quả Dự Án Đầu Tư (NPV/IRR)",
    layout="wide"
)

st.title("💰 Ứng dụng Phân Tích Hiệu Quả Dự Án Đầu Tư (NPV/IRR)")
st.caption("Sử dụng Gemini AI để trích xuất thông số tài chính từ file Word và đánh giá tính khả thi của dự án.")

# --- 1. Hàm AI: Trích xuất Dữ liệu (Sử dụng Structured Output) ---
@st.cache_data(show_spinner=False)
def extract_financial_data(file_content, api_key):
    """
    Gửi nội dung file Word (dạng bytes) đến Gemini API và yêu cầu trích xuất dữ liệu tài chính
    theo cấu trúc JSON định sẵn.
    """
    try:
        client = genai.Client(api_key=api_key)
        
        # Yêu cầu trích xuất 6 thông số cần thiết
        user_prompt = """
        Bạn là một chuyên gia tài chính. Hãy đọc nội dung thô của tài liệu đính kèm (là file Word về phương án kinh doanh) và trích xuất chính xác 6 thông số sau:
        1. Vốn đầu tư ban đầu (VND) - Initial Investment (C0)
        2. Vòng đời dự án (năm) - Project Life (N)
        3. Doanh thu hàng năm (VND) - Annual Revenue
        4. Chi phí hoạt động hàng năm (VND) - Annual Operating Cost (chưa bao gồm thuế)
        5. Chi phí sử dụng vốn bình quân (WACC) - Cost of Capital (r)
        6. Thuế suất (Tax Rate) - t
        
        Nếu một thông số không thể tìm thấy, hãy điền giá trị là 0.
        Đảm bảo đơn vị tiền tệ là VND (ví dụ: 30000000000) và tỷ lệ (WACC, Thuế) là số thập phân (ví dụ: 0.13 cho 13%).
        """
        
        # Định nghĩa Schema cho đầu ra JSON (Task 1)
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "Vốn_đầu_tư": {"type": "NUMBER", "description": "Vốn đầu tư ban đầu (C0) - VND"},
                "Vòng_đời_dự_án": {"type": "NUMBER", "description": "Vòng đời dự án (N) - Năm"},
                "Doanh_thu_hàng_năm": {"type": "NUMBER", "description": "Doanh thu hàng năm - VND"},
                "Chi_phí_hàng_năm": {"type": "NUMBER", "description": "Chi phí hoạt động hàng năm - VND"},
                "WACC": {"type": "NUMBER", "description": "Chi phí sử dụng vốn bình quân (r) - Tỷ lệ thập phân"},
                "Thuế_suất": {"type": "NUMBER", "description": "Thuế suất (t) - Tỷ lệ thập phân"}
            }
        }

        # Gửi file content (bytes) và prompt đến API
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-05-20',
            contents=[
                user_prompt,
                {"inlineData": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "data": file_content}}
            ],
            config={
                "responseMimeType": "application/json",
                "responseSchema": response_schema
            }
        )

        # Chuyển đổi chuỗi JSON trả về thành đối tượng Python
        return json.loads(response.text)

    except APIError as e:
        st.error(f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API hoặc giới hạn sử dụng. Chi tiết lỗi: {e}")
        return None
    except json.JSONDecodeError:
        st.error("Lỗi: AI không trả về định dạng JSON hợp lệ. Vui lòng kiểm tra nội dung file Word.")
        return None
    except Exception as e:
        st.error(f"Đã xảy ra lỗi không xác định trong quá trình trích xuất AI: {e}")
        return None


# --- 2 & 3. Hàm Tính toán Dòng tiền và Chỉ số ---
@st.cache_data
def calculate_project_metrics(data):
    """
    Tính toán Dòng tiền, NPV, IRR, PP và DPP.
    """
    try:
        # Lấy các thông số
        C0 = data['Vốn_đầu_tư']
        N = int(data['Vòng_đời_dự_án'])
        Revenue = data['Doanh_thu_hàng_năm']
        Cost = data['Chi_phí_hàng_năm']
        WACC = data['WACC']
        Tax_Rate = data['Thuế_suất']

        if N <= 0 or WACC <= 0:
            return None, "Vòng đời dự án và WACC phải lớn hơn 0."
        
        # 1. Tính Dòng tiền thuần hàng năm (FCF) - Task 2
        PBT = Revenue - Cost
        Tax = PBT * Tax_Rate
        FCF_t = PBT - Tax # Lợi nhuận sau thuế (FCF, giả định FCF = Lợi nhuận sau thuế)
        
        # Chuỗi dòng tiền (Cash Flows)
        cash_flows = [-C0] + [FCF_t] * N
        
        # 2. Tính toán Chỉ số - Task 3
        # NPV
        NPV = np.npv(WACC, cash_flows)
        
        # IRR
        try:
            IRR = np.irr(cash_flows)
        except ValueError:
            IRR = np.nan # Không thể tính IRR nếu dòng tiền không đổi dấu

        # PP (Payback Period / Thời gian hoàn vốn)
        PP = C0 / FCF_t if FCF_t > 0 else float('inf')
        
        # DPP (Discounted Payback Period / Thời gian hoàn vốn có chiết khấu)
        cumulative_discounted_cf = 0
        DPP = float('inf')
        discounted_fcf_list = []
        
        for t in range(1, N + 1):
            discounted_fcf = FCF_t / ((1 + WACC)**t)
            discounted_fcf_list.append(discounted_fcf)
            cumulative_discounted_cf += discounted_fcf
            
            if DPP == float('inf') and cumulative_discounted_cf >= C0:
                # Tìm thời điểm hoàn vốn: Năm t-1 + (Vốn còn lại / Dòng tiền chiết khấu của năm t)
                capital_needed = C0 - (cumulative_discounted_cf - discounted_fcf)
                DPP = (t - 1) + (capital_needed / discounted_fcf)
                
        # Tạo Bảng Dòng tiền (Cash Flow Table) - Task 2
        df_cf = pd.DataFrame({
            'Năm': [0] + list(range(1, N + 1)),
            'Dòng tiền thuần (FCF)': [f"({C0:,.0f})" if C0 > 0 else "0"] + [f"{FCF_t:,.0f}"] * N,
            'Chiết khấu ({:.2f}%)'.format(WACC * 100): [1.0] + [1 / ((1 + WACC)**t) for t in range(1, N + 1)],
            'Giá trị hiện tại của FCF': [f"({C0:,.0f})" if C0 > 0 else "0"] + [f"{dcf:,.0f}" for dcf in discounted_fcf_list]
        })

        metrics = {
            "NPV": NPV,
            "IRR": IRR,
            "PP": PP,
            "DPP": DPP,
            "WACC": WACC
        }
        
        return df_cf, metrics

    except Exception as e:
        return None, f"Lỗi tính toán: {e}. Vui lòng kiểm tra dữ liệu đã trích xuất."

# --- 4. Hàm AI: Phân tích các chỉ số (Task 4) ---
def get_ai_project_analysis(metrics, df_cf, extracted_data, api_key):
    """Gửi các chỉ số đã tính toán đến Gemini API và nhận nhận xét."""
    try:
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        Bạn là chuyên gia thẩm định dự án đầu tư. Dựa trên các thông số dự án và chỉ số hiệu quả tài chính sau, hãy đưa ra một bài phân tích khách quan, chuyên nghiệp (khoảng 4-5 đoạn).

        **1. Tóm tắt các thông số đầu vào:**
        - Vốn đầu tư ban đầu (C0): {extracted_data['Vốn_đầu_tư']:,.0f} VNĐ
        - Vòng đời dự án (N): {extracted_data['Vòng_đời_dự_án']} năm
        - Lợi nhuận trước thuế (PBT) hàng năm: {(extracted_data['Doanh_thu_hàng_năm'] - extracted_data['Chi_phí_hàng_năm']):,.0f} VNĐ
        - Dòng tiền thuần (FCF) hàng năm: {(extracted_data['Doanh_thu_hàng_năm'] - extracted_data['Chi_phí_hàng_năm']) * (1 - extracted_data['Thuế_suất']):,.0f} VNĐ
        - Chi phí sử dụng vốn (WACC): {metrics['WACC'] * 100:.2f}%
        
        **2. Các chỉ số hiệu quả dự án:**
        - Giá trị hiện tại ròng (NPV): {metrics['NPV']:,.0f} VNĐ
        - Tỷ suất sinh lời nội bộ (IRR): {metrics['IRR'] * 100:.2f}% (hoặc N/A)
        - Thời gian hoàn vốn (PP): {metrics['PP']:.2f} năm
        - Thời gian hoàn vốn có chiết khấu (DPP): {metrics['DPP']:.2f} năm

        **Yêu cầu phân tích:**
        1. Đánh giá tính khả thi tài chính của dự án (So sánh NPV với 0, IRR với WACC).
        2. Nhận xét về tốc độ hoàn vốn (So sánh PP và DPP với Vòng đời dự án).
        3. Phân tích độ nhạy cảm của dự án (mức an toàn) dựa trên chênh lệch giữa IRR và WACC.
        4. Đưa ra 2-3 kiến nghị cụ thể để cải thiện hiệu quả tài chính của dự án (ví dụ: tăng doanh thu, giảm chi phí đầu tư, đàm phán WACC).
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định khi yêu cầu phân tích AI: {e}"


# --- Luồng Ứng dụng Streamlit Chính ---

# Khai báo biến state để lưu trữ dữ liệu
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'metrics' not in st.session_state:
    st.session_state.metrics = None
if 'df_cf' not in st.session_state:
    st.session_state.df_cf = None

api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
    st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets.")

# --- Task 1: Tải File và Lọc Dữ liệu ---
st.subheader("1. Tải File Word (.docx) và Trích xuất Dữ liệu (AI)")

uploaded_file = st.file_uploader(
    "Vui lòng tải lên file Phương án Kinh doanh (Chỉ hỗ trợ định dạng .docx)",
    type=['docx']
)

if uploaded_file is not None and api_key:
    if st.button("Lọc Dữ liệu Dự án (Sử dụng AI)", key="extract_button"):
        with st.spinner('Đang gửi nội dung file Word đến AI để trích xuất các thông số...'):
            # Đọc nội dung file Word (dạng bytes)
            file_content = uploaded_file.read()
            
            # Gọi hàm trích xuất
            data = extract_financial_data(file_content, api_key)
            st.session_state.extracted_data = data
            st.session_state.metrics = None # Reset metrics khi có dữ liệu mới
            st.session_state.df_cf = None

    if st.session_state.extracted_data:
        st.success("✅ Trích xuất dữ liệu thành công!")
        
        # Hiển thị các thông số đã trích xuất
        st.markdown("**Các thông số đã trích xuất:**")
        data_display = st.session_state.extracted_data
        
        # Format lại dữ liệu cho dễ đọc
        col1, col2, col3 = st.columns(3)
        col1.metric("Vốn đầu tư (C0)", f"{data_display['Vốn_đầu_tư']:,.0f} VNĐ")
        col2.metric("Doanh thu Hàng năm", f"{data_display['Doanh_thu_hàng_năm']:,.0f} VNĐ")
        col3.metric("Chi phí Hàng năm", f"{data_display['Chi_phí_hàng_năm']:,.0f} VNĐ")
        
        col4, col5, col6 = st.columns(3)
        col4.metric("Vòng đời Dự án (N)", f"{int(data_display['Vòng_đời_dự_án'])} năm")
        col5.metric("WACC (r)", f"{data_display['WACC'] * 100:.2f}%")
        col6.metric("Thuế suất (t)", f"{data_display['Thuế_suất'] * 100:.2f}%")
        
        # Tính toán Dòng tiền và Chỉ số
        df_cf, metrics = calculate_project_metrics(st.session_state.extracted_data)
        st.session_state.df_cf = df_cf
        st.session_state.metrics = metrics

# --- Task 2 & 3: Hiển thị Dòng tiền và Chỉ số ---
if st.session_state.df_cf is not None and st.session_state.metrics is not None:
    
    st.markdown("---")
    st.subheader("2. Bảng Dòng tiền Dự án (Cash Flow Table)")
    st.dataframe(st.session_state.df_cf, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("3. Các Chỉ số Đánh giá Hiệu quả Dự án")
    
    # Hiển thị các chỉ số tài chính
    metrics_data = st.session_state.metrics
    col_a, col_b, col_c, col_d = st.columns(4)

    col_a.metric("NPV (Giá trị hiện tại ròng)", f"{metrics_data['NPV']:,.0f} VNĐ")
    col_b.metric("IRR (Tỷ suất sinh lời nội bộ)", f"{metrics_data['IRR'] * 100:.2f}%" if not np.isnan(metrics_data['IRR']) else "N/A")
    col_c.metric("PP (Thời gian hoàn vốn)", f"{metrics_data['PP']:.2f} năm")
    col_d.metric("DPP (Hoàn vốn có chiết khấu)", f"{metrics_data['DPP']:.2f} năm")
    
    # Hiển thị trạng thái dự án
    if metrics_data['NPV'] > 0 and metrics_data['IRR'] > metrics_data['WACC']:
        st.success(f"Dự án **KHẢ THI** về mặt tài chính (NPV > 0, IRR > WACC {metrics_data['WACC']*100:.2f}%)")
    elif metrics_data['NPV'] <= 0 or metrics_data['IRR'] <= metrics_data['WACC']:
        st.error(f"Dự án **KHÔNG KHẢ THI** về mặt tài chính (NPV <= 0 hoặc IRR <= WACC {metrics_data['WACC']*100:.2f}%)")
    else:
        st.warning("Không thể đánh giá do thiếu dữ liệu IRR.")

    # --- Task 4: Yêu cầu AI Phân tích ---
    st.markdown("---")
    st.subheader("4. Phân tích Chuyên sâu (AI)")
    
    if st.button("Yêu cầu AI Phân tích & Khuyến nghị", key="ai_analysis_button"):
        with st.spinner('Đang gửi dữ liệu và chờ Gemini AI phân tích chuyên sâu...'):
            ai_result = get_ai_project_analysis(
                st.session_state.metrics, 
                st.session_state.df_cf, 
                st.session_state.extracted_data, 
                api_key
            )
            st.info(ai_result)

else:
    if uploaded_file is None:
        st.info("Vui lòng tải lên file Word Phương án Kinh doanh (.docx) để bắt đầu phân tích.")
    elif api_key and st.session_state.extracted_data is None:
         st.warning("Vui lòng nhấn nút 'Lọc Dữ liệu Dự án (Sử dụng AI)' để trích xuất thông số.")
