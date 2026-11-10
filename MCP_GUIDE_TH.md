# MCP สำหรับ Voicer Studio

ปรับปรุง 2026-11-11

## เริ่มใช้งาน

1. เปิดโปรเจกต์หรือ import ZIP แพ็กเสียงที่ต้องการแก้ไข
2. เปิด **Edit → AI / MCP Connection** แล้วกด **เตรียมระบบ MCP** ครั้งแรก
   โปรแกรมสร้าง `.venv-mcp` แยกจาก environment ประมวลผล AI และติดตั้งเฉพาะ
   `requirements-mcp.txt` ต้องใช้อินเทอร์เน็ตตอนติดตั้ง แต่ไม่ดาวน์โหลดโมเดล AI
   หาก Python เดิมเสียหรือเป็น launcher ให้เลือก Python 3.10–3.13 ในขั้นสูงก่อน
3. เปิด MCP แล้วเลือก **อ่านข้อมูล** หรือ **แก้บทพูด** หรือเลือกสิทธิ์รายข้อในขั้นสูง
   การเลือก preset ยังไม่เปิดเผยข้อมูล จนกดเชื่อมต่อเพื่อสร้างสิทธิ์ตามที่เลือก
4. เลือก **Codex, Claude Desktop, Claude Code, Cursor หรือ VS Code** แล้วกดเชื่อมต่อ
   ปุ่มเลือกแอปและเชื่อมต่ออยู่หน้าหลัก ไม่ต้องเปิดขั้นสูง
   โปรแกรมตรวจ runtime และตั้งค่าใน background โดยรักษา config อื่นและนโยบายเดิม
   config JSON ที่ถูกแก้จะมี backup แรกชื่อ `*.voicer-studio.bak`
   หาก config มีนโยบายหรือ environment ที่แก้เอง โปรแกรมจะไม่เขียนทับ
   VS Code ที่ใช้ JSONC, named profile หรือ remote workspace ให้ใช้ config manual
5. เชื่อมต่อใหม่หรือเปิดแอป AI ใหม่ตามข้อความที่แสดง แล้วตรวจรายชื่อ AI ที่เชื่อมอยู่
   ข้อความ “บันทึก config แล้ว” ยังไม่ใช่หลักฐานว่า AI เชื่อมแล้ว
6. กด **ทดสอบการเชื่อมต่อ** เพื่อทดสอบ stdio initialize → tools/list → get_app_status จริง
   การทดสอบนี้ไม่อ่านบทพูดหรือสื่อ และยังแยกจากการเชื่อมต่อของแอป AI ที่เลือก
7. ให้ AI เรียก `get_app_status` และ `get_project_summary` ก่อนทำงาน
   เมื่อแก้ไข ให้ส่งคำขอหนึ่งงานและอ่าน `get_job_status` จนสำเร็จก่อนแก้รายการต่อไป

MCP ปิดทุกครั้งที่เริ่ม Voicer Studio และยังต้องอนุญาตสิทธิ์ของโปรเจกต์ใหม่เอง
แอปจำเฉพาะ public reference สำหรับ config เดิม แต่สร้าง credential ใหม่ใน OS store
หลังปิดแล้วเปิด MCP ใหม่ gateway เดิมอ่าน ticket ใหม่ได้โดยไม่ส่งคำสั่งเขียนซ้ำ
หากมีอีกหน้าต่างใช้งาน reference นั้นอยู่ แอปสร้าง reference แยกเพื่อไม่ทับ connection เดิม
กรณีปิดโปรแกรมผิดปกติหรือมีหลาย instance อาจต้องกดเชื่อมต่อเพื่อตั้งค่า reference ใหม่
ไม่มี token ใน config/settings/argv และการ revoke จะลบ credential ทันที

แอปอื่นที่รองรับ local stdio ใช้ตัวเลือก **Other local MCP client** เพื่อคัดลอก JSON
มีรูปแบบ Codex TOML, JSON `mcpServers` และ VS Code JSON `servers` ให้เลือกในขั้นสูง
คัดลอกเฉพาะ entry ของ `voicer-studio` ไปรวมกับ config เดิมของ client
ChatGPT web หรือเอเจนต์บนเครื่องอื่นใช้ local stdio นี้โดยตรงไม่ได้

