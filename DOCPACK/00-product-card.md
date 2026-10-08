---
title: Book Data API — Product Card
doc_id: CARD-book-data-api
doc_type: product-card
verdict: template
version: 0.1
date: 2026-10-08
status: ร่างเพื่อพิจารณา
owner: Product owner (Book Dev)
---

# Book Data API — Product Card

## 1. สรุปคุณค่าในหนึ่งประโยค

เป็นตัวอย่างอ้างอิงที่เล็กที่สุดของ `api-tool` ใน Software Program Factory — แสดงการเสิร์ฟข้อมูล `resource.v1` จาก fixture แบบ lake-first ที่ตรวจ manifest ทุกครั้ง

## 2. ปัญหาและผู้ใช้เป้าหมาย

- ปัญหา: ต้องการโครงเริ่มต้นที่พิสูจน์แล้วสำหรับ read-only data API (manifest, SHA-256, auth token, route access)
- ผู้ใช้: นักพัฒนา/agent ที่เริ่ม API ใหม่ใน portfolio — ไม่ใช่ผู้ใช้ปลายทาง

## 3. สิ่งที่ทำได้จริงตอนนี้

- `GET /v1/records` และ `/v1/records/{id}` ต้องใช้ token ที่สร้างตอน runtime (`BOOK_DATA_API_TOKEN`)
- ตรวจ SHA-256, จำนวน record และ parity ระหว่าง landing กับ bronze ทุกครั้งที่โหลด
- ข้อมูลเป็น fixture ใน `data/`; ไม่เรียก network; CI ตรวจว่า fixture ไม่ถูกแก้

## 4. หลักฐานสถานะ

| รายการ | ค่า (ตรวจจาก repository) |
|---|---|
| Stack | Python |
| Commits | 11 (แรก 2026-09-09 → ล่าสุด 2026-10-01) |
| Source | 8 ไฟล์ / 1,269 บรรทัด |
| Tests | 2 ไฟล์ |
| CI | 1 workflow |
| Deploy config | ไม่มี |
| Live URL | ไม่มี |
| README | 94 บรรทัด (`book-data-api`) |
| โครงสร้างซ้ำ (template family) | 2 repo ที่มี structure signature เดียวกัน |

มี structure signature เดียวกับ `book-grounded-ai-assistant` (reference app อีกตัว)

## 5. คุณค่าและจุดต่าง

- คุณค่าคือการเป็นแม่แบบที่ทดสอบแล้ว ลดเวลาเริ่ม API ใหม่
- ไม่มีมุมรายได้ทางตรง

## 6. ช่องว่างสำคัญ

- ไม่มีข้อมูลจริง ไม่มีผู้ใช้ ไม่มี deploy — ตั้งใจเป็นแบบนั้น
- ยังไม่มีหลักฐานว่า repo อื่นถูกสร้างจากแม่แบบนี้ **[ต้องยืนยัน]**

## 7. คำตัดสิน

**`template`** — เป็น reference/starter ไม่ใช่ผลิตภัณฑ์ — ห้ามอ้างเป็น product จะมีค่ามากขึ้นถ้าถูกใช้สร้าง data API จริงอย่างน้อยหนึ่งตัว (เช่น ชั้น API ของ discovery products)

## 8. ขั้นต่อไป

1. ติด label template ใน README/registry
2. ถ้า Software Program Factory ไม่ใช้แม่แบบนี้แล้ว ให้ archive

## การอนุมัติ

| บทบาท | สถานะ | วันที่ | ลงนาม |
|---|---|---|---|
| Product owner (Book Dev) | รอพิจารณา | — | ________ |

## แหล่งข้อมูล

- `README.md`
- `PRODUCT.md`
- `src/book_data_api/api.py`
- `data/manifests/resource_records.v1.manifest.json`
