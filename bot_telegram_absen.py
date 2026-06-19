import os
import threading
import psycopg2
import csv
import io
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

KANTOR_LAT = float(os.getenv("KANTOR_LAT"))
KANTOR_LON = float(os.getenv("KANTOR_LON"))
RADIUS_METER = int(os.getenv("RADIUS_METER", "500"))

REASON = 1
user_states = {} # Ganti ConversationHandler pakai dict sederhana

@app_flask.route('/')
def home():
    try:
        tanggal = request.args.get('tanggal')
        with get_db() as conn:
            cur = conn.cursor()
            if tanggal:
                cur.execute("""
                    SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
                    EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
                    CASE WHEN jam_datang > TIME '09:00:00' THEN true ELSE false END as telat_flag
                    FROM absensi WHERE tanggal=%s ORDER BY jam_datang DESC
                """, (tanggal,))
            else:
                cur.execute("""
                    SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
                    EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
                    CASE WHEN jam_datang > TIME '09:00:00' THEN true ELSE false END as telat_flag
                    FROM absensi ORDER BY tanggal DESC, jam_datang DESC LIMIT 100
                """)
            data = cur.fetchall()

        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Data Absensi</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{{font-family:Arial,sans-serif;padding:20px;background:#f5f5f5;}}
        h2{{text-align:center;}}table{{width:100%;border-collapse:collapse;background:white;box-shadow:0 2px 5px rgba(0,0,0,0.1);}}
        th,td{{padding:12px;text-align:left;border-bottom:1px solid #ddd;}}th{{background:#4CAF50;color:white;}}
        tr:hover{{background:#f1f1f1;}}.telat{{background:#ffebee;color:#c62828;font-weight:bold;}}
       .status-izin{{color:orange;}}.status-sakit{{color:red;}}.status-cuti{{color:blue;}}
       .status-lembur{{color:purple;font-weight:bold;}}.filter{{text-align:center;margin-bottom:20px;}}
        input,button{{padding:8px;font-size:16px;}}</style></head><body>
        <h2>📋 Data Absensi</h2><div class="filter"><form method="get">
        <input type="date" name="tanggal" value="{tanggal if tanggal else ''}">
        <button type="submit">Filter</button><a href="/"><button type="button">Reset</button></a></form></div>
        <table><thead><tr><th>Nama</th><th>Tanggal</th><th>Datang</th><th>Pulang</th><th>Status</th><th>Alasan</th><th>Total Jam</th></tr></thead><tbody>"""

        for row in data:
            nama, tanggal, datang, pulang, status, alasan, telat_db, total_detik, telat_flag = row
            row_class = "telat" if telat_flag else ""
            status_class = f"status-{status}" if status else ""
            total_detik = int(total_detik) if total_detik else 0
            h = total_detik // 3600
            m = (total_detik % 3600) // 60
            total_jam = f"{h:02d}j {m:02d}m" if total_detik > 0 else "-"
            html += f"""<tr class="{row_class}"><td>{nama}</td><td>{tanggal}</td>
            <td>{datang.strftime('%H:%M:%S') if datang else '-'}</td>
            <td>{pulang.strftime('%H:%M:%S') if pulang else '-'}</td>
            <td class="{status_class}">{status or 'hadir'}</td>
            <td>{alasan or '-'}</td><td>{total_jam}</td></tr>"""

        html += "</tbody></table></body></html>"
        return html
    except Exception as e:
        return f"<h2>Error</h2><pre>{e}</pre>", 500

from contextlib import contextmanager

@contextmanager
def get_db():
    conn = psycopg2.connect(os.getenv("SUPABASE_URL"), connect_timeout=10)
    try:
        yield conn
    finally:
        conn.close()

def is_libur(tanggal):
    if tanggal.weekday() == 6:
        return True, "Minggu"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,))
        return bool(cur.fetchone()), "Libur Nasional" if cur.fetchone() else None

def hitung_jarak_meter(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def get_keyboard(status):
    buttons = []
    if status == 'belum':
        buttons.append([InlineKeyboardButton("📍 Absen Datang", callback_data='minta_lokasi_datang'), InlineKeyboardButton("📝 Izin", callback_data='izin')])
    elif status in ['datang', 'lembur']:
        buttons.append([InlineKeyboardButton("📍 Absen Pulang", callback_data='minta_lokasi_pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin'), InlineKeyboardButton("🤒 Sakit", callback_data='sakit')])
    buttons.append([InlineKeyboardButton("📊 Rekap", callback_data='rekap'), InlineKeyboardButton("📋 Saya", callback_data='saya'), InlineKeyboardButton("👥 Tim", callback_data='tim')])
    buttons.append([InlineKeyboardButton("⬇️ Download", callback_data='download'), InlineKeyboardButton("👑 Admin", callback_data='admin'), InlineKeyboardButton("❌", callback_data='noop')])
    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        cur.execute("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
        data = cur.fetchone()
    if not data: return 'belum'
    if data[2] in ['izin', 'sakit', 'cuti', 'lembur']: return data[2]
    if data[0] and not data[1]: return 'datang'
    if data[0] and data[1]: return 'selesai'
    return 'belum'

def simpan_datang(user_id, nama, lat, lon):
    with get_db() as conn:
        cur = conn.cursor()
        wib = datetime.now(WIB)
        hari_ini = wib.date()
        jam_sekarang = wib.time()
        telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()
        libur, jenis_libur = is_libur(hari_ini)
        status = 'lembur' if libur else 'hadir'
        cur.execute("INSERT INTO absensi (user_id, nama, tanggal, jam_datang, lat_datang, lon_datang, status, telat, alasan) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (user_id, nama, hari_ini, jam_sekarang, lat, lon, status, telat, jenis_libur))
        conn.commit()
        return True, telat, libur, jenis_libur

def simpan_pulang(user_id, lat, lon):
    with get_db() as conn:
        cur = conn.cursor()
        wib = datetime.now(WIB)
        cur.execute("UPDATE absensi SET jam_pulang=%s, lat_pulang=%s, lon_pulang=%s WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL",
                    (wib.time(), lat, lon, user_id, wib.date()))
        updated = cur.rowcount > 0
        conn.commit()
        return updated

def simpan_izin(user_id, nama, status, alasan):
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        cur.execute("INSERT INTO absensi (user_id, nama, tanggal, status, alasan) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id, tanggal) DO UPDATE SET status=%s, alasan=%s",
                    (user_id, nama, hari_ini, status, alasan, status, alasan))
        conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states.pop(user_id, None) # Reset state
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)
    teks = f"🤖 *Absensi Karyawan*\n📅 {hari_ini}\n\n"
    if status == 'belum': teks += "Waktunya absen datang"
    elif status in ['datang', 'lembur']: teks += "✅ Sudah absen datang\nSilakan absen pulang"
    elif status in ['izin', 'sakit', 'cuti']: teks += f"📝 Status hari ini: {status}"
    else:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, datetime.now(WIB).date()))
            data = cur.fetchone()
        teks += f"✅ Datang: {data[0].strftime('%H:%M:%S')}\n🚪 Pulang: {data[1].strftime('%H:%M:%S')}\n\nSelesai"
    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    nama = query.from_user.first_name
    status = cek_absen(user_id)

    # Handler spesifik absen harus di atas
    if data == 'minta_lokasi_datang':
        user_states[user_id] = 'menunggu_lokasi_datang'
        keyboard = ReplyKeyboardMarkup([[KeyboardButton("📍 Kirim Lokasi Saya", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
        await query.edit_message_text(f"Kirim lokasi Anda. Radius {RADIUS_METER}m dari kantor.", reply_markup=keyboard)
        return

    if data == 'minta_lokasi_pulang':
        user_states[user_id] = 'menunggu_lokasi_pulang'
        keyboard = ReplyKeyboardMarkup([[KeyboardButton("📍 Kirim Lokasi Saya", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
        await query.edit_message_text(f"Kirim lokasi Anda. Radius {RADIUS_METER}m dari kantor.", reply_markup=keyboard)
        return

    # Handler lain
    if data == 'izin':
        user_states[user_id] = 'menunggu_alasan_izin'
        await query.edit_message_text("Kirim alasan izin:")
    elif data == 'sakit':
        user_states[user_id] = 'menunggu_alasan_sakit'
        await query.edit_message_text("Kirim alasan sakit:")
    elif data == 'rekap':
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id)
        bulan_nama = datetime.now(WIB).strftime('%B %Y')
        teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))
    elif data == 'saya':
        await saya_command(update, context)
    elif data == 'tim':
        await tim_command(update, context)
    elif data == 'download':
        bulan_ini = datetime.now(WIB).strftime('%Y-%m')
        await query.edit_message_text(f"📥 `/export {bulan_ini}`")
    elif data == 'admin':
        await admin_command(update, context)
    elif data == 'admin_belum':
        if user_id!= ADMIN_ID: return
        hari_ini = datetime.now(WIB).date()
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT nama FROM absensi WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin','sakit','cuti','lembur')", (hari_ini,))
            belum = cur.fetchall()
        teks = "❌ Belum Absen:\n" + "\n".join([f"- {n[0]}" for n in belum]) if belum else "✅ Semua sudah absen"
        await query.edit_message_text(teks, parse_mode='Markdown')
    elif data == 'admin_libur':
        if user_id!= ADMIN_ID: return
        user_states[user_id] = 'menunggu_tanggal_libur'
        await query.edit_message_text("Kirim tanggal libur format YYYY-MM-DD:")
    elif data == 'noop':
        await query.edit_message_text("Menu ditutup. Ketik /start")

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state: return

    lokasi = update.message.location
    jarak = hitung_jarak_meter(KANTOR_LAT, KANTOR_LON, lokasi.latitude, lokasi.longitude)
    nama = update.effective_user.first_name

    if jarak > RADIUS_METER:
        await update.message.reply_text(f"❌ Gagal. Jarak {int(jarak)}m. Maks {RADIUS_METER}m.", reply_markup=ReplyKeyboardRemove())
        user_states.pop(user_id, None)
        return

    if state == 'menunggu_lokasi_datang':
        if cek_absen(user_id)!= 'belum':
            await update.message.reply_text("Sudah absen datang.", reply_markup=ReplyKeyboardRemove())
        else:
            success, telat, libur, jenis_libur = simpan_datang(user_id, nama, lokasi.latitude, lokasi.longitude)
            teks = f"✅ Datang berhasil!\nJarak: {int(jarak)}m"
            if libur: teks += f"\n💜 LEMBUR - {jenis_libur}"
            if telat: teks += "\n⚠️ Telat!"
            await update.message.reply_text(teks, reply_markup=ReplyKeyboardRemove())

    elif state == 'menunggu_lokasi_pulang':
        if cek_absen(user_id) not in ['datang', 'lembur']:
            await update.message.reply_text("Belum absen datang.", reply_markup=ReplyKeyboardRemove())
        else:
            success = simpan_pulang(user_id, lokasi.latitude, lokasi.longitude)
            await update.message.reply_text(f"🚪 Pulang berhasil!\nJarak: {int(jarak)}m" if success else "Gagal", reply_markup=ReplyKeyboardRemove())

    user_states.pop(user_id, None)
    await start(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    teks = update.message.text.strip()

    if state == 'menunggu_alasan_izin':
        simpan_izin(user_id, update.effective_user.first_name, 'izin', teks)
        user_states.pop(user_id, None)
        await update.message.reply_text(f"✅ Izin tersimpan: {teks}", reply_markup=get_keyboard(cek_absen(user_id)))
    elif state == 'menunggu_alasan_sakit':
        simpan_izin(user_id, update.effective_user.first_name, 'sakit', teks)
        user_states.pop(user_id, None)
        await update.message.reply_text(f"✅ Sakit tersimpan: {teks}", reply_markup=get_keyboard(cek_absen(user_id)))
    elif state == 'menunggu_tanggal_libur' and user_id == ADMIN_ID:
        try:
            tanggal = datetime.strptime(teks, '%Y-%m-%d').date()
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("INSERT INTO libur_nasional (tanggal) VALUES (%s) ON CONFLICT DO NOTHING", (tanggal,))
                conn.commit()
            await update.message.reply_text(f"✅ {tanggal} ditandai libur", reply_markup=get_keyboard(cek_absen(user_id)))
        except: await update.message.reply_text("Format salah. YYYY-MM-DD")
        user_states.pop(user_id, None)

async def rekap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bulan_str = context.args[0] if context.args else None
    try:
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id, bulan_str)
        bulan_nama = datetime.strptime(bulan_str, '%Y-%m').strftime('%B %Y') if bulan_str else datetime.now(WIB).strftime('%B %Y')
    except:
        await update.message.reply_text("Format: `/rekap 2025-10`", parse_mode='Markdown')
        return
    teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
    await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(cek_absen(user_id)))

async def saya_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    with get_db() as conn:
        cur = conn.cursor()
        tujuh_hari_lalu = datetime.now(WIB).date() - timedelta(days=7)
        cur.execute("SELECT tanggal, jam_datang, jam_pulang, status, alasan, EXTRACT(EPOCH FROM jam_pulang - jam_datang) FROM absensi WHERE user_id=%s AND tanggal >= %s ORDER BY tanggal DESC", (user_id, tujuh_hari_lalu))
        data = cur.fetchall()
    if not data:
        await update.message.reply_text("Belum ada data 7 hari terakhir.", reply_markup=get_keyboard(cek_absen(user_id)))
        return
    teks = "*📋 7 Hari Terakhir*\n\n"
    for tanggal, datang, pulang, status, alasan, total_detik in data:
        total_detik = int(total_detik) if total_detik else 0
        h, m = total_detik // 3600, (total_detik % 3600) // 60
        total_jam = f"{h:02d}j {m:02d}m" if total_detik > 0 else "-"
        teks += f"*{tanggal}*\nDatang: {datang.strftime('%H:%M') if datang else '-'}\nPulang: {pulang.strftime('%H:%M') if pulang else '-'}\nStatus: {status or 'hadir'}\n{('Alasan: '+alasan+'\n') if alasan else ''}{('Total: '+total_jam+'\n') if total_jam!='-' else ''}\n"
    await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(cek_absen(user_id)))

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args)!= 1: await update.message.reply_text("Format: `/export 2025-10`"); return
    tahun, bulan = map(int, context.args[0].split('-'))
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT tanggal, jam_datang, jam_pulang, status, alasan, EXTRACT(EPOCH FROM jam_pulang - jam_datang) FROM absensi WHERE user_id=%s AND EXTRACT(MONTH FROM tanggal)=%s AND EXTRACT(YEAR FROM tanggal)=%s ORDER BY tanggal", (user_id, bulan, tahun))
        data = cur.fetchall()
    if not data: await update.message.reply_text("Tidak ada data"); return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tanggal','Datang','Pulang','Status','Alasan','Total Jam'])
    for row in data:
        tanggal, datang, pulang, status, alasan, total_detik = row
        total_detik = int(total_detik) if total_detik else 0
        h, m = total_detik // 3600, (total_detik % 3600) // 60
        writer.writerow([tanggal, datang, pulang, status, alasan, f"{h:02d}j {m:02d}m" if total_detik else "-"])
    output.seek(0)
    await update.message.reply_document(InputFile(io.BytesIO(output.getvalue().encode()), filename=f"absen_{context.args[0]}.csv"))

async def tim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        cur.execute("SELECT nama, jam_datang, telat, status FROM absensi WHERE tanggal=%s AND jam_datang IS NOT NULL ORDER BY jam_datang", (hari_ini,))
        hadir = cur.fetchall()
        cur.execute("SELECT nama FROM absensi WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin','sakit','cuti','lembur')", (hari_ini,))
        belum = cur.fetchall()
    teks = f"*👥 Tim - {hari_ini}*\n\n✅ Hadir ({len(hadir)}):\n" + "\n".join([f"- {n}: {j.strftime('%H:%M')}{' [TELAT]' if t else ''}{' [LEMBUR]' if s=='lembur' else ''}" for n,j,t,s in hadir])
    teks += f"\n\n❌ Belum ({len(belum)}):\n" + "\n".join([f"- {n[0]}" for n in belum])
    await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(cek_absen(update.effective_user.id)))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!= ADMIN_ID: await update.message.reply_text("❌ Bukan admin"); return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Belum Absen", callback_data='admin_belum')], [InlineKeyboardButton("📅 Tambah Libur", callback_data='admin_libur')], [InlineKeyboardButton("❌ Tutup", callback_data='noop')]])
    await update.message.reply_text("👑 Admin Panel", reply_markup=keyboard, parse_mode='Markdown')

def get_rekap_bulanan(user_id, bulan_str=None):
    with get_db() as conn:
        cur = conn.cursor()
        now = datetime.now(WIB)
        tahun, bulan = map(int, bulan_str.split('-')) if bulan_str else (now.year, now.month)
        cur.execute("SELECT COUNT(*), COALESCE(EXTRACT(EPOCH FROM SUM(jam_pulang - jam_datang)),0), SUM(CASE WHEN telat THEN 1 ELSE 0 END) FROM absensi WHERE user_id=%s AND EXTRACT(MONTH FROM tanggal)=%s AND EXTRACT(YEAR FROM tanggal)=%s AND jam_pulang IS NOT NULL AND status IN ('hadir','lembur')", (user_id, bulan, tahun))
        hari_hadir, total_detik, total_telat = cur.fetchone()
    hari_hadir = hari_hadir or 0
    total_detik = int(total_detik) if total_detik else 0
    total_telat = total_telat or 0
    h, m = total_detik // 3600, (total_detik % 3600) // 60
    rata = f"{total_detik//hari_hadir//3600:02d}j {(total_detik//hari_hadir%3600)//60:02d}m" if hari_hadir > 0 else "00j 00m"
    return hari_hadir, f"{h:02d}j {m:02d}m", total_telat, rata

def run_flask():
    app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def main():
    TOKEN = os.getenv("TOKEN")
    if not TOKEN or not os.getenv("SUPABASE_URL") or not os.getenv("KANTOR_LAT") or not os.getenv("KANTOR_LON"):
        print("Error: TOKEN, SUPABASE_URL, KANTOR_LAT, KANTOR_LON wajib diisi")
        return

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS absensi (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, nama TEXT, tanggal DATE NOT NULL, jam_datang TIME, jam_pulang TIME, lat_datang DOUBLE PRECISION, lon_datang DOUBLE PRECISION, lat_pulang DOUBLE PRECISION, lon_pulang DOUBLE PRECISION, status TEXT DEFAULT 'hadir', alasan TEXT, telat BOOLEAN DEFAULT false, UNIQUE(user_id, tanggal))")
        cur.execute("CREATE TABLE IF NOT EXISTS libur_nasional (tanggal DATE PRIMARY KEY)")
        conn.commit()

    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()

    # URUTAN KRITIS: spesifik dulu, umum belakangan
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rekap", rekap_command))
    app.add_handler(CommandHandler("saya", saya_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("tim", tim_command))
    app.add_handler(CommandHandler("admin", admin_command))

    print("Bot berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
