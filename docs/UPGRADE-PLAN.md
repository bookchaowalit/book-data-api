# Upgrade plan — book-data-api

คะแนน: 6.5/10 -> 8/10 (pass 1) -> 8/10 (pass 2) -> 8.5/10 (pass 3) — เดิมมี test ดีแต่ไม่มี CI, test แก้ไฟล์ fixture จริงระหว่างรัน,
`HEAD` ถูกตอบ 405 และ rate limiter เก็บ client id ไม่จำกัด

## Backlog

- P0: ยืนยันว่า GitHub Actions CI ผ่านใน push แรก และตั้งเป็น required check
- P1: ตัดสินใจว่าจะเป็น API กลางของ `book-*-data` หรือไม่; ถ้าใช่ ให้เพิ่ม adapter
  อ่าน envelope ของ product เหล่านั้นแบบ read-only แยกตาม `schema_version`
- P2: รองรับ `OPTIONS`/CORS แบบ allowlist ถ้ามี browser consumer

## Done in this pass (pass 1)

- เพิ่ม `.github/workflows/ci.yml`: ruff, pytest, `make check`, `make demo` และตรวจว่า
  `data/` ไม่ถูกแก้ (จำลองขั้นตอนใน venv Python 3.12 สะอาดแล้ว)
- `HEAD` ทำงานเหมือน `GET` (ไม่มี body); 405 ส่ง `Allow: GET, HEAD`
- rate limiter ล้าง client ที่ไม่ active เมื่อติดตามเกิน 1024 client และรายงาน
  `window_seconds` จากค่าจริง
- test ที่ทำ fixture เสียหายใช้สำเนาใน temp dir; เพิ่ม test digest/path traversal/
  source-bronze mismatch/missing manifest, auth ผิด, query validation, pagination,
  route 404, HEAD/POST ผ่าน HTTP จริง และ CLI (`serve` ไม่มี token, `records`, `validate`)
- เพิ่ม ruff config และ dev extras; ลบ import ที่ไม่ใช้

## Done in this pass (pass 2)

- เพิ่ม structured access log: logger `book_data_api.access` เขียน JSON หนึ่งบรรทัดต่อ
  request (`event`, `method`, `path` ไม่มี query และตัดที่ 256 ตัวอักษร, `status`,
  `latency_ms`, `bytes`) ก่อนส่ง response; ไม่ log header/token/query; `serve` เปิด
  log ระดับ INFO ลง stderr
- test ผ่าน HTTP จริง: 200/401/HEAD ถูก log ครบ, ไม่มี token ที่ถูกหรือผิด, ไม่มี query;
  และ test การตัด path ยาว (รันซ้ำ 5 รอบไม่ flaky)

## Done in this pass (pass 3)

- Conditional GET: response `/v1/*` สถานะ 200 มี strong `ETag` = sha256 (32 hex) ของ
  canonical JSON body ที่ส่งจริง (เปลี่ยนเมื่อ data, lineage หรือ API version เปลี่ยน —
  ละเอียดกว่าใช้ `bronze_sha256` อย่างเดียว) และ `Cache-Control: private, no-cache`
- `If-None-Match` (weak comparison ตาม RFC 9110, list, `*`, header ไม่สน case) ตอบ `304`
  ไม่มี body/Content-Type สำหรับ GET และ HEAD; ตรวจหลัง auth เท่านั้น จึงไม่มี 304 หรือ
  ETag ให้ request ที่ไม่มี token; `/healthz` และ error คง `no-store`
- test ระดับ service และ HTTP จริง (25 tests); ruff 0.15.8/0.16.9 ผ่าน; `data/` ไม่ถูกแก้