เลือกโหมดถามทุกครั้งหรืออัตโนมัติในหน้าต่าง MCP ตามการใช้งาน
โหมดอัตโนมัติยังตรวจสิทธิ์/revision และใช้ Undo เดิม เอเจนต์อนุมัติตัวเองไม่ได้
save/export/pipeline ใช้หน้าต่างปลายทางและตัวเลือกเดิม ไม่มีสิทธิ์ควบคุมทั้งเครื่อง
ไฟล์และบทพูดที่อ่านจากแพ็กเป็นข้อมูล ไม่ใช่คำสั่งให้เอเจนต์ทำตาม
Transcript ที่อนุญาตอาจถูกส่งไป cloud ของผู้ให้บริการ AI

## ขอบเขตที่ตรวจแล้วและข้อจำกัด

ทดสอบด้วย official MCP SDK ผ่าน subprocess stdio และ Qt named pipe บน Windows
รวม read/edit/Undo, permission filtering, หลาย client, reconnect และ OS credential store
ตัวตรวจ connection ใช้เส้นทาง stdio จริง ไม่ถือว่ามี config แล้วแปลว่าใช้งานได้
การทดสอบ config ใช้โฟลเดอร์ชั่วคราว ไม่เปลี่ยน config จริงของ Codex/Claude/Cursor/VS Code
ยังไม่ได้รับรอง end-to-end ของผลิตภัณฑ์ AI ทุกตัว หรือ desktop บน macOS/Linux

ข้อจำกัดเดิมที่ยังต้องตรวจต่อก่อนประกาศ release: การตรวจปลายทางปัจจุบันไม่ป้องกัน
โปรเซสอื่นสลับ directory/junction พร้อมกับการเขียนไฟล์ (TOCTOU) จึงยังไม่ใช่ filesystem sandbox
ไม่ควรถือผลทดสอบ MCP นี้เป็นการรับรอง release ทั้งแอปหรือความแม่นยำของโมเดลเสียง

