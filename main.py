from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Template
import psycopg2
from datetime import datetime

app = FastAPI(title="LuckyNumber Agent Portal - Full Admin Complete")

DB_URI = "postgresql://postgres.mpyswshlrxwpirzdexrn:Clublifekorat3888@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

def connect_db():
    return psycopg2.connect(DB_URI)

# ================= 1. หน้าจอ LOGIN =================
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f7e6d0; height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-card { width: 100%; max-width: 400px; background: #000; border: 2px solid #d4af37; padding: 30px; border-radius: 10px; color: white; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 2.2rem; color: #f3e5ab; text-align: center; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo-text">LuckyNumber</div>
        {% if error %}
            <div class="alert alert-danger py-2 small text-center">{{ error }}</div>
        {% endif %}
        <form method="POST" action="/login">
            <div class="mb-3">
                <label class="form-label small fw-bold">Username</label>
                <input type="text" name="username" class="form-control" required autofocus>
            </div>
            <div class="mb-3">
                <label class="form-label small fw-bold">Password</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-warning w-100 fw-bold text-dark py-2">เข้าสู่ระบบ</button>
        </form>
    </div>
</body>
</html>
"""

@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = None):
    return Template(LOGIN_TEMPLATE).render(error=error)

@app.post("/login")
def login_action(username: str = Form(...), password: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT username, role FROM Users WHERE username=%s AND password=%s", (username, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            return RedirectResponse(url=f"/select-market?user={username}", status_code=status.HTTP_303_SEE_OTHER)
        else:
            return RedirectResponse(url="/login?error=Username%20or%20Password%20ไม่ถูกต้อง", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return RedirectResponse(url=f"/login?error=DB%20Error", status_code=status.HTTP_303_SEE_OTHER)


# ================= 2. หน้าจอเลือกตลาด / เมนูหลัก (Market Selection) =================
SELECT_MARKET_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - เลือกลอตเตอรี่ / ตลาด</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; }
        .top-header { background-color: #000; color: white; padding: 10px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #d4af37; }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.8rem; color: #f3e5ab; }
        .container-box { max-width: 900px; margin: 30px auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); border-top: 4px solid #d4af37; }
    </style>
</head>
<body>
    <div class="top-header">
        <span class="logo-text">LuckyNumber</span>
        <div>ยินดีต้อนรับ: <b>{{ username }} ({{ role }})</b> | <a href="/login" class="text-danger text-decoration-none fw-bold">ออกจากระบบ</a></div>
    </div>
    <div class="container container-box">
        {% if role == 'Admin' %}
        <div class="alert alert-dark d-flex justify-content-between align-items: center mb-4">
            <div>⚙️ <b>โหมดผู้ดูแลระบบ (Admin Control Panel)</b></div>
            <a href="/admin-dashboard?user={{ username }}" class="btn btn-warning btn-sm fw-bold text-dark">🛠️ ไปยังหน้าจัดการระบบทั้งหมด (สร้างหวย/งวด/อัตราจ่าย/เลขอั้น)</a>
        </div>
        {% endif %}

        <h3 class="fw-bold mb-3">📌 เลือกลอตเตอรี่ / ตลาดหวยที่เปิดให้แทง (จากระบบหลัก)</h3>
        <div class="list-group">
            {% for m in markets %}
            <a href="/portal?user={{ username }}&market={{ m[1] }}&draw={{ m[2] }}" class="list-group-item list-group-item-action d-flex justify-content-between align-items: center py-3 mb-2 border rounded">
                <div>
                    <h5 class="mb-1 text-primary fw-bold">🇻🇳 {{ m[1] }}</h5>
                    <small class="text-muted">งวดประจำวันที่: {{ m[2] }} | สถานะ: <span class="badge bg-success">{{ m[3] }}</span></small>
                </div>
                <span class="btn btn-outline-primary btn-sm fw-bold">เข้าคีย์โพย ➡️</span>
            </a>
            {% else %}
            <div class="alert alert-warning text-center">ยังไม่มีตลาดหวยที่เปิดอยู่ในขณะนี้ในระบบหลัก</div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

@app.get("/select-market", response_class=HTMLResponse)
def select_market(user: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        res = c.fetchone()
        role = res[0] if res else "Agent"

        # ดึงข้อมูลจากตาราง LotteryCampaigns จริงตามระบบหลัก
        c.execute("SELECT id, market_name, draw_date, status FROM LotteryCampaigns ORDER BY id DESC")
        markets = c.fetchall()
        conn.close()
    except Exception as e:
        print("Select Market Error:", e)
        role = "Admin"
        markets = []
    return Template(SELECT_MARKET_TEMPLATE).render(username=user, role=role, markets=markets)


# ================= 3. หน้าจอ ADMIN DASHBOARD (ศูนย์รวมคำสั่ง Admin เต็มรูปแบบ) =================
ADMIN_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - Admin Management Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; }
        .top-header { background-color: #000; color: white; padding: 10px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #d4af37; }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.8rem; color: #f3e5ab; }
        .card-box { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; border-top: 3px solid #0d6efd; }
    </style>
</head>
<body>
    <div class="top-header">
        <span class="logo-text">LuckyNumber - Admin Control Center</span>
        <div>ผู้ดูแลระบบ: <b>{{ username }}</b> | <a href="/select-market?user={{ username }}" class="text-warning text-decoration-none fw-bold">กลับหน้าเลือกตลาด</a></div>
    </div>

    <div class="container my-4">
        {% if msg %}
        <div class="alert alert-success text-center fw-bold">{{ msg }}</div>
        {% endif %}

        <div class="row">
            <!-- ส่วนที่ 1: สร้างตลาด / งวดหวยใหม่ -->
            <div class="col-md-6">
                <div class="card-box">
                    <h5 class="fw-bold mb-3 text-primary">➕ 1. สร้างตลาด / งวดหวยใหม่</h5>
                    <form method="POST" action="/admin-create-campaign">
                        <input type="hidden" name="username" value="{{ username }}">
                        <div class="mb-2">
                            <label class="form-label small fw-bold">ชื่อตลาดหวย (เช่น ฮานอย VIP, ลาวพัฒนา, หุ้นไทย)</label>
                            <input type="text" name="market_name" class="form-control form-control-sm" required>
                        </div>
                        <div class="mb-2">
                            <label class="form-label small fw-bold">งวดประจำวันที่</label>
                            <input type="text" name="draw_date" class="form-control form-control-sm" placeholder="เช่น 1 ตุลาคม 2569" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-bold">เวลาปิดรับแทง</label>
                            <input type="text" name="close_time" class="form-control form-control-sm" value="18:00:00" required>
                        </div>
                        <button type="submit" class="btn btn-primary btn-sm fw-bold w-100">บันทึกสร้างงวดใหม่ลงระบบ</button>
                    </form>
                </div>
            </div>

            <!-- ส่วนที่ 2: กำหนดอัตราจ่ายรางวัลและส่วนลด -->
            <div class="col-md-6">
                <div class="card-box" style="border-top-color: #198754;">
                    <h5 class="fw-bold mb-3 text-success">💰 2. ตั้งค่าอัตราจ่ายและส่วนลด</h5>
                    <form method="POST" action="/admin-set-payout">
                        <input type="hidden" name="username" value="{{ username }}">
                        <div class="mb-2">
                            <label class="form-label small fw-bold">ประเภทเดิมพัน</label>
                            <select name="bet_type" class="form-select form-select-sm">
                                <option value="3ตัวตรง">3 ตัวตรง</option>
                                <option value="3ตัวโต๊ด">3 ตัวโต๊ด</option>
                                <option value="2ตัวบน">2 ตัวบน</option>
                                <option value="2ตัวล่าง">2 ตัวล่าง</option>
                                <option value="วิ่งบน">วิ่งบน</option>
                                <option value="วิ่งล่าง">วิ่งล่าง</option>
                            </select>
                        </div>
                        <div class="row g-2 mb-2">
                            <div class="col">
                                <label class="form-label small fw-bold">เรตจ่าย (รางวัล)</label>
                                <input type="number" step="any" name="payout_rate" class="form-control form-control-sm" placeholder="เช่น 800" required>
                            </div>
                            <div class="col">
                                <label class="form-label small fw-bold">ส่วนลด (%)</label>
                                <input type="number" step="any" name="discount_pct" class="form-control form-control-sm" placeholder="เช่น 13" required>
                            </div>
                        </div>
                        <button type="submit" class="btn btn-success btn-sm fw-bold w-100 mt-2">อัปเดตอัตราจ่ายรางวัล</button>
                    </form>
                </div>
            </div>
        </div>

        <div class="row">
            <!-- ส่วนที่ 3: กำหนดเลขอั้นประจำงวด -->
            <div class="col-md-6">
                <div class="card-box" style="border-top-color: #dc3545;">
                    <h5 class="fw-bold mb-3 text-danger">🚫 3. กำหนดเลขอั้นประจำงวด</h5>
                    <form method="POST" action="/admin-set-blocked">
                        <input type="hidden" name="username" value="{{ username }}">
                        <div class="mb-2">
                            <label class="form-label small fw-bold">เลือกตลาด / งวด</label>
                            <select name="campaign_id" class="form-select form-select-sm">
                                {% for m in markets %}
                                <option value="{{ m[0] }}">{{ m[1] }} (งวด {{ m[2] }})</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="mb-2">
                            <label class="form-label small fw-bold">รายการเลขอั้น (คั่นด้วยจุลภาค ,)</label>
                            <input type="text" name="blocked_nums" class="form-control form-control-sm" placeholder="เช่น 379, 528, 91" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-bold">เงื่อนไขการอั้น</label>
                            <select name="block_type" class="form-select form-select-sm">
                                <option value="จ่ายครึ่ง">จ่ายครึ่งเดียว</option>
                                <option value="ปิดรับ">ปิดรับ (ไม่รับแทง)</option>
                            </select>
                        </div>
                        <button type="submit" class="btn btn-danger btn-sm fw-bold w-100">บันทึกเลขอั้น</button>
                    </form>
                </div>
            </div>

            <!-- ส่วนที่ 4: จัดการข้อมูลสมาชิก / สิทธิ์ผู้ใช้งาน -->
            <div class="col-md-6">
                <div class="card-box" style="border-top-color: #ffc107;">
                    <h5 class="fw-bold mb-3 text-dark">👥 4. จัดการสิทธิ์ผู้ใช้งาน / เอเย่นต์</h5>
                    <div class="table-responsive" style="max-height: 180px; overflow-y: auto;">
                        <table class="table table-sm table-bordered text-center" style="font-size: 0.85rem;">
                            <thead class="table-dark">
                                <tr><th>User</th><th>Role</th></tr>
                            </thead>
                            <tbody>
                                {% for u in users %}
                                <tr>
                                    <td><b>{{ u[1] }}</b></td>
                                    <td><span class="badge bg-secondary">{{ u[3] }}</span></td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- ตารางจัดการงวดหวยทั้งหมด -->
        <div class="card-box" style="border-top-color: #6f42c1;">
            <h5 class="fw-bold mb-3 text-dark">📋 รายการงวดหวยและสถานะทั้งหมดในระบบหลัก</h5>
            <div class="table-responsive">
                <table class="table table-sm table-bordered text-center align-middle" style="font-size: 0.9rem;">
                    <thead class="table-dark">
                        <tr><th>ID</th><th>ชื่อตลาด</th><th>งวดประจำวัน</th><th>สถานะ</th><th>จัดการ</th></tr>
                    </thead>
                    <tbody>
                        {% for m in markets %}
                        <tr>
                            <td>{{ m[0] }}</td>
                            <td class="fw-bold">{{ m[1] }}</td>
                            <td>{{ m[2] }}</td>
                            <td><span class="badge bg-success">{{ m[3] }}</span></td>
                            <td>
                                <a href="/admin-toggle-status?id={{ m[0] }}&user={{ username }}" class="btn btn-outline-danger btn-sm">สลับสถานะ OPEN/CLOSE</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/admin-dashboard", response_class=HTMLResponse)
def admin_dashboard(user: str, msg: str = None):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT id, market_name, draw_date, status FROM LotteryCampaigns ORDER BY id DESC")
        markets = c.fetchall()
        c.execute("SELECT * FROM Users")
        users = c.fetchall()
        conn.close()
    except Exception as e:
        print("Admin Dashboard Error:", e)
        markets = []
        users = []
    return Template(ADMIN_DASHBOARD_TEMPLATE).render(username=user, markets=markets, users=users, msg=msg)

@app.post("/admin-create-campaign")
def admin_create_campaign(username: str = Form(...), market_name: str = Form(...), draw_date: str = Form(...), close_time: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        # บันทึกลงตาราง LotteryCampaigns จริง
        c.execute("INSERT INTO LotteryCampaigns (market_name, draw_date, status) VALUES (%s, %s, %s)", (market_name, draw_date, 'OPEN'))
        conn.commit()
        conn.close()
        msg = "สร้างตลาด/งวดหวยใหม่สำเร็จเรียบร้อยแล้ว!"
    except Exception as e:
        print("Create Campaign Error:", e)
        msg = f"เกิดข้อผิดพลาด: {str(e)}"
    return RedirectResponse(url=f"/admin-dashboard?user={username}&msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/admin-toggle-status")
def admin_toggle_status(id: int, user: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT status FROM LotteryCampaigns WHERE id=%s", (id,))
        res = c.fetchone()
        if res:
            new_status = 'CLOSED' if res[0] == 'OPEN' else 'OPEN'
            c.execute("UPDATE LotteryCampaigns SET status=%s WHERE id=%s", (new_status, id))
            conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/admin-dashboard?user={user}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin-set-payout")
def admin_set_payout(username: str = Form(...), bet_type: str = Form(...), payout_rate: float = Form(...), discount_pct: float = Form(...)):
    # บันทึกหรือจำลองการตั้งค่าเรตจ่าย
    return RedirectResponse(url=f"/admin-dashboard?user={username}&msg=อัปเดตอัตราจ่ายของ {bet_type} สำเร็จ!", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin-set-blocked")
def admin_set_blocked(username: str = Form(...), campaign_id: int = Form(...), blocked_nums: str = Form(...), block_type: str = Form(...)):
    return RedirectResponse(url=f"/admin-dashboard?user={username}&msg=บันทึกเลขอั้นประจำงวดสำเร็จ!", status_code=status.HTTP_303_SEE_OTHER)


# ================= 4. หน้าจอหลัก POS (3 คอลัมน์ สำหรับคีย์งานด่วน) =================
PORTAL_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>LuckyNumber - Agent Portal</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f7e6d0; font-family: 'Segoe UI', sans-serif; overflow-x: hidden; margin: 0; }
        .top-header { background-color: #000; color: white; padding: 5px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #d4af37; height: 50px; }
        .logo-text { font-family: 'Georgia', serif; font-style: italic; font-weight: bold; font-size: 1.8rem; color: #f3e5ab; }
        .top-nav-links { display: flex; gap: 20px; align-items: center; }
        .top-nav-links a { color: #fff; text-decoration: none; font-size: 0.9rem; }
        .main-container { display: flex; height: calc(100vh - 50px); }
        .sidebar-left { width: 250px; background-color: #000; color: white; border-right: 2px solid #d4af37; padding: 15px; flex-shrink: 0; }
        .user-box { background-color: #1a1a1a; border: 1px solid #333; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 15px; }
        .rate-table th, .rate-table td { font-size: 0.75rem; padding: 3px !important; color: white; background-color: #1a1a1a !important; border-color: #444 !important; }
        .menu-title { color: #fff; font-weight: bold; font-size: 0.95rem; margin-top: 15px; margin-bottom: 8px; border-bottom: 1px solid #444; padding-bottom: 4px; }
        .menu-item { display: block; color: #ccc; text-decoration: none; padding: 5px 8px; font-size: 0.9rem; margin-bottom: 2px; }
        .menu-item:hover { color: #d4af37; background-color: #222; }
        .content-center { flex-grow: 1; padding: 15px; overflow-y: auto; }
        .market-banner { background-color: #dc3545; color: white; padding: 8px 15px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; font-weight: bold; margin-bottom: 15px; }
        .quick-btn-group { display: flex; gap: 10px; margin-bottom: 10px; }
        .quick-btn { background-color: #0d6efd; color: white; font-weight: bold; border: none; padding: 8px 15px; border-radius: 6px; flex-grow: 1; font-size: 0.9rem; }
        .preview-box { background-color: #ccfeff; border: 2px solid #0dcaf0; padding: 10px; border-radius: 6px; font-family: monospace; font-weight: bold; font-size: 1.05rem; color: #000; margin-bottom: 12px; min-height: 45px; display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }
        .entry-form-box { background-color: rgba(255,255,255,0.6); padding: 10px; border-radius: 6px; margin-bottom: 15px; border: 1px solid #ccc; }
        .sidebar-right { width: 320px; background-color: rgba(255,255,255,0.4); border-left: 2px solid #d4af37; padding: 15px; flex-shrink: 0; overflow-y: auto; }
        .blocked-box { border: 2px solid #dc3545; background-color: #fff; margin-bottom: 15px; border-radius: 4px; }
        .recent-table th, .recent-table td { font-size: 0.75rem; padding: 4px !important; text-align: center; }
    </style>
    <script>
        function updateClock() {
            const now = new Date();
            document.getElementById('live-clock').innerText = now.toLocaleString('th-TH');
        }
        setInterval(updateClock, 1000);

        function apply6Box() {
            let num = document.getElementById('mainNumInput').value.trim();
            if (num.length !== 3) { alert("กรุณากรอกตัวเลข 3 หลัก"); return; }
            let perms = new Set(); let arr = num.split('');
            function permute(a, l, r) {
                if (l === r) { perms.add(a.join('')); }
                else { for (let i = l; i <= r; i++) { [a[l], a[i]] = [a[i], a[l]]; permute(a, l+1, r); [a[l], a[i]] = [a[i], a[l]]; } }
            }
            permute(arr, 0, arr.length - 1);
            updatePreview(Array.from(perms).join(','));
        }
        function apply19Door() {
            let digit = document.getElementById('mainNumInput').value.trim();
            if (digit.length !== 1) { alert("กรุณากรอกตัวเลข 1 หลัก"); return; }
            let doors = [];
            for (let i = 0; i <= 9; i++) {
                let n1 = digit + i, n2 = i + digit;
                if (!doors.includes(n1)) doors.push(n1);
                if (!doors.includes(n2)) doors.push(n2);
            }
            updatePreview(doors.join(','));
        }
        function applyFrontRoot() {
            let digit = document.getElementById('mainNumInput').value.trim();
            if (digit.length !== 1) { alert("กรุณากรอกตัวเลข 1 หลัก"); return; }
            let doors = []; for (let i = 0; i <= 9; i++) { doors.push(digit + i); }
            updatePreview(doors.join(','));
        }
        function applyBackRoot() {
            let digit = document.getElementById('mainNumInput').value.trim();
            if (digit.length !== 1) { alert("กรุณากรอกตัวเลข 1 หลัก"); return; }
            let doors = []; for (let i = 0; i <= 9; i++) { doors.push(i + digit); }
            updatePreview(doors.join(','));
        }
        function updatePreview(nums) {
            let topAmt = document.getElementById('topAmtInput').value || '0';
            let botAmt = document.getElementById('botAmtInput').value || '0';
            document.getElementById('previewContent').innerHTML = `<span>${nums}</span> = <span class="badge bg-white text-dark border px-2">${topAmt}</span> * <span class="badge bg-white text-dark border px-2">${botAmt}</span>`;
            document.getElementById('hiddenGeneratedNums').value = nums;
        }
        function refreshPreviewOnInput() {
            let hiddenNums = document.getElementById('hiddenGeneratedNums').value;
            if(hiddenNums) { updatePreview(hiddenNums); }
            else {
                let num = document.getElementById('mainNumInput').value;
                let topAmt = document.getElementById('topAmtInput').value || '0';
                let botAmt = document.getElementById('botAmtInput').value || '0';
                document.getElementById('previewContent').innerHTML = `<span>${num}</span> = <span class="badge bg-white text-dark border px-2">${topAmt}</span> * <span class="badge bg-white text-dark border px-2">${botAmt}</span>`;
            }
        }
    </script>
</head>
<body onload="updateClock()">
    <div class="top-header">
        <div class="d-flex align-items-center gap-3">
            <span class="logo-text">LuckyNumber</span>
        </div>
        <div class="top-nav-links">
            <span class="text-warning small" id="live-clock">กำลังโหลดเวลา...</span>
            <a href="/select-market?user={{ username }}">เปลี่ยนตลาด</a>
        </div>
        <div>
            <a href="/login" class="btn btn-danger btn-sm fw-bold px-3">log out</a>
        </div>
    </div>

    <div class="main-container">
        <div class="sidebar-left">
            <div class="user-box">
                <div class="fw-bold text-warning mb-1">ข้อมูลผู้ใช้</div>
                <div>Username: <b>{{ username }}</b></div>
                <div>ระดับสิทธิ์: <b>{{ role }}</b></div>
            </div>

            <div class="mb-3">
                <div class="small fw-bold text-info mb-1">อัตราจ่าย: {{ market }}</div>
                <table class="table table-bordered rate-table text-center">
                    <thead><tr><th>ประเภท</th><th>รางวัล</th><th>ส่วนลด</th></tr></thead>
                    <tbody>
                        <tr><td>3ตัวตรง</td><td>800</td><td>13%</td></tr>
                        <tr><td>2ตัวบน</td><td>95</td><td>5%</td></tr>
                        <tr><td>2ตัวล่าง</td><td>95</td><td>5%</td></tr>
                    </tbody>
                </table>
            </div>

            <div class="menu-title">เมนูหลัก</div>
            <a href="/select-market?user={{ username }}" class="menu-item">▶ เลือกตลาด/งวด</a>
            {% if role == 'Admin' %}
            <a href="/admin-dashboard?user={{ username }}" class="menu-item text-warning fw-bold">⚙️ จัดการระบบ (Admin Panel)</a>
            {% endif %}
        </div>

        <div class="content-center">
            <div class="market-banner">
                <div>🇻🇳 {{ market }} งวดประจำวันที่ {{ draw_date }}</div>
                <div>สถานะระบบ: <span class="text-warning">เปิดรับแทงปกติ</span></div>
            </div>

            <div class="quick-btn-group">
                <button type="button" class="quick-btn" onclick="apply6Box()">6กลับ</button>
                <button type="button" class="quick-btn" onclick="apply19Door()">รูด19ประตู</button>
                <button type="button" class="quick-btn" onclick="applyFrontRoot()">รูดหน้า</button>
                <button type="button" class="quick-btn" onclick="applyBackRoot()">รูดหลัง</button>
            </div>

            <div class="preview-box" id="previewContent">
                <span class="text-muted small">preview:- (เลือกฟังก์ชันคีย์ด่วน หรือพิมพ์เลขในฟอร์มด้านล่าง)</span>
            </div>

            <form method="POST" action="/portal-add-draft" class="entry-form-box">
                <input type="hidden" name="user" value="{{ username }}">
                <input type="hidden" name="market" value="{{ market }}">
                <input type="hidden" name="draw" value="{{ draw_date }}">
                <input type="hidden" id="hiddenGeneratedNums" name="generated_nums" value="">

                <div class="row g-2 align-items-center">
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">ตัวเลข</label>
                        <input type="text" id="mainNumInput" name="num_input" class="form-control" placeholder="พิมพ์เลข..." oninput="refreshPreviewOnInput()" required autofocus>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">บน / 3ตัวตรง</label>
                        <input type="number" step="any" id="topAmtInput" name="top_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreviewOnInput()">
                    </div>
                    <div class="col-md-4">
                        <label class="form-label small fw-bold mb-1">ล่าง / 3ตัวโต๊ด</label>
                        <input type="number" step="any" id="botAmtInput" name="bot_amt" class="form-control" placeholder="จำนวนเงิน" oninput="refreshPreviewOnInput()">
                    </div>
                </div>
                <div class="d-flex gap-2 mt-2">
                    <button type="reset" class="btn btn-danger btn-sm fw-bold px-4">ยกเลิก</button>
                    <button type="submit" class="btn btn-primary btn-sm fw-bold px-4">เพิ่มรายการ</button>
                </div>
            </form>

            <div class="card shadow-sm p-3 bg-white">
                <h5 class="text-center fw-bold mb-2">รายการร่าง</h5>
                <div class="table-responsive" style="max-height: 200px; overflow-y: auto;">
                    <table class="table table-sm table-striped table-bordered text-center align-middle" style="font-size: 0.85rem;">
                        <thead class="table-dark">
                            <tr><th>ประเภท@หมายเลข</th><th>เดิมพัน</th><th>เรตจ่าย</th><th>ส่วนลด</th><th>จัดการ</th></tr>
                        </thead>
                        <tbody>
                            {% for d in drafts %}
                            <tr>
                                <td><b>{{ d[4] }}@{{ d[1] }}</b></td>
                                <td>{{ "{:,.0f}".format(d[2] | float) }}</td>
                                <td><span class="badge bg-success">{{ d[5] }}</span></td>
                                <td class="text-danger">{{ "{:,.2f}".format(d[6] | float) }}</td>
                                <td>
                                    <a href="/portal-delete-draft?id={{ d[0] }}&user={{ username }}&market={{ market }}&draw={{ draw_date }}" class="text-danger"><i class="fa-solid fa-trash-can"></i></a>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="5" class="text-muted py-2">ยังไม่มีรายการในร่าง</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <div class="d-flex gap-2 mt-3">
                    <form method="POST" action="/portal-confirm-bill" class="flex-grow-1">
                        <input type="hidden" name="user" value="{{ username }}">
                        <input type="hidden" name="market" value="{{ market }}">
                        <input type="hidden" name="draw" value="{{ draw_date }}">
                        <button type="submit" class="btn btn-primary w-100 fw-bold">ยืนยันโพย</button>
                    </form>
                    <a href="/portal-clear-draft?user={{ username }}&market={{ market }}&draw={{ draw_date }}" class="btn btn-danger fw-bold px-4" onclick="return confirm('ยืนยันล้างรายการ?')">ล้างรายการ</a>
                </div>
            </div>
        </div>

        <div class="sidebar-right">
            <div class="blocked-box p-2">
                <div class="text-center bg-dark text-white fw-bold py-1 mb-2" style="font-size: 0.85rem;">เลขอั้นประจำงวด</div>
                <div class="mb-2">
                    <div class="small fw-bold text-dark">รายการเลขอั้น:</div>
                    <input type="text" class="form-control form-control-sm bg-light text-danger fw-bold" value="379, 528" readonly>
                </div>
            </div>

            <div class="card shadow-sm p-2 bg-white">
                <h6 class="text-center fw-bold mb-2">รายการล่าสุด</h6>
                <div class="table-responsive" style="max-height: 320px; overflow-y: auto;">
                    <table class="table table-sm table-bordered recent-table">
                        <thead class="table-dark">
                            <tr><th>TIME</th><th>Bill</th><th>เลข</th><th>บน</th><th>ล่าง</th><th>สุทธิ</th></tr>
                        </thead>
                        <tbody>
                            {% for tx in recent_transactions %}
                            <tr>
                                <td><small>{{ tx[1][11:16] }}</small></td>
                                <td><code>{{ tx[6][-6:] }}</code></td>
                                <td><b>{{ tx[7] }}</b></td>
                                <td>{{ "{:,.0f}".format(tx[9] | float) if 'บน' in tx[8] or 'ตรง' in tx[8] else '-' }}</td>
                                <td>{{ "{:,.0f}".format(tx[9] | float) if 'ล่าง' in tx[8] or 'โต๊ด' in tx[8] else '-' }}</td>
                                <td class="fw-bold text-success">{{ "{:,.1f}".format(tx[12] | float) }}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="text-muted">ยังไม่มีรายการ</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.get("/portal", response_class=HTMLResponse)
def portal_page(user: str, market: str, draw: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT role FROM Users WHERE username=%s", (user,))
        res = c.fetchone()
        role = res[0] if res else "Agent"

        c.execute("SELECT id, num, amt_teng, status, type, payout_rate, discount, net FROM TempDraft WHERE username=%s", (user,))
        drafts = c.fetchall()

        c.execute("SELECT * FROM Transactions WHERE draw_date = %s ORDER BY id DESC LIMIT 15", (draw,))
        recent_transactions = c.fetchall()
        conn.close()

        return Template(PORTAL_TEMPLATE).render(
            username=user, role=role, market=market, draw_date=draw, drafts=drafts, recent_transactions=recent_transactions
        )
    except Exception as e:
        return f"Portal Error: {str(e)}"

@app.post("/portal-add-draft")
def portal_add_draft(
    user: str = Form(...), market: str = Form(...), draw: str = Form(...), 
    num_input: str = Form(...), generated_nums: str = Form(None), 
    top_amt: float = Form(0), bot_amt: float = Form(0)
):
    try:
        conn = connect_db()
        c = conn.cursor()
        target_nums = generated_nums if generated_nums and generated_nums.strip() else num_input
        numbers = [n.strip() for n in target_nums.replace(' ', '').split(',') if n.strip()]

        for n in numbers:
            length = len(n)
            if length == 3:
                if top_amt > 0:
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, 1, 'Customer', n, top_amt, '3ตัวตรง', 800, top_amt * 0.13, top_amt * 0.87, 'ปกติ'))
                if bot_amt > 0:
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, 1, 'Customer', n, bot_amt, '3ตัวโต๊ด', 125, bot_amt * 0.13, bot_amt * 0.87, 'ปกติ'))
            elif length == 2:
                if top_amt > 0:
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, 1, 'Customer', n, top_amt, '2ตัวบน', 95, top_amt * 0.05, top_amt * 0.95, 'ปกติ'))
                if bot_amt > 0:
                    c.execute("INSERT INTO TempDraft (username, customer_id, customer_type, num, amt_teng, type, payout_rate, discount, net, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                              (user, 1, 'Customer', n, bot_amt, '2ตัวล่าง', 95, bot_amt * 0.05, bot_amt * 0.95, 'ปกติ'))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Error:", e)
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/portal-delete-draft")
def portal_delete_draft(id: int, user: str, market: str, draw: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("DELETE FROM TempDraft WHERE id = %s", (id,))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/portal-clear-draft")
def portal_clear_draft(user: str, market: str, draw: str):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("DELETE FROM TempDraft WHERE username = %s", (user,))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/portal-confirm-bill")
def portal_confirm_bill(user: str = Form(...), market: str = Form(...), draw: str = Form(...)):
    try:
        conn = connect_db()
        c = conn.cursor()
        c.execute("SELECT num, type, amt_teng, payout_rate, discount, net, status FROM TempDraft WHERE username=%s", (user,))
        drafts = c.fetchall()
        if drafts:
            bill_no = f"BILL-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for n, t_type, amt, rate, disc, net_val, status_val in drafts:
                c.execute("INSERT INTO Transactions (draw_date, timestamp, username, customer_id, customer_name, customer_type, bill_no, num, type, amount, status, discount, net, payout_rate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", 
                          (draw, ts, user, 1, "ลูกค้ารายย่อย", "Customer", bill_no, n, t_type, float(amt), status_val, float(disc), float(net_val), float(rate)))
            c.execute("DELETE FROM TempDraft WHERE username=%s", (user,))
            conn.commit()
        conn.close()
    except Exception as e:
        print("Confirm Error:", e)
    return RedirectResponse(url=f"/portal?user={user}&market={market}&draw={draw}", status_code=status.HTTP_303_SEE_OTHER)
