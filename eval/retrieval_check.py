"""Kiểm tra nhanh truy xuất: mỗi câu hỏi có (doc, mã số) chỉ tiêu cần xuất hiện trong top-k.
Hit@k = tỉ lệ câu hỏi có đoạn đúng trong k kết quả đầu; MRR = trung bình 1/hạng của đoạn đúng đầu tiên.
Chạy: python eval/retrieval_check.py [--retriever data/processed/retriever.pkl] [--show]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.rag.retriever import HybridRetriever  # noqa: E402

# (câu hỏi, doc cần có, từ khóa bắt buộc trong đoạn đúng)
CASES = [
    ("Doanh thu thuần hợp nhất Q1/2026 là bao nhiêu?", "q1-2026", "(mã số 10)"),
    ("Lợi nhuận sau thuế quý 2 năm 2026?", "q2-2026", "(mã số 60)"),
    ("Tổng tài sản tại ngày 31/12/2025", "q4-2025", "(mã số 270)"),
    ("Tổng tài sản cuối quý 2/2026 là bao nhiêu", "q2-2026", "(mã số 280)"),
    ("Giá vốn hàng bán Q3/2025", "q3-2025", "(mã số 11)"),
    ("Chi phí bán hàng 6 tháng đầu năm 2026", "q2-2026", "(mã số 25)"),
    ("Lưu chuyển tiền thuần từ hoạt động kinh doanh quý 1/2025", "q1-2025", "(mã số 20)"),
    ("Vay ngắn hạn tại ngày 30/6/2025 là bao nhiêu", "q2-2025", "Vay ngắn hạn (mã số 320)"),
    ("Phải trả người bán quý III/2025", "q3-2025", "(mã số 311)"),
    ("Lợi nhuận gộp quý 4 năm 2025", "q4-2025", "(mã số 20)"),
    ("Vốn chủ sở hữu 31/3/2026", "q1-2026", "(mã số 400)"),
    ("Lợi ích cổ đông không kiểm soát Q2/2025", "q2-2025", "(mã số 429)"),
    ("Chi phí lãi vay Q1/2025 trong thuyết minh chi phí tài chính", "q1-2025", "lãi vay"),
    ("Dự phòng trợ cấp thôi việc quý 1 năm 2026", "q1-2026", "trợ cấp thôi việc"),
]


# Câu hỏi diễn đạt khác với tên chỉ tiêu trong báo cáo (đồng nghĩa/văn nói): phép thử cho nhánh vector.
PARAPHRASE = [
    ("Quý 2 năm 2026 công ty lãi ròng bao nhiêu?", "q2-2026", "(mã số 60)"),
    ("Tiền mặt và tương đương tiền cuối kỳ Q1 2026", "q1-2026", "(mã số 110)"),
    ("Lượng tiền công ty đang nắm giữ cuối quý 3/2025", "q3-2025", "(mã số 110)"),
    ("Khoản vay ngân hàng ngắn hạn tại 30/9/2025", "q3-2025", "(mã số 320)"),
    ("Công ty lời bao nhiêu trước khi đóng thuế quý 1/2026?", "q1-2026", "(mã số 50)"),
    ("Hàng tồn kho cuối quý 2/2025", "q2-2025", "(mã số 140)"),
    ("Công ty bán được bao nhiêu tiền hàng trong quý 3/2025 sau khi trừ giảm giá?", "q3-2025", "(mã số 10)"),
    ("Tổng nợ của công ty tại 31/12/2025", "q4-2025", "(mã số 300)"),
    ("Chi phí quảng cáo khuyến mãi quý 1 năm 2025", "q1-2025", "(mã số 25)"),
    ("Tiền công ty bỏ ra mua máy móc nhà xưởng 6 tháng 2026", "q2-2026", "(mã số 21)"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retriever", default="data/processed/retriever.pkl")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    r = HybridRetriever.load(a.retriever)
    for name, cases in (("TỪ KHÓA", CASES), ("ĐỒNG NGHĨA", PARAPHRASE)):
        print(f"--- {name} ({len(cases)} câu) ---")
        run_group(r, cases, a)


def run_group(r, CASES, a):
    runs =[("bm25", "bm25", None), ("vector", "vector", None), ("hybrid", "hybrid", None)]
    runs += [(f"hybrid w_vec={wv}", "hybrid", {"vector": wv}) for wv in (0.5, 0.3, 0.15)]
    for label, mode, weights in runs:
        hit = rr = 0.0
        misses = []
        for q, doc, needle in CASES:
            hits = r.search(q, k=a.k, mode=mode, weights=weights)
            rank = next((i for i, h in enumerate(hits, 1) if h.chunk["doc"] == doc and needle in h.chunk["text"]), None)
            if rank:
                hit += 1
                rr += 1 / rank
            else:
                misses.append(q)
            if a.show and mode == "hybrid":
                print(f"\n# {q}  -> rank đúng: {rank}")
                for h in hits[:3]:
                    print(f"   {h.score:.4f} {h.ranks} {h.chunk['id']} | {h.chunk['text'].splitlines()[0][:80]}")
        n = len(CASES)
        print(f"{label:16s} Hit@{a.k} = {hit / n:.2f}  MRR = {rr / n:.2f}" + (f"   trượt: {misses}" if misses else ""))


if __name__ == "__main__":
    main()
