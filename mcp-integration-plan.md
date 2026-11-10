# แผนเพิ่ม MCP ให้ Voicer Studio — 3 Sections

วันที่จัดทำ: 2026-10-08 | สถานะ: แผนเท่านั้น ยังไม่ได้พัฒนาหรือทดสอบ MCP

สมมติฐาน: เป้าหมายคือ Voicer Studio ใน repository นี้ ไม่ใช่ส่วนขยาย Microsoft Visual Studio; เริ่มเชื่อมเฉพาะเครื่องเดียว หากต้องการ IDE extension หรือ remote access ต้องปรับขอบเขตก่อนลงมือ

เป้าหมายคือให้ AI agent ที่รองรับ MCP อ่านข้อมูลที่ได้รับอนุญาต เสนอแก้บทพูด และสั่ง workflow เดิมได้ ไม่ใช่ให้ AI ทุกผลิตภัณฑ์เชื่อมได้โดยอัตโนมัติ ความเข้ากันได้ต้องระบุเป็นราย client/transport/protocol version ที่ทดสอบจริง

สถาปัตยกรรมที่เสนอ:

```text
MCP-compatible AI client
        │ stdio มาตรฐาน MCP
        ▼
scripts/mcp_server.py — adapter แยก process ไม่โหลดโมเดล AI
        │ local IPC + credential + สิทธิ์ของผู้ใช้
        ▼
gui/agent_bridge.py — รับคำสั่งและส่งเข้า Qt owner thread
        │ validation → permission → revision → confirmation
        ▼
คำสั่ง/สถานะที่ใช้ร่วมกับ GUI เดิม
        │
        ├─ แก้ข้อมูล → UndoManager + dirty/invalidation เดิม
        └─ งานหนัก → workers / pipeline / export เดิม → job status
```

ใช้ stdio สำหรับฝั่ง AI และเสนอ QLocalServer/QLocalSocket สำหรับ IPC ภายใน เพราะโครงการมี PySide6 อยู่แล้ว ต้องพิสูจน์การทำงานและการป้องกันข้อมูลบน Windows/macOS/Linux ก่อนยืนยันรายละเอียด ไม่เปิด TCP/HTTP/LAN ในระยะแรก ไม่สร้าง protocol MCP เอง และไม่เปิดโปรแกรม GUI อีก instance ทุกครั้งที่ AI เชื่อม

สิ่งที่พบจากโค้ดปัจจุบัน:

- `gui/main_window.py` เป็นเจ้าของสถานะ การแก้บทพูด Undo/Redo และการเปิด export; ยังไม่พบ MCP implementation จากการค้นใน `core/`, `gui/`, `scripts/`
- `core/models.py` มี `PipelineState`, `DialogueItem`, `UndoManager`; `DialogueItem.index` เป็นหมายเลขเรียงลำดับและเปลี่ยนหลัง `renumber()` จึงไม่ใช่รหัสถาวรที่ AI ใช้อ้างอิงโดยไม่มี revision ได้
- `core/pipeline.py` มี worker และสัญญาณ progress/error/cancel; worker เขียนสถานะระหว่างประมวลผล จึงไม่ควรให้ MCP อ่าน live mutable state แล้วถือว่าเป็น snapshot ที่สอดคล้องกัน
- `gui/export_dialog.py` มี `FullExportWorker` ที่ deepcopy สถานะ และตรวจด้วย `QualityChecker` ก่อน ZIP; ต้องใช้เส้นทางนี้ร่วมกับ GUI ไม่สร้าง exporter ใหม่
- `_is_busy()` ในหน้าต่างหลักตรวจ worker บางรายการ แต่ `FullExportWorker` อยู่ใน dialog จึงต้องตรวจ lifecycle ของ dialog และงานแก้ asset ด้วย ก่อนใช้ busy guard สำหรับ MCP
- `core/diagnostics.py` มีระบบ log และรายงานที่กรองข้อมูล; formatter ปัจจุบันรับ extra fields `operation`, `stage` หากต้องเพิ่ม correlation IDs ต้องเพิ่มเฉพาะ field ที่อนุญาต
- CI เดิมครอบคลุม Windows/macOS/Linux × Python 3.10/3.11/3.12; packaging และ updater มี allowlist ซึ่งยังไม่มี `requirements-mcp.txt`

ข้อกำหนดร่วม: feature ปิดเป็นค่าเริ่มต้น, ไม่เปลี่ยนรูปแบบ project/pack, ไม่ลดคุณภาพเสียง/ภาพ, ไม่ย้าย processing ไป cloud, ไม่โหลดโมเดลใน process ตัวเชื่อม, ไม่สร้าง shell/exec tool, ไม่ใช้ .bat เป็นทางเชื่อมใหม่ และไม่รับประกันว่าไม่มีบั๊กหรือ performance เท่าเดิมจนกว่าจะมีผลทดสอบจริง

## Section 1 — กลไกคำสั่งร่วม สถานะ และความปลอดภัยของข้อมูล

ผลลัพธ์ของส่วนนี้: GUI ยังทำงานเหมือนเดิม แต่มี interface ขนาดเล็กที่ทดสอบได้สำหรับ snapshot, การเสนอแก้ข้อมูล และ job lifecycle โดยยังไม่เปิด MCP ให้ภายนอก

