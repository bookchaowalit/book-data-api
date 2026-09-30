# book-data-api

`book-data-api` คือ reference implementation ของ `api-tool` แบบเล็กที่สุดที่
พิสูจน์เส้นทาง `read-one-versioned-resource` ได้จริงในเครื่องเดียว

## Purpose

แอปนี้ให้บริการข้อมูล resource ที่ผ่าน contract `resource.v1` โดยอ่านจาก
fixture ที่แบ่งชั้นแบบ lake-first:

```text
data/landing/source_records.json
        │
        ├── data/manifests/resource_records.v1.manifest.json
        │
        ▼
data/bronze/resource_records.v1.json
        │
        ▼
GET /v1/records และ GET /v1/records/{id}
```

manifest จะตรวจ SHA-256, จำนวน record และความตรงกันระหว่าง source snapshot
กับ bronze object ทุกครั้งที่โหลด แอปไม่เขียนทับ fixture และไม่เรียก network
ภายนอก

## Run locally

จาก root ของ repository ย่อยนี้:

```bash
make test
make check
make demo
```

ตรวจแบบเดียวกับ CI (`.github/workflows/ci.yml`, Python 3.11/3.12):

```bash
python -m pip install "pytest>=7" "ruff>=0.5"
ruff check .
python -m pytest -q
make check && make demo
```

test ที่ทดสอบ fixture เสียหายจะคัดลอก `data/` ไปยัง temporary directory ก่อน
จึงไม่แก้ไฟล์ fixture จริง และ CI ตรวจซ้ำด้วย `git diff --exit-code -- data`

เปิด HTTP server โดยสร้าง token เฉพาะ runtime ใน shell:

```bash
export BOOK_DATA_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
PYTHONPATH=src python3 -m book_data_api.cli serve --port 8080
```

หรือใช้ `--allow-unauthenticated-local` ได้เฉพาะการทดลอง local ที่ไม่มี
credential; ตัวเลือกนี้ไม่ได้เปิดเป็นค่าเริ่มต้น

`serve` เขียน access log แบบ JSON หนึ่งบรรทัดต่อ request ลง stderr ผ่าน logger
`book_data_api.access` มีเฉพาะ `event`, `method`, `path` (ไม่มี query string,
ตัดที่ 256 ตัวอักษร), `status`, `latency_ms` และ `bytes` โดยไม่ log header,
token หรือ query

ตัวอย่างการอ่าน:

```bash
curl http://127.0.0.1:8080/healthz
curl -H "Authorization: Bearer $BOOK_DATA_API_TOKEN" \
  'http://127.0.0.1:8080/v1/records?category=developer-tools&limit=10'
curl -H "Authorization: Bearer $BOOK_DATA_API_TOKEN" \
  http://127.0.0.1:8080/v1/records/resource-001
```

## Contract boundary

- `GET /healthz` เป็น public health check ที่ไม่เปิดข้อมูล record
- `GET /v1/metadata` แสดง schema, count และ lineage
- `GET /v1/records` รองรับ `category`, `limit` และ `offset`
- `GET /v1/records/{id}` อ่าน record เดียวตาม id
- รองรับ `HEAD` เหมือน `GET` แต่ไม่ส่ง body; method ที่เปลี่ยนข้อมูลตอบ `405` และ
  `Allow: GET, HEAD`
- rate limit ต่อ client อยู่ในหน่วยความจำ และล้าง client ที่ไม่ active แล้วอัตโนมัติ
- ข้อมูลที่ผิด contract หรือ digest ไม่ตรง manifest จะ fail closed
- token ไม่อยู่ใน source, fixture หรือ manifest และไม่มี dependency ภายนอก

นี่เป็น local baseline เพื่อใช้ตรวจ role/step และ acceptance ของ reference app
เท่านั้น ยังไม่ใช่ production API, remote lake, multi-tenant service หรือ
deployment evidence