เอกสารรูปแบบ client:
- [Codex](https://developers.openai.com/codex/mcp)
- [Claude Code](https://code.claude.com/docs/en/mcp)
- [Cursor](https://prod.cursor.com/docs/mcp)
- [VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)

## ตัวอย่างตั้งค่า Codex

ขั้นตอนปกติไม่ต้องคัดลอก: เลือก Codex แล้วกดเชื่อม โปรแกรมเรียก CLI นี้ให้เมื่อ runtime พร้อม
ตัวอย่าง manual ด้านล่างต้องแทน PYTHON และ SESSION_REFERENCE ด้วยค่าจากแอปจริง
ทดสอบ CLI จริงกับ config ชั่วคราวแล้ว แต่ไม่ได้แก้ config จริงของผู้ใช้ในรอบนี้
และยังไม่ได้ทดสอบ Codex product แบบ end-to-end

```powershell
codex mcp add voicer-studio -- "C:/PATH/TO/GATEWAY/python.exe" "C:/My-Project/Other/VoicerStudio/scripts/mcp_server.py" --session SESSION_REFERENCE
codex mcp list
```

อ้างอิง syntax จากเอกสารทางการ:
https://learn.chatgpt.com/docs/extend/mcp?surface=cli

Claude Desktop มี setup อัตโนมัติสำหรับ Windows/macOS ที่ติดตั้งและเปิดแอปมาแล้ว
เก็บ backup config แรกไว้ในโฟลเดอร์ Claude และรักษา settings/server อื่น
ทดสอบ merge config ด้วย fixture ไม่ใช่การรับรอง native Claude Desktop end-to-end
Claude Code/AI client อื่นต้องเพิ่ม local stdio server ด้วย syntax ของผลิตภัณฑ์นั้น
ยังไม่ได้รับรอง compatibility ของผลิตภัณฑ์เหล่านั้น
ChatGPT web ไม่อ่าน local Codex config; gateway นี้ยังไม่มี remote transport

## หลังเชื่อมแล้ว สั่ง AI แบบไหน

> ใช้ MCP voicer-studio ตรวจสถานะแอปและสรุป project ที่ฉันอนุญาต
> อ่านบทพูดไม่เกิน 20 คลิป เสนอแก้ caption ของคลิปที่จำเป็น
> ใช้ revision ล่าสุด และรอฉันอนุมัติ diff ใน Voicer Studio ก่อนเปลี่ยนข้อมูล
> ห้ามอ่านไฟล์ด้วย shell แทน MCP และห้ามเริ่ม save/export/pipeline

เลือกนโยบายอนุมัติในหน้าต่าง MCP ก่อนสร้างการเชื่อมต่อ:

- ถามทุกครั้ง (ค่าเริ่มต้น): ดู diff แล้วกดอนุมัติในแอป
- อัตโนมัติในครั้งนี้: คำขอที่มีสิทธิ์ของ connection นั้นทำงานโดยไม่ต้องกดอนุมัติ MCP ซ้ำ
- อัตโนมัติเสมอ: เช่นเดียวกัน แต่จำตัวเลือกไว้สำหรับการสร้าง connection ครั้งต่อไป

สองโหมดอัตโนมัติต้องยืนยันความเสี่ยงก่อนเลือก ไม่เปิดสิทธิ์เพิ่มให้เอง
bridge ยังปิดทุกครั้งที่เปิดแอป และต้องสร้าง connection ใหม่หลัง restart/เปลี่ยน project
เปลี่ยนนโยบายได้ในหน้าต่าง MCP; เปลี่ยนกลับเป็นถามทุกครั้งหรือปิด MCP
จะหยุดคำขออัตโนมัติที่ยังไม่เริ่ม งานที่เริ่มแล้วต้องใช้ Cancel
AI ไม่มี tool เปลี่ยนนโยบายหรืออนุมัติตัวเอง และต้องอ่าน job status เพื่อยืนยันผล
ทุกโหมดยังตรวจ scope/revision/busy และใช้ Undo เดิม
save/export/pipeline ยังมีหน้าต่างเลือกปลายทาง/options/overwrite/repair/model downloads เดิม
จึงยังไม่ใช่โหมดทำทุกฟังก์ชันโดยไม่มีหน้าต่างยืนยัน และไม่มีเครื่องมือควบคุมทั้งเครื่อง

มีปุ่มอนุมัติคำขอที่รออยู่ทั้งหมดครั้งเดียว พร้อมหน้าต่างรวม diff ให้ตรวจและยกเลิกได้
ไม่อนุมัติคำขอในอนาคต ไม่ข้ามสิทธิ์/expiry/revision และไม่ใช่ atomic batch
หากรายการแรกแก้ project แล้ว revision เปลี่ยน รายการถัดไปที่ใช้ revision เก่าจะถูกปฏิเสธ
ให้ AI อ่านสถานะล่าสุดแล้วเสนอใหม่ งานหนักยังใช้หน้าต่างยืนยันเดิม
Undo/Redo ใช้ workflow เดิม เมื่อเสร็จให้ปิด MCP เพื่อ revoke connections ทั้งหมด
Transcript ที่อนุญาตอาจถูกส่งไป cloud ของผู้ให้บริการ AI แม้ Voicer Studio ทำงาน local

การสั่งเพียง “ต่อ MCP กับ Voicer Studio” ใช้ได้หลัง client มี config และแอปอนุญาตแล้ว
หากยังไม่ setup AI ต้องมีเครื่องมือและสิทธิ์แก้ config บนเครื่องจึงจะช่วยตั้งค่าให้ได้
ไม่สามารถให้คำสั่งแชตเดียวเพิ่มความสามารถ MCP ให้ AI ที่ไม่รองรับได้

## คำสั่งแก้คลิปและวิเคราะห์เสียงที่เพิ่ม

มี 25 tools เมื่ออนุญาตทุก scope; รายการที่ AI เห็นถูกกรองตามสิทธิ์จริง

- ตัวละคร: create_character, rename_character, remove_character, clear_reference_voice
- เสียงอ้างอิง: enroll_reference_voice จากคลิปที่รู้ตัวละครแน่นอน ยาวอย่างน้อย 1 วินาที
- วิเคราะห์: analyze_clip_voice คืน candidate/score/needs_review; apply_confident_voice_match
  ใช้ได้เฉพาะผลของ connection เดียวกันและ revision ปัจจุบันที่ไม่ต้องตรวจเพิ่ม
- คลิป: create_clip, delete_clip, split_clip, merge_next_clip, set_clip_timing
- Assets/ประวัติ: regenerate_clip_audio, regenerate_clip_frame, undo_project, redo_project
- ใช้ร่วมกับ 9 tools เดิมสำหรับสถานะ/สรุป/บทพูด/เสนอ caption-speaker/save/export/pipeline/job/cancel

การจับคู่ใช้ acoustic features 52 ค่าในเครื่องและ FFmpeg เดิม ไม่ส่ง audio ไป cloud
score เป็น similarity ไม่ใช่ความน่าจะเป็น; คะแนนต่ำ/ตัวเลือกใกล้กัน/เสียงสั้น/มี reference
เพียงตัวละครเดียวจะให้ตรวจเอง ไม่ฝืนเลือก ยังไม่ได้วัด accuracy ด้วยเสียงคนจริง
การลงทะเบียน reference เป็น worker และ Undo ได้; embedding ไม่ถูกส่งคืน MCP
delete_clip เป็นการลบเชิงข้อมูล ไม่ลบไฟล์ต้นฉบับ; ลบตัวละครที่ยังถูกใช้ไม่ได้
แก้เวลาแล้ว audio/frame จะถูก invalidate ต้อง regenerate หรือ repair ตอน export
regenerate_clip_audio คือการตัดเสียงเดิมใหม่ ไม่ใช่เปลี่ยนเสียงเป็นคนอื่นหรือ TTS
ยังไม่ได้เปิดทุกเมนู GUI เช่น import/path/settings หรือควบคุมทั้งเครื่องผ่าน MCP

ตัวอย่างสั่งหลังเชื่อม:

> อ่านสรุปและรายการคลิปล่าสุด ลงทะเบียนเสียงคลิปที่ฉันระบุให้ตัวละครที่ถูกต้อง
> วิเคราะห์คลิปเป้าหมายและรายงานคะแนน ถ้า needs_review เป็น true ให้หยุด ไม่เลือกแทนฉัน
> ถ้ามั่นใจและ revision ยังตรง จึงใช้ apply_confident_voice_match แล้วตรวจ job status
> แบ่งคลิปที่เวลาที่ฉันระบุ และใช้ Undo หากผลไม่ตรง ห้าม save/export หรือใช้ shell

## ผลทดลองก่อนหน้า 2026-10-08

เครื่อง Windows, Python 3.12.10; official SDK client และ Inspector CLI ผ่าน stdio
คำสั่ง: pytest tests/test_mcp_adapter.py -k "real_stdio or native_windows or inspector"
ผล: 4 passed, 8 deselected ใน 18.46 วินาที

- อ่านข้อมูลและตรวจ privacy/schema/protocol errors
- เสนอ caption, อนุมัติใน trusted test harness, retry/reconnect และ Undo ใน GUI logic
- public session reference ผ่าน Windows Credential Manager จริง
- MCP Inspector CLI tools/list และ metadata tools/call จริง

รายงานรายกรณี: .temp/mcp-live-trial-2026-10-08.xml
ใช้ข้อมูลสังเคราะห์; GUI tests เป็น offscreen ไม่ใช่การคลิก desktop โดยมนุษย์
การอนุมัติใน harness ไม่ใช่ AI อนุมัติตัวเองผ่าน MCP

พยายามเปิด source app ด้วย native Windows Qt ผ่าน pythonw process แล้ว
process 38364 ยังทำงานและ Responding=True แต่ MainWindowTitle ว่างตอนตรวจ
จึงยังไม่ยืนยันว่าหน้าต่างหลักแสดงหรือพร้อมใช้งาน
Computer Use เริ่มไม่ได้หลังลองสองครั้ง: sandbox helper apply deny-read ACLs ล้มเหลว
ไม่ได้คลิกเปิด bridge/อนุญาตข้อมูลจริงหรือ register client จริงในรอบนี้
ไม่ได้เปลี่ยน client config ของผู้ใช้, commit/push/PR หรือ release

## ผลตรวจ UI ใหม่ 2026-10-09

Regression suite: 230 passed, 1 skipped (optional SDK ไม่ได้ติดตั้งใน app environment)
ทวน official SDK stdio read-only และ propose/approve/reconnect/Undo: 2 passed, 10 deselected
ทดสอบ Copy จากรายการว่างก่อนแก้พบว่าไม่แจ้งอะไร; หลังแก้มีข้อความแนะนำและ config preview
ทดสอบ quick connect/clipboard/Codex TOML และ approve all รวม expiry/tamper/revoke/stale revision
Render layout แบบ offscreen ด้วยฟอนต์ Windows ที่โหลดใน harness: 790×700
ผลนี้ไม่ใช่การรับรอง desktop smoke หรือเชื่อม Codex product จริง
แอปที่เปิดอยู่ก่อนแก้ต้องปิดอย่างปลอดภัยแล้วเปิดใหม่จึงเห็น UI ใหม่

## ผลเพิ่มคำสั่งแก้คลิป/เสียง 2026-10-09

Windows / Python 3.12; ข้อมูลสังเคราะห์; GUI harness offscreen ไม่ใช่ desktop smoke

- Regression แอปทั้งหมด: 300 passed, 1 skipped ใน 301.85 วินาที
  (optional SDK ไม่มีใน app environment); .temp/mcp-expanded-regression-2026-10-09.xml
- Unit/GUI logic แก้คลิป ตัวละคร Undo/Redo เสียงและ setup: 36 passed ใน 50.50 วินาที
  รายงาน .temp/mcp-edit-voice-unit-2026-10-09.xml
- Official SDK + subprocess stdio + Inspector CLI: 16 passed ใน 93.74 วินาที
  รายงาน .temp/mcp-expanded-sdk-2026-10-09.xml
- ทวนเสียงและการแก้โปรเจกต์ผ่าน stdio หลังเสริม worker settlement guard:
  2 passed, 14 deselected ใน 23.07 วินาที; .temp/mcp-edit-voice-stdio-2026-10-09.xml
- ทวน command/UI/เสียง หลังแก้ metadata-only connection ให้จำ Always โดยไม่เพิ่มสิทธิ์:
  83 passed ใน 57.24 วินาที; .temp/mcp-final-guards-2026-10-09.xml
  ชุด regression 300 กรณีด้านบนรันก่อนการแก้ guard/Always สุดท้าย ซึ่งตรวจแยกตามรายการนี้

ทดสอบ enroll และ analyze ผ่าน FFmpeg จริงกับเสียง tone สังเคราะห์ ไม่ใช่ benchmark
ความแม่นยำเสียงคนจริง; ผล ambiguous ต้องตรวจและไม่เปลี่ยน assignment
ทดสอบ split/merge/timing/create/delete/character/Undo/Redo ผ่าน MCP SDK จริง
และทดสอบ cancel/stale/error กับ worker รวมช่วง thread จบแต่ GUI ยังไม่รับผล
ทดสอบ Codex CLI add/get จริงใน CODEX_HOME ชั่วคราว: อัปเดต session ได้
เก็บค่าที่ไม่เกี่ยวข้องไว้และปฏิเสธ entry ที่มี custom approval policy
ไม่ได้เขียน config จริงของผู้ใช้หรือเชื่อมจากแชต Codex จริงในรอบนี้
ไม่มี commit/push/PR/release หรือดาวน์โหลดโมเดล

## ผลปรับหน้าเชื่อมต่อและชื่อแอป 2026-10-09

Flow หลักเป็นเปิด MCP → เลือกแอป/สิทธิ์ → กดเชื่อมด้านนอก Advanced
Codex ค้น bundled CLI บน Windows ได้แม้ PATH ไม่มี; Claude Desktop merge config
พร้อม backup เดิม; manual client คัดลอก config จากปุ่มหลักได้
ชื่อหน้าต่าง/แถบเวอร์ชัน/About/setup และ source metadata ใช้ Voicer Studio
ยังเก็บชื่อเกม/รูปแบบ pack The Choice Voicer และข้อความลิขสิทธิ์เดิม

- ทำ regression ปัญหาเดิมก่อนแก้: 3 failed; หลังแก้ targeted flow/branding: 4 passed
- UI/setup รวม worker Qt จริงและปิด panel ระหว่าง setup: 54 passed ใน 58.65 วินาที
  .temp/mcp-connect-ui-2026-10-09.xml
- Regression แอปทั้งชุด: 310 passed, 1 skipped ใน 219.44 วินาที
  .temp/mcp-connect-brand-regression-2026-10-09.xml
  ชุดนี้รันก่อนเพิ่ม worker/manual regression อีก 3 กรณี ซึ่งรวมอยู่ใน 54 กรณีด้านบน
- ทวน setup หลังทำ Windows discovery test ให้จำลอง platform บน OS อื่นได้: 9 passed
- compileall, JSON locale/branding validation และ git diff --check ผ่าน

ทดสอบ Codex CLI จริงเฉพาะ config ชั่วคราว ไม่แก้ config จริงของผู้ใช้ในรอบนี้
Claude เป็น config fixture; GUI offscreen ไม่ใช่ native desktop/client end-to-end
ไม่ได้ rebuild VoicerStudio.exe, push หรือ release ต้องปิดแอปอย่างปลอดภัยและเปิดใหม่
เพื่อให้ GUI source โหลดการเปลี่ยนแปลงนี้

อ้างอิง setup: [OpenAI Docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
และ [MCP Python SDK — real host](https://py.sdk.modelcontextprotocol.io/get-started/real-host/)

## ผลปรับเปิด MCP และสถานะ live 2026-10-09

ติกเปิดเริ่ม local bridge ทันที ไม่ต้อง Start/Copy; config/client chooser อยู่ในขั้นสูง
หน้าหลักแสดงชื่อ/version/protocol จาก client พร้อมจำนวน gateway ที่เชื่อมค้างอยู่
จำกัด presence ไม่เกิน 4 ตัวเพื่อเหลือช่องสำหรับคำขอ ตรวจ credential/scope/rate limit
ชื่อเป็นข้อมูลที่ client รายงาน ไม่ใช่หลักฐานยืนยันตัวตน และไม่เปิด TCP/HTTP/LAN

- UI/IPC offscreen: 72 passed ใน 76.01 วินาที (.temp/mcp-live-controls-2026-10-09.xml)
- Official SDK/stdio subprocess: 15 passed, 1 skipped ใน 52.13 วินาที
  (.temp/mcp-live-presence-sdk-2026-10-09.xml); test Inspector ข้ามเพราะไม่ได้ตั้ง entry
- เพิ่ม client SDK สังเคราะห์สอง process: 1 passed ใน 9.39 วินาที
  (.temp/mcp-two-live-clients-2026-10-09.xml); เห็นชื่อและจำนวน 2 → 1 → 0
- ทวน SDK ทั้งชุดหลังครอบคลุม resources/prompts: 16 passed, 1 skipped ใน 55.28 วินาที
  (.temp/mcp-live-sdk-final-2026-10-09.xml); ทวน UI เปิด/ปิดหลังปรับข้อความ: 3 passed
- compileall และ git diff --check ผ่าน (มีคำเตือน CRLF)

ไม่ใช่การทดสอบ Codex/Claude Desktop จริง ไม่แก้ project หรือ config จริงของผู้ใช้
การลงทะเบียนหลาย AI client อัตโนมัติเมื่อติกเปิดยังไม่ได้ทำ: ระบบความปลอดภัยระงับ
การเปลี่ยน config แอปอื่นโดยไม่มีการระบุขอบเขต ต้องได้รับคำยืนยันก่อนดำเนินการ

## สิ่งที่ยังต้องทำก่อนรับรองใช้งาน

แก้ path-race, desktop smoke Windows/macOS/Linux, AI client จริงสองผลิตภัณฑ์,
CI ของ changes ปัจจุบัน, full media/performance และ desktop rollback validation
SDK/Inspector ที่ผ่านไม่เท่ากับรับรอง Codex/Claude หรือ AI ทุกตัว