### 1.1 เก็บ baseline และไล่เส้นทาง mutation

- ไฟล์: `gui/main_window.py`, `gui/clip_editor.py`, `core/models.py`, `core/pipeline.py`, `gui/export_dialog.py` และ tests ที่เกี่ยวข้อง
- ไล่ทุกเส้นทางที่แก้ caption/speaker/timing/split/merge/undo/redo/load และ callback ของ frame/audio regeneration; จดว่าเส้นทางใดเป็น synchronous หรือ worker
- เก็บผล tests เดิมและเวลา startup, idle CPU/RAM, UI latency และ pipeline/export ด้วย fixture เดิมบนเครื่องอ้างอิงก่อนแก้
- ตรวจ `_is_busy()` ร่วมกับ export dialog, modal dialog และ worker ที่ไม่ได้อยู่ในรายการเดิม ห้ามใช้เพียง flag เดียวโดยยังไม่ตรวจ lifecycle จริง
- เกณฑ์ผ่าน: มี baseline ที่ทำซ้ำได้ และรายชื่อจุดที่ต้องเพิ่ม revision/busy guard โดยไม่ refactor ทั้งหน้าต่าง
- ขึ้นกับ: ไม่มี; เป็นงานแรกก่อน 1.2–1.6

### 1.2 กำหนด interface และข้อมูลตอบกลับ

- ไฟล์ใหม่ที่เสนอ: `core/agent_commands.py`; ใช้ dataclass/ชนิดข้อมูลจาก stdlib และ model เดิมเท่าที่เหมาะสม
- Interface ภายในให้มีงานหลักเพียง `describe`, `snapshot`, `submit`, `job_status`, `cancel`; ชื่อเหล่านี้เป็นข้อเสนอ ไม่ใช่ฟังก์ชันที่มีอยู่แล้ว
- กำหนด command/result schema และ error code เช่น `APP_NOT_READY`, `NO_PROJECT`, `BUSY`, `PERMISSION_DENIED`, `REVISION_CONFLICT`, `INVALID_ARGUMENT`, `APPROVAL_REQUIRED`, `JOB_NOT_FOUND`
- Snapshot ให้มี `project_epoch`, `revision`, metadata ที่ได้รับอนุญาต และข้อมูลคลิปแบบแบ่งหน้า; ไม่ส่ง object Qt, ndarray, embedding, settings ทั้งก้อน หรือ raw file bytes
- เริ่มด้วย summary ที่ไม่มีเนื้อหาบทพูด; caption/speaker name/path/media เป็นข้อมูลผู้ใช้ ต้องผ่าน scope/consent แยกต่างหาก
- จำกัด page size, caption length, batch size และ message size; ตรวจ finite numbers และเวลา end > start ตามกฎเดิม
- เกณฑ์ผ่าน: tests ที่เรียก interface โดยไม่เปิด GUI ตรวจ valid/invalid input และ output ไม่รั่ว settings/token/voiceprint
- ขึ้นกับ: 1.1

### 1.3 ป้องกันการแก้คลิปผิดและข้อมูลเก่า

- ไฟล์: `gui/main_window.py`, `core/agent_commands.py`; หลีกเลี่ยงการเปลี่ยน `to_dict/from_dict` ของ project
- ใช้ `project_epoch + revision + clip reference` แบบ runtime; เปิด project ใหม่หรือ reload ต้องเปลี่ยน epoch และทำให้ reference เดิมใช้ไม่ได้
- ทุกคำสั่งแก้ข้อมูลต้องมี `expected_revision`;ตรวจอีกครั้งทันทีที่ลงมือบน Qt owner thread ไม่ใช่ตรวจเฉพาะตอนรับคำสั่ง
- Revision ต้องเพิ่มจาก GUI edits, Undo/Redo, split/merge, โหลด project และผล callback ที่เปลี่ยนข้อมูล ไม่ใช่เพิ่มเฉพาะการแก้ผ่าน MCP
- เมื่อ pipeline กำลังเขียน state ให้ตอบเฉพาะ progress snapshot ที่เผยแพร่ไว้ หรือ BUSY; ไม่ deepcopy live state โดยสมมติว่าการอ่านบน GUI thread ป้องกัน race กับ worker ได้
- เกณฑ์ผ่าน: snapshot เก่าหลัง GUI edit/split/undo ต้องถูกปฏิเสธ; AI สอง client แก้ revision เดียวกันได้สำเร็จเพียงคำสั่งแรก
- ขึ้นกับ: 1.2

### 1.4 ใช้คำสั่งแก้ข้อมูลร่วมกับ GUI เดิม

- ไฟล์: `gui/main_window.py`, `core/agent_commands.py`, `tests/test_agent_commands.py` (ใหม่)
- เริ่ม MVP ด้วยแก้ caption และเปลี่ยน speaker ของคลิปที่มีอยู่; split/merge/timing เพิ่มทีหลังเมื่อมี regression tests ครบ
- แยกเฉพาะ logic ที่จำเป็นจาก handler เดิมให้ GUI และ AI เรียก implementation เดียวกัน: validation → push undo → mutate → invalidate/dirty → refresh
- Batch ให้ prevalidate ทั้งชุดก่อนแก้ และเป็นหนึ่ง undo action; ถ้าทำ transaction/rollback ให้ถูกต้องไม่ได้ ให้ยังไม่เปิด batch
- ไม่ให้ AI แก้ `_state` โดยตรงหรือใช้ simulate mouse/keyboard แทนคำสั่งที่ตรวจสอบได้
- เกณฑ์ผ่าน: ผล GUI/MCP ตรงกัน; Undo/Redo, timestamps, speaker assignments, asset invalidation และ unsaved indicator เดิมไม่เปลี่ยน
- ขึ้นกับ: 1.3

