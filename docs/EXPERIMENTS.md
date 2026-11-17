# Experiment log

Ghi lại mốc để lần sau quay lại không mất ngữ cảnh. Cập nhật mỗi lần đổi prompt hoặc rule.

## Trạng thái hiện tại (đóng băng)

- **Prompt v4** — `src/exhibit_validator/layers/llm_layer.py`, hàm `build_prompt`.
  Cache key = md5 của prompt đã render. Đổi prompt → cache tự vô hiệu; **revert prompt → dùng lại cache cũ, 0 token**.
- **Rule layer** — chỉ trả `wrong` khi: không có typecode bảo tàng hợp lệ **và** (typecode bị loại **hoặc** keyword bị loại).
  Typecode trộn (vừa allowed vừa hard) → để LLM quyết.
- **Decision** — chỉ `wrong` từ Rule mới bỏ qua LLM. Verdict LLM là cuối; tripwire chỉ gắn `tripwire_flag`.
- `errors → suspicious` không bao giờ tự thành `ok`.

## Kết quả đã có (đều là prompt v3)

| Tập | Rows | ok / wrong / abstain | ok recall | wrong recall | false OK | false WRONG | cost |
|---|---|---|---|---|---|---|---|
| `test_small_30` | 13 | 9 / 2 / 2 | 81.8% | 100% | 0 | 0 | 2 |
| `test_tianhe_300` | 268 | 218 / 36 / 14 | 94.2% | 73.2% | 4 | 6 | 72 |

Kappa 0.6061 (13 dòng) và 0.6915 (268 dòng). **v4 chưa được kiểm chứng.**

## v4 thay đổi gì

- typecode chỉ là gợi ý, không phải bằng chứng → sửa nhóm false OK kiểu `香云纱`.
- vị trí (mall / toà nhà / khu dân cư) và hậu tố `(…店)` **không** phải tín hiệu thương mại → sửa nhóm false WRONG kiểu `上海恋爱博物馆`.
- loại rõ: sảnh nội bộ (`局史馆`…), đơn vị nghiên cứu (`文物保护…中心`), tên thuần sản phẩm.

## Việc tiếp theo

Chạy **cùng prompt v4** trên dữ liệu **không dùng để tinh chỉnh**, đọc **false OK trước tiên**.

1. `data/raw/probe_30.json` — 30 dòng, ~30k token.
2. `data/raw/test_798_mixed.json` (14 dòng), `data/raw/test_national_museum.json` (66 dòng).
3. Chỉ khi 1–2 ổn mới chạy tập lớn.

## Ước lượng chi phí trước khi chạy (0 token)

```powershell
.\.venv\Scripts\python.exe -m exhibit_validator.cli <file> --objective "..." `
  --intent-path configs/intents/museum.yaml --output-path data/outputs/_estimate.json
.\.venv\Scripts\python.exe -c "import json,collections; d=json.load(open('data/outputs/_estimate.json',encoding='utf-8')); c=collections.Counter(r['source_layer'] for r in d['records']); print(c, 'LLM calls =', c['fallback'])"
```

## Nhiễu đã biết trong nhãn

- `gold_300.csv` khác `gold_tianhe_300.csv` ở 10 nhãn.
- `摩登博物馆` có 2 chi nhánh bị gán nhãn ngược nhau (`芮欧百货店` = ok, `上海陆家嘴中心店` = wrong).
- Vì vậy chênh lệch dưới ~4% trên 268 dòng **không có ý nghĩa thống kê**.
