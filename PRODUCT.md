# Product brief — book-data-api

## Job to be done

ให้ผู้ใช้หรือโปรแกรมอื่นอ่าน resource ที่มี schema และ lineage ชัดเจนได้จาก
endpoint เดียว โดยรู้ได้ว่าข้อมูลมาจาก object ใดและผ่านการตรวจสอบแล้วหรือไม่

## Vertical slice

`read-one-versioned-resource`

ผู้ใช้สามารถตรวจ health, ดู metadata, list แบบ filter/pagination และอ่าน
resource ตาม id ได้จากข้อมูล fixture ที่มี manifest กำกับ

## Acceptance criteria

| พื้นที่ | เกณฑ์ยอมรับ | หลักฐาน local |
| --- | --- | --- |
| Contract | ทุก record เป็น `resource.v1` และ response มี `data_status` | `src/book_data_api/schema.py`, tests |
| Lake-first | landing/bronze/manifest ระบุ object และ digest | `data/`, `src/book_data_api/store.py` |
| Access boundary | health public, data endpoints ต้อง Bearer token เมื่อ serve | `src/book_data_api/api.py`, CLI |
| Read-only | POST/PUT/PATCH/DELETE ไม่ mutate และตอบ `405` | API tests |
| Resilience | digest, schema, count และ source/bronze equality fail closed | store tests |
| Usability | CLI validate/metadata/records และ HTTP server รันด้วย stdlib | `README.md`, Makefile |

## Non-goals ของ baseline

- ไม่เชื่อมต่อ remote storage, database หรือ external API
- ไม่เก็บ credential จริง
- ไม่รองรับ write API, tenant isolation หรือ production deployment
- ไม่อ้างว่า fixture นี้เป็น production data หรือ operational SLO evidence

