import os
import threading
import psycopg2
import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

REASON = 1
GEN_MULAI, GEN_BBM_AWAL, GEN_BBM_AKHIR = range(3)

def get_db():
    return psycopg2.connect(os.getenv("SUPABASE_URL"))

# ===== WEB ABSEN: FILTER NAMA + BULAN =====
@app_flask.route('/')
def home():
    try:
        nama_filter = request.args.get('nama', '')
        bulan_filter = request.args.get('bulan', '')

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT nama FROM absensi ORDER BY nama")
        list_nama = [r[0] for r in cur.fetchall()]

        sql = """
            SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
            EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
            CASE WHEN jam_datang > TIME '09:00:00' THEN true ELSE false END as telat_flag
            FROM absensi WHERE 1=1
        """
        params = []
        if nama_filter:
            sql += " AND nama ILIKE %s"
            params.append(f"%{nama_filter}%")
        if bulan_filter:
            tahun, bulan = bulan_filter.split('-')
            sql += " AND EXTRACT(YEAR FROM tanggal) = %s AND EXTRACT(MONTH FROM tanggal) = %s"
            params.extend([tahun, bulan])
        sql += " ORDER BY tanggal DESC, jam_datang DESC LIMIT 200"
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()

        navbar = """<nav style="background:#4CAF50;padding:15px;text-align:center">
        <a href="/" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">📋 Absensi</a>
        <a href="/genset" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">⛽ Genset BBM</a></nav>"""

        option_nama = '<option value="">Semua Karyawan</option>'
        for n in list_nama:
            selected = 'selected' if n == nama_filter else ''
            option_nama += f'<option value="{n}" {selected}>{n}</option>'

        html = navbar + f"""
        <!DOCTYPE html><html><head><meta charset="UTF-8"><title>Data Absensi</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{{font-family:Arial;padding:20px;background:#f5f5f5}}h2{{text-align:center}}
        table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:center}}
        th{{background:#4CAF50;color:white}}tr:hover{{background:#f1f1f1}}
       .telat{{background:#ffebee;color:#c62828;font-weight:bold}}
       .status-izin{{color:orange}}.status-sakit{{color:red}}.status-cuti{{color:blue}}.status-lembur{{color:purple;font-weight:bold}}
       .filter{{text-align:center;margin:20px}}input,select,button{{padding:8px 12px;font-size:16px;margin:5px;border-radius:5px;border:1px solid #ddd}}
        @media (max-width:600px){{table,thead,tbody,th,td,tr{{display:block}}th{{display:none}}
        td{{border:none;position:relative;padding-left:50%}}td:before{{content:attr(data-label);position:absolute;left:10px;font-weight:bold}}}}
        </style></head><body><h2>📋 Data Absensi</h2>
        <div class="filter"><form method="get">
        <select name="nama">{option_nama}</select>
        <input type="month" name="bulan" value="{bulan_filter}">
        <button>Filter</button><a href="/"><button type="button">Reset</button></a>
        </form></div>
        <table><thead><tr><th>Nama</th><th>Tanggal</th><th>Datang</th><th>Pulang</th><th>Status</th><th>Alasan</th><th>Total Jam</th></tr></thead><tbody>
        """

        for row in data:
            nama, tanggal, datang, pulang, status, alasan, telat_db, total_detik, telat_flag = row
            row_class = "telat" if telat_flag else ""
            status_class = f"status-{status}" if status else ""
            total_detik = int(total_detik) if total_detik else 0
            h = total_detik // 3600
            m = (total_detik % 3600) // 60
            total_jam = f"{h:02d}j {m:02d}m" if total_detik else "-"
            html += f"""<tr class="{row_class}"><td data-label="Nama">{nama}</td><td data-label="Tanggal">{tanggal}</td><td data-label="Datang">{datang.strftime('%H:%M:%S') if datang else '-'}</td><td data-label="Pulang">{pulang.strftime('%H:%M:%S') if pulang else '-'}</td><td data-label="Status" class="{status_class}">{status or 'hadir'}</td><td data-label="Alasan">{alasan or '-'}</td><td data-label="Total Jam">{total_jam}</td></tr>"""
        html += """</tbody></table></body></html>"""
        return html
    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