### 1.5 เชื่อม job กับ worker เดิม

- ไฟล์: `gui/main_window.py`, `gui/export_dialog.py`, `core/pipeline.py`; เพิ่ม module แยกเฉพาะเมื่อ implementation ใหญ่จนอ่านไม่ง่าย
- Job มีสถานะ `awaiting_approval`, `running`, `cancelling`, `cancelled`, `failed`, `succeeded` และข้อมูล stage/progress/error ที่กรองแล้ว
- เริ่มงานหนักพร้อมกันได้หนึ่งงานที่เปลี่ยน project หรือใช้โมเดล; ไม่สร้าง worker/pipeline ใหม่ต่อ client และไม่เพิ่ม unbounded queue
- การสั่งงานคืน `job_id` เร็ว ไม่ค้าง tool call ตลอด transcription/export; รอผลด้วย status และเรียก cancel แบบ cooperative เดิม
- แยก worker finished-as-thread-exit ออกจากสำเร็จจริง: `FullExportWorker` เมื่อ cancel ไม่ emit error/success ตามปกติ ต้องมี terminal state ที่แน่นอนและไม่ค้าง running
- รักษา export snapshot, missing/corrupt asset repair, validation ก่อน ZIP และ success เฉพาะมีผลลัพธ์ที่ตรวจแล้ว; ผู้ใช้ยังต้องยืนยัน repair/overwrite ตาม policy
- การตัดการเชื่อมต่อไม่เริ่มงานซ้ำ; job ที่อนุมัติและเริ่มแล้วอยู่ให้ผู้ใช้ตรวจ/ยกเลิกในแอปได้ ไม่ force terminate thread
- เกณฑ์ผ่าน: pipeline/export ซ้อนถูกปฏิเสธ รวมกรณี dialog เปิดอยู่; cancel/failure ไม่แสดง succeeded; ทดสอบ missing image/audio และ FFmpeg failure เดิม
- ขึ้นกับ: 1.3–1.4

### 1.6 Proof of concept local IPC และสิทธิ์

- ไฟล์ใหม่ที่เสนอ: `gui/agent_bridge.py`; client adapter อยู่ `core/agent_client.py` ถ้าจำเป็นต้องแยกจาก entrypoint
- พิสูจน์ QLocalServer/QLocalSocket กับ Qt/PySide รุ่นขั้นต่ำที่โครงการรองรับ ไม่ใช้ API ใหม่ของ Qt โดยอาศัยเอกสาร latest อย่างเดียว
- Windows ใช้ named pipe, Unix ใช้ local socket; ให้ชื่อ instance ไม่ชนกัน กรณีหลายหน้าต่างต้องเลือก instance ชัดเจน ไม่เปิด GUI ใหม่อัตโนมัติ
- ตั้ง user restriction เมื่อ OS รองรับ และใช้ random per-session credential เสมอ; macOS ไม่ควรพึ่ง socket permission flag เพียงอย่างเดียว
- Credential/discovery ใช้ app-data runtime directory ที่จำกัดสิทธิ์; Unix 0700/0600, Windows user-only ACL ที่ตรวจจริง หรือใช้ keyring เดิม ถ้าเก็บอย่างปลอดภัยไม่ได้ให้ fail closed
- ไม่ใส่ credential ใน argv, repo, example settings, stdout หรือ diagnostics; token ใช้ยืนยันช่องทางภายใน ไม่ใช่แทน permission/approval ของคำสั่ง
- Parse ข้อความแบบมีขนาดสูงสุด/timeout; ตรวจ framing ที่ขาด/แตกหลาย packet/หลายข้อความ; auth ก่อนให้ snapshot และ dispatch
- ห้ามทำ blocking wait บน GUI thread; socket callback ต้องสั้น ส่งงานให้ owner thread/worker อย่างถูกต้อง ไม่แอบสร้าง Qt socket แล้วใช้ข้าม thread
- เกณฑ์ผ่าน: round trip บนทั้งสาม OS, wrong token/expired session/oversized request ถูกปฏิเสธ; shutdown ลบได้เฉพาะ endpoint ที่ instance นี้เป็นเจ้าของ
- ขึ้นกับ: 1.2–1.5; หาก PoC ยังไม่ผ่าน ให้หยุดการเปิด feature ภายนอก ไม่ fallback เป็น listener ที่ไม่มี auth

Demo จบ Section 1: ใช้ test harness ส่งคำสั่งที่ผ่าน validation ไปยังแอปตัวทดสอบ อ่าน snapshot และแก้ caption แล้ว Undo ได้; tests เดิมยังผ่าน และ GUI ปกติไม่เปิด listener

