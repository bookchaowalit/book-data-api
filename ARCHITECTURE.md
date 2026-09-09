# Architecture — book-data-api

## Flow

1. `data/landing/source_records.json` เป็น source snapshot ที่ทำให้ปลอดภัยและ
   ตรวจซ้ำได้
2. `data/bronze/resource_records.v1.json` เป็น durable local fixture ที่มี
   `schema_version` และ `dataset`
3. `data/manifests/resource_records.v1.manifest.json` เป็น lineage contract
   ที่ชี้ object ทั้งสองและเก็บ SHA-256 กับ `record_count`
4. `store.load_dataset()` ตรวจ path ให้อยู่ใน repository, digest, JSON, schema,
   count และ equality ก่อนคืน dataset แบบ read-only
5. `ApiService` ทำ auth, rate limit, pagination, error envelope และ response
   contract ก่อนส่งให้ `http.server`

## Boundaries

- storage เป็นไฟล์ local ที่ตั้งใจให้เป็น fixture evidence ไม่ใช่ remote lake
- API ไม่มี write path; method อื่นนอกจาก GET ถูกปฏิเสธ
- เมื่อกำหนด `BOOK_DATA_API_TOKEN` แล้ว endpoint ใต้ `/v1` ต้องใช้
  `Authorization: Bearer ...`; `/healthz` ไม่เปิด record data
- CLI server จะหยุดก่อน bind หากไม่มี token เว้นแต่ผู้ใช้ระบุ
  `--allow-unauthenticated-local`
- rate limit เป็น in-memory per-client guard สำหรับ baseline ไม่ใช่ distributed
  quota หรือ security perimeter
- ใช้ Python standard library เท่านั้น เพื่อลด dependency และให้การทดสอบ
  ทำซ้ำได้ใน environment นี้

## Failure and recovery

ถ้า object หาย, อ่านไม่ได้, path หลุดออกนอก repository, digest ไม่ตรง,
schema ไม่ตรง, id ซ้ำ หรือ source กับ bronze ไม่เท่ากัน `load_dataset()` จะ
โยน `DataContractError` และ CLI จะแสดง structured error โดยไม่เสิร์ฟข้อมูล

การกู้คืนใน baseline คือคืน fixture ที่ถูกต้องจาก version-controlled local
scaffold แล้วรัน `make test && make check` ใหม่ การแก้ไข fixture ต้องแก้
manifest digest ให้สอดคล้องในขั้นตอนที่ตรวจสอบได้; ไม่มี migration หรือ
in-place repair อัตโนมัติ

