# Local baseline evidence

สถานะ: `verified-local`

## Scope

หลักฐานนี้ครอบคลุมเฉพาะ local scaffold ของ `book-data-api` และ vertical slice
`read-one-versioned-resource` ไม่ใช่ production, remote, deployment หรือ
security certification

## Commands to run

```bash
make test
make check
make demo
```

## Expected evidence

- unit/in-process tests ตรวจ schema, manifest digest, source/bronze equality,
  auth, read-only method, pagination และ rate limit
- HTTP smoke test อ่าน `resource-002` ผ่าน ephemeral local port
- `validate` คืน `status: ok` และ lineage ของ bronze fixture
- `demo` คืน metadata และ record ที่ filter ด้วย `developer-tools`

## Observed result

- `make test`: ผ่าน 21 tests (2026-09-30; เพิ่ม lineage tamper, path traversal, HEAD,
  query validation, CLI และ rate-limit sweep)
- `make check`: compile และ `validate` ผ่าน
- `make demo`: คืน metadata และ `resource-001` ตาม filter ที่กำหนด
- HTTP smoke test: อ่าน `resource-002` ได้ด้วย status `200`

## Reproducibility boundary

ข้อมูลทั้งหมดเป็น sanitized fixture ใน repository ย่อยนี้ ไม่มี credential,
external network หรือ write side effect ระหว่างการตรวจสอบ