คำสั่งสำหรับมอบหมาย Section 1:

```text
พัฒนาเฉพาะ Section 1 ใน mcp-integration-plan.md หลังอ่าน AGENTS.md และไล่ callers จริง
เก็บ baseline ก่อนแก้ สร้าง interface/snapshot/revision/job ที่ใช้ logic GUI และ workers เดิม
เริ่ม caption/speaker; ไม่เปลี่ยน project serialization หรือ pack format ไม่สร้าง exporter/pipeline ซ้ำ
พิสูจน์ local IPC ที่ auth และจำกัดสิทธิ์ครบ Windows/macOS/Linux แต่ยังไม่เปิดให้ client ภายนอก
เพิ่ม regression tests สำหรับ stale revision, Undo/Redo, busy, export/cancel และ privacy
ทำทีละ commit-sized change รายงานไฟล์/ผลทดสอบจริง ไม่ทำ Section 2/3 ไม่ push/PR/release โดยอัตโนมัติ
```

## Section 2 — MCP adapter และชุดคำสั่งที่ AI เข้าใจง่าย

ผลลัพธ์ของส่วนนี้: MCP-compatible client ต่อ stdio gateway และทำงานกับ Voicer Studio instance ที่เปิดและอนุญาตไว้ได้ โดย SDK ไม่เข้าไปปะปนกับ startup/processing ปกติ

### 2.1 เลือกและแยก dependency ของ SDK

- ไฟล์ใหม่: `requirements-mcp.txt`, `scripts/mcp_server.py`; manifest หลักไม่จำเป็นต้องบังคับทุกคนติดตั้ง MCP
- ใช้ official Python MCP SDK และเลือก stable release ที่ตรวจบน Python 3.10/3.11/3.12 กับ dependencies เดิมแล้ว; pin รุ่นที่ทดสอบ ไม่เดาว่า latest API เหมือน tutorial เก่า
- ติดตั้ง optional feature โดยผู้ใช้เลือกอย่างชัดเจน ไม่ pip install/download โมเดลอัตโนมัติเมื่อเปิดแอปหรือ client เชื่อม
- Import SDK เฉพาะใน gateway; ห้าม import `main.py`, GUI widgets, pipeline, torch/Whisper/separator เพื่อเริ่ม gateway
- เกณฑ์ผ่าน: แอปเปิดได้เมื่อไม่มี SDK; gateway แจ้ง dependency missing แบบ actionable และไม่ทำลาย stdio; dependency resolution ไม่อัปเกรดแพ็กเกจ AI เดิมโดยไม่ตั้งใจ
- ขึ้นกับ: Section 1 ผ่าน รวม IPC PoC

### 2.2 เชื่อม transport และความเข้ากันได้ของ protocol

- ไฟล์: `scripts/mcp_server.py`, `core/agent_client.py` ตาม seam ที่ยืนยันจาก Section 1
- ให้ SDK จัดการ protocol lifecycle/version compatibility/tools/resources/errors ตามรุ่นที่เลือก; ไม่เขียน JSON-RPC MCP parser ใหม่
- stdio stdout มีเฉพาะข้อความ MCP; debug/progress logs ไป stderr แบบกรองหรือ log ของแอป ไม่ print ทั่วไปบน stdout
- ใช้ absolute interpreter/entrypoint ใน config ตัวอย่าง และ args array รองรับ path ไทย/ช่องว่าง; ไม่ผูกกับ cwd ของ IDE และไม่ใช้ .bat หรือ `shell=True`
- หากแอปปิด/feature ปิด/instance ไม่ตรง ให้แจ้ง error และวิธีแก้ ไม่ spawn GUI หรือเปิด project แทนโดยไม่ขอ
- กำหนด compatibility matrix ตาม SDK/protocol/client จริง; specs ต่างยุคอาจมี lifecycle ต่างกัน จึงไม่ hardcode initialize handshake แบบเดียวสำหรับทุก client
- เกณฑ์ผ่าน: protocol contract test, subprocess STDIO จริง, stderr ไม่ปน JSON, disconnect/reconnect/app restart ไม่ replay writes
- ขึ้นกับ: 2.1

### 2.3 Tools สำหรับ MVP

ชื่อทั้งหมดด้านล่างเป็นข้อเสนอ ยังไม่มีในโค้ด ต้องทำ JSON schemas และ description ที่ชัดเจน โดยระบุ prerequisite/permission/error/retry guidance

| Tool | งาน | สิทธิ์/ข้อจำกัด |
| --- | --- | --- |
| `get_app_status` | version, feature/busy/job capabilities | ไม่ส่ง token/settings/raw paths |
| `get_project_summary` | จำนวนคลิป/speakers/duration/revision | metadata ของ project ที่ user อนุญาต |
| `list_dialogues` | คลิปแบบ pagination; caption เมื่ออนุญาต | `read_project` + `read_transcript` แยกกัน |
| `propose_dialogue_edits` | เสนอแก้ caption/speaker พร้อม diff | ยังไม่ mutate; ต้องมี expected revision |
| `request_save_project` | เสนอ save ตาม workflow เดิม | สิทธิ์ write + ยืนยัน destination/overwrite |
| `request_pipeline` | เสนอเริ่มขั้นตอนที่รองรับ | อนุมัติแผน/options ก่อนใช้ทรัพยากร/ดาวน์โหลด |
| `request_export` | เสนอ export และ repair ที่จำเป็น | ยืนยัน output/repair; validator เดิม |
| `get_job_status` | status/stage/progress/error | เฉพาะ job ที่ client มีสิทธิ์ |
| `cancel_job` | ขอยกเลิกงานของ client | cooperative cancel; ไม่ cancel งานคนอื่น |