# ===== WEB GENSET: MERAH <30% + GRAFIK + DURASI =====
# ===== WEB GENSET: MERAH <30% + GRAFIK + DURASI =====
@app_flask.route('/genset')
def home_genset():
    try:
        tanggal = request.args.get('tanggal', '')
        nama = request.args.get('nama', '')
        bulan = request.args.get('bulan', datetime.now(WIB).strftime('%Y-%m'))
        conn = get_db()
        cur = conn.cursor()
        # ... lanjutin kode lu ...
        cur.execute("SELECT DISTINCT petugas FROM genset_log ORDER BY petugas")
        list_petugas = [r[0] for r in cur.fetchall()]

        sql = "SELECT tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas FROM genset_log WHERE 1=1"
        params = []
        if tanggal:
            sql += " AND tanggal=%s"
            params.append(tanggal)
        if nama:
            sql += " AND petugas ILIKE %s"
            params.append(f"%{nama}%")
        sql += " ORDER BY tanggal ASC, jam_mulai ASC LIMIT 100"
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()

        labels = []
        data_sisa = []
        data_pakai = []
        info_detail = []
        rows = ""
        for r in data:
            tanggal, mulai, selesai, awal, akhir, pakai, sisa, petugas = r

            # HITUNG DURASI JAM MENIT
            if mulai and selesai:
                dt_mulai = datetime.combine(tanggal, mulai)
                dt_selesai = datetime.combine(tanggal, selesai)
                durasi_detik = (dt_selesai - dt_mulai).total_seconds()
                if durasi_detik < 0: durasi_detik += 86400
                h = int(durasi_detik // 3600)
                m = int((durasi_detik % 3600) // 60)
                durasi_str = f"{h}j {m}m"
            else:
                durasi_str = "-"

            labels.append(f"{tanggal} {mulai.strftime('%H:%M') if mulai else '-'}")
            data_sisa.append(sisa if sisa else 0)
            data_pakai.append(pakai if pakai else 0)
            info_detail.append(f"Tgl:{tanggal} | {mulai.strftime('%H:%M')}-{selesai.strftime('%H:%M') if selesai else '-'} | Durasi:{durasi_str} | Awal:{awal}% | Akhir:{akhir}% | Pakai:{pakai}% | Petugas:{petugas}")

            row_class = "style='background:#ffebee;color:#c62828;font-weight:bold'" if sisa and sisa < 30 else ""
            rows += f"<tr {row_class}><td>{tanggal}</td><td>{mulai.strftime('%H:%M') if mulai else '-'}</td><td>{selesai.strftime('%H:%M') if selesai else '-'}</td><td>{durasi_str}</td><td>{awal}%</td><td>{akhir}%</td><td>{pakai}%</td><td>{sisa}%</td><td>{petugas}</td></tr>"

        option_petugas = '<option value="">Semua Petugas</option>'
        for p in list_petugas:
            selected = 'selected' if p == nama else ''
            option_petugas += f'<option value="{p}" {selected}>{p}</option>'

        navbar = """<nav style="background:#FF9800;padding:15px;text-align:center">
        <a href="/" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">📋 Absensi</a>
        <a href="/genset" style="color:white;margin:0 20px;text-decoration:none;font-weight:bold">⛽ Genset BBM</a></nav>"""

        html = navbar + f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Log Genset</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>body{{font-family:Arial;padding:20px;background:#f5f5f5}}h2{{text-align:center}}
        table{{width:100%;border-collapse:collapse;background:white;margin-top:20px}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:center}}
        th{{background:#FF9800;color:white}}tr:hover{{background:#fff3e0}}
       .filter{{text-align:center;margin:20px}}input,select,button{{padding:8px 12px;font-size:16px;margin:5px;border-radius:5px;border:1px solid #ddd}}
       .chart-container{{background:white;padding:20px;border-radius:10px;box-shadow:0 2px 5px rgba(0,0,0,0.1);margin:20px 0}}
       .alert-low{{background:#ffebee;color:#c62828;padding:10px;border-radius:5px;text-align:center;font-weight:bold;margin:10px 0}}
        </style></head><body><h2>⛽ Log Penggunaan Genset & BBM</h2>

        <div class="filter"><form method="get">
        <input type="month" name="bulan" value="{bulan if 'bulan' in locals() else datetime.now(WIB).strftime('%Y-%m')}">
<select name="nama">{option_petugas}</select>
<button>Filter</button><a href="/genset"><button type="button">Reset</button></a>
<a href="/export_genset?bulan={bulan if 'bulan' in locals() else datetime.now(WIB).strftime('%Y-%m')}&nama={nama}" style="padding:8px 12px;background:#FF9800;color:white;text-decoration:none;border-radius:5px;margin-left:10px">⬇️ Export CSV Bulan Ini</a>        </form></div>

        <div class="chart-container"><canvas id="grafikBBM"></canvas></div>
        {f'<div class="alert-low">⚠️ PERHATIAN: Ada log dengan sisa BBM < 30%. Segera isi BBM!</div>' if any(s and s < 30 for s in data_sisa) else ''}

        <table><tr><th>Tanggal</th><th>Mulai</th><th>Selesai</th><th>Durasi</th><th>BBM Awal</th><th>BBM Akhir</th><th>Pakai</th><th>Sisa</th><th>Petugas</th></tr>{rows}</table>

        <script>
        const ctx = document.getElementById('grafikBBM');
        const infoDetail = {info_detail};
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {labels},
                datasets: [{{
                    label: 'Sisa BBM %',
                    data: {data_sisa},
                    borderColor: 'rgb(255, 99, 132)',
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    tension: 0.4, fill: true, pointRadius: 5, pointHoverRadius: 8
                }}, {{
                    label: 'Pemakaian BBM %',
                    data: {data_pakai},
                    borderColor: 'rgb(54, 162, 235)',
                    backgroundColor: 'rgba(54, 162, 235, 0.2)',
                    tension: 0.4, fill: true, pointRadius: 5, pointHoverRadius: 8
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    title: {{display: true, text: 'Grafik Penggunaan & Sisa BBM Genset', font: {{size: 18}}}},
                    tooltip: {{callbacks: {{afterLabel: function(context) {{return infoDetail[context.dataIndex];}}}}}}
                }},
                scales: {{
                    y: {{beginAtZero: true, max: 100, title: {{display: true, text: 'Persentase BBM %'}}}},
                    x: {{title: {{display: true, text: 'Tanggal & Jam'}}}}
                }}
            }}
        }});
        </script></body></html>"""
        return html
    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

@app_flask.route('/export_genset')
def export_genset():
    try:
        tanggal = request.args.get('tanggal')
nama = request.args.get('nama', '')
bulan = request.args.get('bulan', datetime.now(WIB).strftime('%Y-%m'))  # tambah ini
        
        conn = get_db()
        cur = conn.cursor()
        
        sql = "SELECT tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas FROM genset_log WHERE 1=1"
        params = []
        
        # Filter bulan YYYY-MM
        if bulan and '-' in bulan:
            tahun, bln = bulan.split('-')
            sql += " AND EXTRACT(YEAR FROM tanggal) = %s AND EXTRACT(MONTH FROM tanggal) = %s"
            params.extend([tahun, bln])
        
        # Filter nama/petugas
        if nama:
            sql += " AND petugas ILIKE %s"
            params.append(f"%{nama}%")
            
        sql += " ORDER BY tanggal DESC, jam_mulai DESC"
        cur.execute(sql, params)
        data = cur.fetchall()
        conn.close()
        
        if not data: 
            return "Belum ada data genset bulan ini", 404
            
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Tanggal', 'Jam Mulai', 'Jam Selesai', 'Durasi', 'BBM Awal %', 'BBM Akhir %', 'Pemakaian %', 'Sisa %', 'Petugas'])
        
        for row in data:
            tanggal, mulai, selesai, awal, akhir, pakai, sisa, petugas = row
            if mulai and selesai:
                dt_mulai = datetime.combine(tanggal, mulai)
                dt_selesai = datetime.combine(tanggal, selesai)
                durasi_detik = (dt_selesai - dt_mulai).total_seconds()
                if durasi_detik < 0: durasi_detik += 86400
                h = int(durasi_detik // 3600)
                m = int((durasi_detik % 3600) // 60)
                durasi_str = f"{h}j {m}m"
            else: 
                durasi_str = "-"
            writer.writerow([tanggal, mulai.strftime('%H:%M') if mulai else '-', selesai.strftime('%H:%M') if selesai else '-', durasi_str, awal, akhir, pakai, sisa, petugas])
            
        output.seek(0)
        filename = f"genset_log_{bulan}.csv"
        return Response(output.getvalue(), mimetype="text/csv", 
                       headers={"Content-Disposition": f"attachment;filename={filename}"})
    except Exception as e:
        return f"Error: {e}", 500

def is_libur(tanggal):
    if tanggal.weekday() == 6: return True, "Minggu"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,))
    result = cur.fetchone()
    conn.close()
    return (True, "Libur Nasional") if result else (False, None)

def get_keyboard(status):
    buttons = []
    if status == 'belum':
        buttons.append([InlineKeyboardButton("✅ Datang", callback_data='datang'), InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin')])
    elif status in ['datang', 'lembur']:
        buttons.append([InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin'), InlineKeyboardButton("🤒 Sakit", callback_data='sakit')])
    buttons.append([InlineKeyboardButton("📊 Rekap", callback_data='rekap'), InlineKeyboardButton("📋 Saya", callback_data='saya'), InlineKeyboardButton("⛽ Genset", callback_data='genset')])
    buttons.append([InlineKeyboardButton("⬇️ Download", callback_data='download'), InlineKeyboardButton("👑 Admin", callback_data='admin'), InlineKeyboardButton("❌", callback_data='noop')])
    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if not data: return 'belum'
    if data[2] in ['izin', 'sakit', 'cuti', 'lembur']: return data[2]
    return 'datang' if data[0] and not data[1] else 'selesai' if data[0] and data[1] else 'belum'

def simpan_datang(user_id, nama):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()
    libur, jenis_libur = is_libur(hari_ini)
    status = 'lembur' if libur else 'hadir'
    try:
        cur.execute("INSERT INTO absensi (user_id, nama, tanggal, jam_datang, status, telat, alasan) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO NOTHING", (user_id, nama, hari_ini, jam_sekarang, status, telat, jenis_libur))
        conn.commit()
        return True, telat, libur, jenis_libur
    except: return False, False, False, None
    finally: conn.close()

def simpan_pulang(user_id):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    cur.execute("UPDATE absensi SET jam_pulang=%s WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL", (jam_sekarang, user_id, hari_ini))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated

def simpan_izin(user_id, nama, status, alasan):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("INSERT INTO absensi (user_id, nama, tanggal, status, alasan) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO UPDATE SET status=%s, alasan=%s", (user_id, nama, hari_ini, status, alasan, status, alasan))
    conn.commit()
    conn.close()

def get_rekap_bulanan(user_id, bulan_str=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(WIB)
    tahun, bulan = map(int, bulan_str.split('-')) if bulan_str else (now.year, now.month)
    cur.execute("SELECT COUNT(*), COALESCE(EXTRACT(EPOCH FROM SUM(jam_pulang - jam_datang)), 0), SUM(CASE WHEN telat THEN 1 ELSE 0 END) FROM absensi WHERE user_id=%s AND EXTRACT(MONTH FROM tanggal)=%s AND EXTRACT(YEAR FROM tanggal)=%s AND jam_pulang IS NOT NULL AND status IN ('hadir','lembur')", (user_id, bulan, tahun))
    data = cur.fetchone()
    conn.close()
    hari_hadir, total_detik, total_telat = data[0] or 0, int(data[1] or 0), data[2] or 0
    h, m = divmod(total_detik, 3600)
    total_jam_fmt = f"{h:02d}j {m//60:02d}m"
    rata_fmt = f"{(total_detik//hari_hadir//3600):02d}j {((total_detik//hari_hadir)%3600//60):02d}m" if hari_hadir > 0 else "00j 00m"
    return hari_hadir, total_jam_fmt, total_telat, rata_fmt

async def genset_mulai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jam = update.message.text.strip()
    try:
        datetime.strptime(jam, '%H:%M')
        context.user_data['jam_mulai'] = jam
        await update.message.reply_text("2/3 BBM awal %? Contoh: 90")
        return GEN_BBM_AWAL
    except:
        await update.message.reply_text("Format jam salah. Contoh: 08:30")
        return GEN_MULAI

async def genset_bbm_awal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bbm = int(update.message.text.strip())
        if not 0 <= bbm <= 100: raise ValueError
        context.user_data['bbm_awal'] = bbm
        await update.message.reply_text("3/3 BBM akhir %? Contoh: 60\nKetik /cancel buat batal")
        return GEN_BBM_AKHIR
    except:
        await update.message.reply_text("Isi angka 0-100 aja bang")
        return GEN_BBM_AWAL

async def genset_bbm_akhir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bbm_akhir = int(update.message.text.strip())
        bbm_awal = context.user_data['bbm_awal']
        if bbm_akhir > bbm_awal:
            await update.message.reply_text("BBM akhir gaboleh lebih gede dari awal 😅")
            return GEN_BBM_AKHIR
        pemakaian = bbm_awal - bbm_akhir
        sisa = bbm_akhir
        jam_selesai = datetime.now(WIB).strftime('%H:%M')
        tanggal = datetime.now(WIB).date()
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO genset_log (tanggal, jam_mulai, jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, petugas, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (tanggal, context.user_data['jam_mulai'], jam_selesai, bbm_awal, bbm_akhir, pemakaian, sisa, nama, user_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ *Genset Dicatat*\n📅 {tanggal}\n⏰ {context.user_data['jam_mulai']} - {jam_selesai}\n⛽ {bbm_awal}% → {bbm_akhir}%\n🔥 Pakai: {pemakaian}%\n💧 Sisa: {sisa}%\n👤 {nama}\n\nKetik /start buat balik ke menu", parse_mode='Markdown')
        context.user_data.clear()
        return ConversationHandler.END
    except:
        await update.message.reply_text("Isi angka 0-100")
        return GEN_BBM_AKHIR

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Dibatalkan. Ketik /start buat buka menu", reply_markup=get_keyboard(cek_absen(update.effective_user.id)))
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)
    teks = f"🤖 *Absen & Genset*\n📅 {hari_ini}\n\n"
    teks += "Waktunya absen datang" if status == 'belum' else "✅ Sudah absen datang\nSilakan absen pulang" if status in ['datang', 'lembur'] else f"📝 Status hari ini: {status}" if status in ['izin', 'sakit', 'cuti'] else "Absensi hari ini sudah selesai"
    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    status = cek_absen(user_id)
    wib = datetime.now(WIB)
    jam = wib.strftime('%H:%M:%S')

    if button_id == 'datang':
        if status!= 'belum': await query.answer("Sudah absen datang", show_alert=True); return
        success, telat, libur, jenis_libur = simpan_datang(user_id, nama)
        if success:
            teks = f"✅ Absen datang berhasil!\nWaktu: {jam}"
            if libur: teks += f"\n💜 *LEMBUR* - {jenis_libur}"
            if telat: teks += "\n⚠️ *Kamu telat!*"
            teks += "\n\nSilakan absen pulang"
            await query.edit_message_text(text=teks, reply_markup=get_keyboard('datang'), parse_mode='Markdown')
    elif button_id == 'pulang':
        if status not in ['datang', 'lembur']: await query.answer("Belum absen datang", show_alert=True); return
        if simpan_pulang(user_id):
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT jam_datang, jam_pulang, status, EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, wib.date()))
            data = cur.fetchone()
            conn.close()
            jam_datang_str, jam_pulang_str, status_akhir = data[0].strftime('%H:%M:%S'), data[1].strftime('%H:%M:%S'), data[2]
            total_detik = int(data[3]) if data[3] else 0
            h, m = divmod(total_detik, 3600)
            total_jam = f"{h:02d}j {m//60:02d}m"
            teks = f"🤖 *Absen Selesai*\n📅 {wib.strftime('%d/%m/%Y')}\n━━━━━━━━━━━━━━\n✅ Datang: {jam_datang_str}\n🚪 Pulang: {jam_pulang_str}\n⏱️ Total: {total_jam}\n"
            if status_akhir == 'lembur': teks += f"💜 Status: LEMBUR\n"
            teks += f"Selesai. Ketik /start buat buka menu"
            await query.edit_message_text(text=teks, parse_mode='Markdown', reply_markup=get_keyboard('selesai'))
    elif button_id == 'genset':
        await query.answer()
        await query.edit_message_text("⛽ *Catat Penggunaan Genset*\n\n1/3 Jam mulai? Ketik 08:30\nKetik /cancel buat batal", parse_mode='Markdown')
        context.user_data.clear()
        return GEN_MULAI
    elif button_id in ['izin', 'sakit', 'cuti']:
        context.user_data['status_izin'] = button_id
        await query.edit_message_text(f"Kirim alasan {button_id}:", reply_markup=get_keyboard(status))
        return REASON
    elif button_id == 'rekap':
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id)
        bulan_nama = datetime.now(WIB).strftime('%B %Y')
        teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))
    elif button_id == 'noop':
        await query.edit_message_text("Menu ditutup. Ketik /start", reply_markup=None)

async def terima_alasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    status = context.user_data.get('status_izin')
    if status:
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        simpan_izin(user_id, nama, status, teks)
        context.user_data.pop('status_izin', None)
        await update.message.reply_text(f"✅ Status {status} tersimpan", reply_markup=get_keyboard(cek_absen(user_id)))
        return ConversationHandler.END
    return ConversationHandler.END

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN/SUPABASE_URL kosong")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS absensi (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, nama TEXT, tanggal DATE NOT NULL, jam_datang TIME, jam_pulang TIME, status TEXT DEFAULT 'hadir', alasan TEXT, telat BOOLEAN DEFAULT false, UNIQUE(user_id, tanggal))")
    cur.execute("CREATE TABLE IF NOT EXISTS libur_nasional (tanggal DATE PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS genset_log (id SERIAL PRIMARY KEY, tanggal DATE NOT NULL, jam_mulai TIME NOT NULL, jam_selesai TIME, bbm_awal INTEGER NOT NULL, bbm_akhir INTEGER, pemakaian INTEGER, sisa INTEGER, petugas TEXT, user_id BIGINT)")
    conn.commit()
    conn.close()
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    genset_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            GEN_MULAI: [CommandHandler('cancel', cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, genset_mulai)],
            GEN_BBM_AWAL: [CommandHandler('cancel', cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, genset_bbm_awal)],
            GEN_BBM_AKHIR: [CommandHandler('cancel', cancel), MessageHandler(filters.TEXT & ~filters.COMMAND, genset_bbm_akhir)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, terima_alasan)]},
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(genset_conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot jalan... Absen + Genset + Grafik + Durasi")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
