# Upgrade plan — book-data-api

คะแนน: 6.5/10 -> 8/10 — เดิมมี test ดีแต่ไม่มี CI, test แก้ไฟล์ fixture จริงระหว่างรัน,
`HEAD` ถูกตอบ 405 และ rate limiter เก็บ client id ไม่จำกัด

## Backlog

- P0: ยืนยันว่า GitHub Actions CI ผ่านใน push แรก และตั้งเป็น required check
- P1: เพิ่ม structured access log (method, path, status, latency) โดยไม่ log token/header
- P1: ตัดสินใจว่าจะเป็น API กลางของ `book-*-data` หรือไม่; ถ้าใช่ ให้เพิ่ม adapter
  อ่าน envelope ของ product เหล่านั้นแบบ read-only แยกตาม `schema_version`
- P2: เพิ่ม `ETag` จาก `bronze_sha256` เพื่อให้ consumer cache ได้
- P2: รองรับ `OPTIONS`/CORS แบบ allowlist ถ้ามี browser consumer

## Done in this pass

- เพิ่ม `.github/workflows/ci.yml`: ruff, pytest, `make check`, `make demo` และตรวจว่า
  `data/` ไม่ถูกแก้ (จำลองขั้นตอนใน venv Python 3.12 สะอาดแล้ว)
- `HEAD` ทำงานเหมือน `GET` (ไม่มี body); 405 ส่ง `Allow: GET, HEAD`
- rate limiter ล้าง client ที่ไม่ active เมื่อติดตามเกิน 1024 client และรายงาน
  `window_seconds` จากค่าจริง
- test ที่ทำ fixture เสียหายใช้สำเนาใน temp dir; เพิ่ม test digest/path traversal/
  source-bronze mismatch/missing manifest, auth ผิด, query validation, pagination,
  route 404, HEAD/POST ผ่าน HTTP จริง และ CLI (`serve` ไม่มี token, `records`, `validate`)
- เพิ่ม ruff config และ dev extras; ลบ import ที่ไม่ใช้