- การ approve ทำใน GUI ที่เชื่อถือได้ ไม่เพิ่ม tool `approve=true` ให้ agent อนุมัติตัวเอง
- เปิดทีละกลุ่ม: read-only ก่อน → proposed edits → save/export → pipeline; client ไม่ควรเห็นหรือเรียกสิทธิ์ที่ยังไม่เปิด
- User-triggered validation ที่อ่านไฟล์/decode/run FFmpeg ให้เป็น job ไม่อ้างว่า read-only แปลว่ารวดเร็ว; ไม่รัน `check_all` หนักใน GUI callback
- split/merge/timing, raw media access และเปิด arbitrary project/path ไม่ใช่ MVP; เพิ่มหลังมี consent/workspace policy และ regression tests เฉพาะ
- เกณฑ์ผ่าน: ทุก tool มี schema, negative test และ permission test; tools/call ข้ามชื่อหรือ scope ที่ไม่ได้อนุญาตทำไม่ได้แม้ส่ง request เอง
- ขึ้นกับ: 2.2 และ command/job ใน Section 1

### 2.4 Resources และ prompts ที่ไม่ทำให้ข้อมูลหลุด

- ไฟล์: `scripts/mcp_server.py`, tests ของ adapter
- เริ่ม resource `voicer://app/capabilities` และ summary ของ project ที่อนุญาต; descriptions/resource listing ต้องไม่เผยเนื้อหา/ชื่อไฟล์ที่ยังไม่ผ่าน consent
- ถ้า client ไม่รองรับ resource/prompt ให้ยังใช้ tools หลักได้; ไม่ทำให้ optional protocol features เป็นเงื่อนไขบังคับ
- Prompt templates ที่มีประโยชน์: review captions, suggest speaker corrections, explain export failure; templates ต้องเรียก tool แบบ bounded และยืนยันก่อนแก้
- ข้อความ caption/metadata/error เป็นข้อมูลที่ไม่น่าเชื่อถือ ไม่ใช่ system instruction; prompt injection ใน project ต้องไม่ทำให้ permission/path validation ถูกข้าม
- ไม่ฝังภาพ/เสียง/base64 หรือ log report อัตโนมัติใน resource; external AI อาจส่งข้อมูลที่ MCP คืนไปยัง cloud ของผู้ให้บริการ แม้ server อยู่ local
- เกณฑ์ผ่าน: ปิด read_transcript แล้วทั้ง tools/resources/prompts ไม่คืน caption; prompt ที่มีคำสั่งหลอกไม่ข้าม approval ได้
- ขึ้นกับ: 2.3

### 2.5 Request identity, errors และการ reconnect

- ไฟล์: adapter, command module, `core/diagnostics.py` หากต้องเพิ่ม field
- ใช้ client session, request ID, job ID และ idempotency key สำหรับ writes; key เดิม+payload เดิมใน app session คืนผล/job เดิม ไม่เริ่มงานซ้ำ
- จำกัด cache/TTL; key เดิมแต่ payload ต่างกันต้อง error ไม่ถือว่าเป็นคำสั่งเดิม; หลัง app restart ไม่รับประกัน exactly-once และต้องอ่าน state ใหม่ก่อน resubmit
- ไม่ใช้ชื่อ client ที่ส่งมาเป็นหลักฐานยืนยัน identity; approval ผูกกับ session/project/revision/payload ที่แอปตรวจแล้ว
- แยก protocol malformed/unknown tool ออกจาก tool execution failure; business error ใช้ผล MCP ที่มี `isError` ตาม SDK/spec รุ่นที่รองรับ และระบุ recovery action
- Log เฉพาะ operation/stage/code/IDs/เวลา ไม่ dump arguments, token, captions, media หรือ full settings; report ใช้ diagnostics exporter เดิม
- Job completion/permission expiry หลัง disconnected ต้องตรวจสิทธิ์ใหม่เมื่อกลับมา และไม่ให้ client อื่น query ผลที่มีข้อมูลส่วนตัว
- เกณฑ์ผ่าน: timeout-after-submit + retry ไม่ export ซ้ำ, stale IDs ใช้ไม่ได้, malformed input ไม่ crash แอป, report ไม่มี secret ที่ใช้ใน fixtures
- ขึ้นกับ: 2.3–2.4

Demo จบ Section 2: เปิดแอปและเปิด bridge ใน test setup; client SDK/Inspector อ่าน summary → เสนอ caption → user อนุมัติใน harness → อ่าน job/result → Undo ใน GUI ได้; stdio gateway ไม่โหลดโมเดลหรือสร้างแอปซ้ำ

คำสั่งสำหรับมอบหมาย Section 2:

