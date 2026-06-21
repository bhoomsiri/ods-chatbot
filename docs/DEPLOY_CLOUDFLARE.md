# เปิด ODS Chatbot ออกเน็ตด้วย Cloudflare Tunnel + Access

คู่มือเปิด demo ให้ test user เข้าจากภายนอก โดย self-host บนเครื่องตัวเอง
ปลอดภัย: **เปิดเฉพาะ frontend** ผ่าน tunnel, backend/qdrant/postgres อยู่ภายในไม่ออกเน็ต,
กั้นด้วย Google login + allowlist อีเมล, และ `/api/ingest` ล็อกเป็น admin

> โค้ดฝั่ง repo พร้อมแล้ว (มี service `cloudflared` + ล็อก ingest) เหลือทำตามขั้นตอนด้านล่าง

---

## 0. เตรียม

- โดเมน — แนะนำจดผ่าน **Cloudflare Registrar** (Dashboard → Domain Registration → Register)
  ราคาทุน อยู่บน Cloudflare ทันที ไม่ต้องย้าย nameserver
  (ถ้าจดที่อื่น: เพิ่ม site ใน Cloudflare แล้วเปลี่ยน nameserver ตามที่ Cloudflare บอก รอ active)
- บัญชี Cloudflare (เปิด **Zero Trust** ฟรี: เลือก team name, แพลน Free)
- Docker stack รันอยู่ (`docker compose up -d`)

---

## 1. ตั้งค่า `.env` (บนเครื่อง — ห้าม commit)

```
ODS_ADMIN_KEY=<สุ่มสตริงยาว ๆ ของคุณ>
CLOUDFLARE_TUNNEL_TOKEN=<ได้จากขั้นตอนที่ 2>
```
- `ODS_ADMIN_KEY` คือกุญแจอัปโหลดเอกสาร — ตั้งให้เดายาก เก็บไว้คนเดียว

---

## 2. สร้าง Cloudflare Tunnel (แบบ token)

1. **Zero Trust → Networks → Tunnels → Create a tunnel** → ชนิด **Cloudflared** → ตั้งชื่อ เช่น `ods-demo`
2. หน้า "Install connector" จะมี **token** (สตริงยาวหลัง `--token`) → copy เอาไปใส่
   `CLOUDFLARE_TUNNEL_TOKEN` ใน `.env` (เราใช้ผ่าน docker ไม่ต้องลง connector เอง)
3. ไปแท็บ **Public Hostname → Add a public hostname**
   - Subdomain: `ods-demo`  ·  Domain: `<โดเมนคุณ>`  → ได้ `ods-demo.<โดเมน>`
   - Type: **HTTP**  ·  URL: **`frontend:3000`**
     (cloudflared คุยกับ frontend ผ่าน docker network)
4. บนเครื่อง: `docker compose up -d cloudflared`
   ตรวจ log: `docker compose logs cloudflared` ต้องเห็น **"Registered tunnel connection"**
   - กลับไปหน้า Tunnels จะเห็นสถานะ **HEALTHY**

ทดสอบเปล่า ๆ: เปิด `https://ods-demo.<โดเมน>` ควรเห็นหน้า ODS (ตอนนี้ยัง**ไม่มี** Access กั้น — ทำข้อ 3-4)

---

## 3. ตั้ง Google เป็นวิธี login (IdP)

**3.1 สร้าง OAuth client ใน Google Cloud Console**
- APIs & Services → Credentials → **Create Credentials → OAuth client ID** → Web application
- **Authorized redirect URI** ใส่ (ดูค่าที่แน่นอนจากหน้า Cloudflare ข้อ 3.2 — รูปแบบ):
  `https://<team-name>.cloudflareaccess.com/cdn-cgi/access/callback`
- ได้ **Client ID** + **Client secret**

**3.2 เพิ่มใน Cloudflare**
- Zero Trust → **Settings → Authentication → Login methods → Add new → Google**
- วาง Client ID / Client secret → **Save** → กด **Test** ให้ผ่าน

---

## 4. สร้าง Access Application + นโยบาย allowlist

1. Zero Trust → **Access → Applications → Add an application → Self-hosted**
2. Application name: `ODS Demo` · Session: เช่น 24h
3. **Public hostname**: `ods-demo.<โดเมน>` (ตรงกับข้อ 2.3)
4. **Identity providers**: เลือก **Google** (ปิด One-time PIN ได้ถ้าไม่อยากให้ใช้)
5. **Policies → Add a policy**
   - Name: `testers` · Action: **Allow**
   - Include → **Emails** = รายอีเมล tester (หรือ **Emails ending in** `@domain.com`)
6. Save

เสร็จแล้ว: เปิด `https://ods-demo.<โดเมน>` → จะเด้งหน้า Cloudflare → **Login with Google** →
อีเมลที่อยู่ใน policy เท่านั้นที่เข้าได้ คนอื่นถูกบล็อก

---

## 5. เปิดสิทธิ์อัปโหลดให้ตัวเอง (admin)

- เข้าเว็บ demo → แผงขวา **"เพิ่มเอกสารฐานความรู้"** → ช่อง **Admin key** → ใส่ค่าเดียวกับ
  `ODS_ADMIN_KEY` (เก็บใน browser คุณครั้งเดียว)
- tester ไม่มี key → อัปโหลดไม่ได้ (403) แต่แชตได้ปกติ
- อัปโหลดผ่าน CLI ก็ได้: ส่ง header `X-Admin-Key: <ODS_ADMIN_KEY>`

---

## 6. เช็คลิสต์ทดสอบ

- [ ] `docker compose logs cloudflared` → tunnel HEALTHY
- [ ] เปิด URL → เจอ Google login (Cloudflare Access)
- [ ] อีเมลใน allowlist เข้าได้ + แชต/ประวัติทำงาน · อีเมลนอก allowlist ถูกบล็อก
- [ ] อัปโหลดไม่มี key → ขึ้นเตือนต้องมีสิทธิ์ admin · ใส่ key → อัปโหลดได้
- [ ] `https://<โดเมน>:8000` หรือ backend ตรง ๆ เข้าจากเน็ตไม่ได้ (เปิดแค่ frontend)

---

## หมายเหตุ
- **SSE streaming** ผ่าน tunnel ได้ (ตั้ง `X-Accel-Buffering: no` ไว้แล้ว)
- ปิด demo: `docker compose stop cloudflared` (ตัดการเข้าถึงจากเน็ตทันที สแตกอื่นยังรัน)
- PDPA: เป็น demo วงปิด (เฉพาะอีเมลที่เชิญ) — ก่อนใช้ข้อมูลผู้ป่วยจริงค่อยทำ Clerk + ย้าย managed (ดู memory: deployment-options)