```text
พัฒนาเฉพาะ Section 2 หลัง Section 1 ผ่าน interface/IPC contract tests แล้ว
ใช้ official MCP Python SDK รุ่นที่ตรวจ compatibility จริง ทำ stdio gateway แยก process
reuse command interface/permission/job เดิม ไม่ import main.py หรือโมเดล AI ใน gateway
ทำ read-only tools ก่อน แล้ว proposed edits/save/export/pipeline ที่ต้องให้ผู้ใช้ยืนยันในแอป
เพิ่ม schema/resource privacy/idempotency/errors และ STDIO/reconnect integration tests
ห้ามสร้าง arbitrary shell/exec/file-read tool ห้ามเปิด LAN/HTTP ห้าม bypass export repair/validator
รายงาน client/protocol/OS ที่ทดสอบจริง ไม่กล่าวว่ารองรับ AI ทุกตัว ไม่ทำ UI/release แทน Section 3
```

## Section 3 — หน้าควบคุม สิทธิ์ การทดสอบข้าม OS และการส่งมอบ

ผลลัพธ์ของส่วนนี้: ผู้ใช้เปิด/ปิด MCP ได้ เข้าใจว่าจะเปิดเผยข้อมูลอะไร เห็นและควบคุมงานของ AI ได้ และมีหลักฐานว่า workflow เดิมยังใช้ได้ก่อนเปิด feature ใน release

### 3.1 เพิ่มหน้าควบคุมแบบ optional

- ไฟล์: `gui/main_window.py`, settings UI เดิมที่ตรวจพบตอนลงมือ, `config.py`, `settings.example.json`, `core/i18n.py`/`locales/`
- เพิ่มเมนู AI/MCP Connection ตามธีมและ icon เดิม ไม่ redesign หน้าหลัก; รองรับภาษาไทย/อังกฤษ
- เปิด/ปิด feature, instance ID, connected clients, capabilities/scopes, pending requests, jobs และปุ่ม revoke/cancel
- Default off; settings เก่าที่ไม่มี key ใหม่ต้องโหลดเหมือนเดิม; ไม่เก็บ ephemeral credential ลง settings.json
- Copy connection configuration ให้เฉพาะ path/interpreter/instance reference ที่ไม่เป็น secret; ตรวจ syntax กับแต่ละ client จริง ไม่สมมติว่า config ทุก AI ใช้ key เดียวกัน
- ปิด feature แล้วหยุด listener/revoke sessions/ยกเลิกคำขอที่ยังไม่อนุมัติ; งานที่เริ่มแล้วต้องมี policy ชัด ให้ user เลือกรอหรือ cooperative cancel ไม่ฆ่า thread หรือทำผลลัพธ์หายเงียบ ๆ
- เกณฑ์ผ่าน: missing SDK/offline/older settings เปิดแอปได้; toggle on/off หลายครั้งไม่ leak socket/thread และ user GUI actions ยังใช้ได้
- ขึ้นกับ: Sections 1–2

### 3.2 Approval และ path/data policy

- ไฟล์: bridge/UI, command validation; ไม่สร้าง generic permission framework หลายชั้น
- Permission levels: app metadata → selected project metadata → transcripts → proposed edits → save/export/pipeline; ไม่เปิด read_transcript หรือ raw media โดย default
- Show diff ก่อนแก้ caption/speaker และแสดง output/options/repair/model download ก่อนงานหนัก; เริ่มด้วยอนุมัติทีละครั้ง ไม่ให้ blanket approval ทุก command
- Approval มี expiry และผูกกับ session, project epoch, revision, command+arguments; ถ้าผู้ใช้แก้ project ระหว่างรอต้องเสนอใหม่
- ใช้ project/output ที่ผู้ใช้เลือกผ่าน UI; agent ส่ง destination reference ที่อนุญาต ไม่ใช่ arbitrary path ที่เข้าได้ทั้งเครื่อง
- ถ้ารับ path ต้อง canonicalize, ตรวจ root/extension/overwrite, symlink/junction/UNC/network path และตรวจใหม่ก่อน I/O; root check อย่างเดียวไม่แก้ symlink race ทั้งหมด ต้องเลือก safe-open/reject policy และทดสอบ
- Pending UI approval ไม่ให้ transport thread รอ modal แบบ deadlock: คืน pending request/job handle แล้วดูสถานะได้
- ไม่มีสิทธิ์ลบ source/model/cache, run shell, แก้ credentials หรือสั่ง update/release ผ่าน MCP รุ่นแรก
- การจำกัดใน MCP ไม่ใช่ sandbox ของ AI process ทั้งเครื่อง; หาก agent มี shell/filesystem tools ของตัวเอง permission ของแอปไม่สามารถควบคุมเครื่องมือเหล่านั้นแทนได้
- เกณฑ์ผ่าน: scope denied, approval expired/payload changed, overwrite denied, path traversal/symlink/junction และ malicious caption ถูกปฏิเสธโดยไม่มี side effect
- ขึ้นกับ: 3.1 และ policy ของ Section 1–2

### 3.3 ชุดทดสอบและ regression gates

- ไฟล์ใหม่ที่เสนอ: `tests/test_agent_commands.py`, `tests/test_agent_bridge.py`, `tests/test_mcp_adapter.py`; รวมไฟล์ได้หากเล็ก ไม่สร้าง test framework ใหม่
- Command tests: pagination, permission, bounds/NaN, revision, split-after-snapshot, GUI edit/undo, batch atomicity, missing project
- IPC/protocol tests: two clients, partial/invalid/large messages, wrong/expired credential, app not running, SDK missing, stdio purity, supported versions และ process restart
- Thread/lifecycle tests: main-thread mutations เท่านั้น, busy รวม export dialog, worker state consistency, disconnect ระหว่าง approval/export, cancel terminal state, ปิดแอปขณะงานค้าง และไม่ QThread destroyed while running
- Privacy tests: secrets/transcripts/embeddings/paths ที่ไม่อนุญาตไม่ออกผ่าน listing/error/resource/log/report; ไม่ใช้ข้อมูลจริงของผู้ใช้ใน fixtures
- Existing regressions ต้องยังผ่าน: project load/save, clip editor/Undo, speaker/timing, missing/corrupt export assets, FFmpeg error, pack layout, updater และ diagnostics
- เพิ่ม CI จาก `.github/workflows/tests.yml`: รักษา OS × Python เดิม และทดสอบสองโหมด ไม่มี SDK/feature off กับ SDK/feature on โดยไม่ลด coverage เดิม
- Integration กับ MCP Inspector และอย่างน้อยสอง client ที่ผู้ใช้ต้องการจริง; ทดสอบใน interpreter/cwd/path configuration ของ client ไม่ใช่เฉพาะ mock
- Offscreen tests ไม่แทน desktop smoke tests: ทดสอบจริง Windows/macOS/Linux เรื่อง dialog, permissions, IPC และ close/cancel ด้วย
- เกณฑ์ผ่าน: ไม่มี regression ที่ยังไม่อธิบายได้, ไม่ skip test เดิมเพื่อให้ feature ผ่าน, ระบุผลจริงของแต่ละ environment
- ขึ้นกับ: 3.1–3.2

### 3.4 Performance budgets และการตรวจประสิทธิภาพ

ตัวเลขต่อไปนี้เป็น budget เสนอสำหรับเครื่องอ้างอิง ไม่ใช่ผลวัดปัจจุบัน ต้องเก็บ baseline และทำซ้ำก่อนตกลง threshold สุดท้าย

- Feature off: ไม่ import SDK, ไม่เปิด listener, ไม่เพิ่ม polling timer หรือ process และไม่โหลดโมเดลเพิ่ม; startup/RAM/UI latency ต้องอยู่ในช่วงความแปรปรวน baseline
- Feature on idle: listener ทำงานแบบ event-driven, ไม่อ่าน project ทั้งก้อนซ้ำทุกวินาที; เริ่ม budget idle CPU <1% เฉลี่ย โดยระบุวิธี normalize จำนวน CPU cores
- Summary/page queries: p95 เป้าหมาย <200 ms สำหรับ fixture ที่กำหนดและ page size จำกัด โดยไม่ decode media; วัด GUI event-loop latency แยกจาก round-trip
- งาน pipeline/export เดิม: เวลา/RAM/VRAM เทียบ fixture/settings/device เดียวกัน; ถ้าช้าขึ้นเกินประมาณ 5% อย่างสม่ำเสมอให้ตรวจ bottleneck ไม่แก้ด้วยลดคุณภาพ
- จำกัดจำนวน clients/requests/pending approvals/job history/idempotency cache ให้ bounded; throttle progress/log notifications และใช้ polling แบบ backoff เมื่อ client ไม่รองรับ notification
- ไม่ serialize ภาพ/waveform/embedding ใน snapshot, ไม่ deepcopy state ทั้งก้อนทุก query; cache เฉพาะเมื่อวัดแล้วจำเป็น และ invalidate ด้วย revision
- เกณฑ์ผ่าน: มี raw benchmark results ก่อน/หลังแยก off/on; ไม่มี duplicate model loading, redraw storm หรือ memory growth หลัง reconnect/toggle ซ้ำ
- ขึ้นกับ: baseline 1.1 และ integration ที่ทำงานแล้ว

### 3.5 Packaging, updater และคู่มือใช้งาน

- ไฟล์: `scripts/package_release.py`, `scripts/update_installer.py`, `README.md`, คู่มือ MCP ที่เลือกตำแหน่งเมื่อ implement
- เพิ่ม optional manifest `requirements-mcp.txt` ใน packaging include paths และ updater allowlist อย่างเจาะจง; ไฟล์ภายใต้ core/gui/scripts ใช้กลไกเดิม ไม่สร้าง top-level runtime tree ใหม่โดยไม่จำเป็น
- ทดสอบ clean installation และ release ZIP ว่ามี gateway/manifest ครบ; checksum sidecar เดิมยังต้องมี และ updater ต้องไม่ลบ models/projects/settings/credentials ใน app-data
- แยกความหมาย cross-platform source/runtime support ออกจาก binary distribution: packager ปัจจุบันสร้าง win64 ไม่ได้หมายความว่ามี native installers ทั้งสาม OS แล้ว; ไม่เปลี่ยนแพ็กเกจ Windows ให้ macOS/Linux ใช้ผิดแพลตฟอร์ม
- คู่มือแต่ละ OS: optional dependency setup, เปิดแอป/เปิด MCP, เลือก instance, config แบบ argv, permissions, offline behavior, error codes และวิธีหยุด/revoke
- ใส่คำเตือนชัดว่า external AI provider อาจรับข้อมูล transcript เมื่ออนุญาต แม้ Voicer Studio ประมวลผล offline
- เกณฑ์ผ่าน: ติดตั้งจาก package จริงแล้ว client เชื่อมได้; upgrade preserving data ผ่าน; ไม่มี .bat ใหม่/secret/โมเดล/debug dump ใน release
- ขึ้นกับ: 3.3–3.4

### 3.6 เกณฑ์จบ การปล่อยใช้งาน และ rollback

- ลำดับทำงาน: Section 1 → Section 2 → Section 3; งานเอกสาร/fixtures อาจเตรียมแยกได้หลัง interface ตกลง แต่ไม่แก้ main_window.py พร้อมกันหลายงานโดยไม่มี coordination
- Demo สุดท้าย: user เปิด project เดิม → เปิด MCP → AI อ่านข้อมูลที่อนุญาต → เสนอ caption diff → user อนุมัติ → Undo/Redo ได้ → export ที่ขาดรูป → user อนุมัติ repair → ตรวจ pack และ import เข้า The Choice Voicer → cancel/revoke ได้โดยไม่ freeze
- ต้องมี test cases ของ failure ไม่ใช่เฉพาะ happy path; success UI/MCP/job ต้องตรงกัน และ log ช่วยไล่ request/job โดยไม่เผยเนื้อหาส่วนตัว
- หยุดส่งมอบหาก IPC permissions ไม่ผ่าน OS ใด, export regressions ล้ม, project เก่าเปิดไม่ได้, stale revision ยังแก้ผิดคลิปได้ หรือ performance เกิน budget โดยไม่มีคำอธิบาย
- Rollback ขั้นแรกปิด feature/revoke sessions โดยไม่เปลี่ยน project format; หลังยกเลิกหรือจบ workers อย่างปลอดภัยจึง rollback source/package ผ่าน workflow ปกติ ไม่ downgrade ขณะกำลังเขียนไฟล์
- การ rollback package ไม่ลบ project/media/settings/models; ทดสอบ behavior settings ใหม่กับเวอร์ชันก่อนหน้าที่ใช้เป็น rollback target
- เมื่อผู้ใช้อนุญาตรอบ implementation/release จึงค่อย commit/push dev → PR main → รอ CI/review → merge → package/checksum → release version ใหม่; แผนรอบนี้ไม่อนุญาตให้ดำเนินการเหล่านั้นโดยอัตโนมัติและยังไม่กำหนดหมายเลข release

คำสั่งสำหรับมอบหมาย Section 3:

```text
พัฒนา Section 3 หลัง Section 1/2 ผ่าน tests แล้ว เพิ่ม UI เปิด/ปิด MCP แบบ default off
ทำ scopes/consent/diff approval/revoke/job status ภาษาไทยและอังกฤษตามธีมเดิม
ทดสอบ legacy ไม่มี SDK และ optional MCP บน Windows/macOS/Linux × Python 3.10/3.11/3.12
เพิ่ม desktop smoke tests, export repair/import regressions, privacy/path/thread/cancel tests
วัด startup/idle/UI/pipeline/export ก่อนหลัง ห้ามลดคุณภาพเสียงภาพเพื่อให้ benchmark ผ่าน
ตรวจ packaging และ updater allowlist สำหรับ manifest/gateway และรักษาข้อมูลผู้ใช้
จัดทำคู่มือและหลักฐาน compatibility จริง; ไม่ release จน gates ผ่านและได้รับคำสั่งให้ส่งมอบ
```

เอกสารอ้างอิงสำหรับยืนยัน implementation ตอนลงมือ:

- [MCP transports และข้อกำหนด compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports): stdio เป็น transport มาตรฐาน; lifecycle ของ protocol รุ่นก่อนและรุ่นใหม่ต่างกัน ต้องใช้รุ่นที่ SDK/client รองรับจริง
- [Official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk): รองรับ Python 3.10+; ใช้ SDK แทน implementation protocol เอง และเลือก release ที่ทดสอบแล้ว
- [MCP tools/error/access-control requirements](https://modelcontextprotocol.io/specification/2026-07-28/server/tools): แยก protocol error กับ tool execution error และบังคับ validation/access control
- [Qt QLocalServer](https://doc.qt.io/qt-6/qlocalserver.html): socket permission behavior แตกต่างตาม OS โดยเฉพาะ macOS; ต้องตรวจ API กับ PySide6/Qt รุ่นที่ติดตั้งจริงและไม่พึ่ง permission flag อย่างเดียว

ข้อควรระวังที่ทบทวนหลังจัดแผน: การระบุชื่อ AI client ยังไม่ชัด จึงต้องเลือกสอง client จริงก่อนทดสอบ interoperability; หากคำตอบเปลี่ยนเป็น Visual Studio extension หรือ remote access ต้องปรับสถาปัตยกรรม ไม่ขยาย listener/สิทธิ์เอง การรับประกันไม่มีบั๊กหรือ performance เท่าเดิมทำไม่ได้จากเอกสาร ต้องผ่าน gates และรายงานข้อจำกัดจริง
