import os
import threading
import psycopg2
import csv
import io
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

KANTOR_LAT = float(os.getenv("KANTOR_LAT", "-6.9667"))
KANTOR_LON = float(os.getenv("KANTOR_LON", "110.4167"))
RADIUS_METER = int(os.getenv("RADIUS_METER", "500"))

def query_db(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if commit:
                conn.commit()
                return cur.rowcount
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        conn.close()

@app_flask.route('/')
def home():
    try:
        tanggal = request.args.get('tanggal')
        wib_now = datetime.now(WIB)

        if tanggal:
            sql = """
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
                EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
                CASE WHEN jam_datang > TIME '09:00:00' THEN true ELSE false END as telat_flag
                FROM absensi WHERE tanggal=%s ORDER BY jam_datang DESC
            """
            data = query_db(sql, (tanggal,), fetchall=True)
        else:
            sql = """
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
                EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
                CASE WHEN jam_datang > TIME '09:00:00' THEN true ELSE false END as telat_flag
                FROM absensi ORDER BY tanggal DESC, jam_datang DESC LIMIT 100
            """
            data = query_db(sql, fetchall=True)

        if data is None:
            return "<h2>Error Koneksi DB</h2>", 500

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Data Absensi</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
                h2 {{ text-align: center; }}
                table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #4CAF50; color: white; }}
                tr:hover {{ background: #f1f1f1; }}
              .telat {{ background: #ffebee; color: #c62828; font-weight: bold; }}
              .status-izin {{ color: orange; }}
              .status-sakit {{ color: red; }}
              .status-cuti {{ color: blue; }}
              .status-lembur {{ color: purple; font-weight: bold; }}
              .filter {{ text-align: center; margin-bottom: 20px; }}
                input, button {{ padding: 8px; font-size: 16px; }}
                @media (max-width: 600px) {{
                    table, thead, tbody, th, td, tr {{ display: block; }}
                    th {{ display: none; }}
                    td {{ border: none; position: relative; padding-left: 50%; }}
                    td:before {{ content: attr(data-label); position: absolute; left: 10px; font-weight: bold; }}
                }}
            </style>
        </head>
        <body>
            <h2>📋 Data Absensi</h2>
            <div class="filter">
                <form method="get">
                    <input type="date" name="tanggal" value="{tanggal if tanggal else ''}">
                    <button type="submit">Filter</button>
                    <a href="/"><button type="button">Reset</button></a>
                </form>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Nama</th><th>Tanggal</th><th>Datang</th><th>Pulang</th>
                        <th>Status</th><th>Alasan</th><th>Total Jam</th>
                    </tr>
                </thead>
                <tbody>
        """

        for row in data:
            nama, tanggal, datang, pulang, status, alasan, telat_db, total_detik, telat_flag = row
            row_class = "telat" if telat_flag else ""
            status_class = f"status-{status}" if status else ""
            total_detik = int(total_detik) if total_detik else 0
            h, m = divmod(total_detik, 3600)
            m = m // 60
            total_jam = f"{h:02d}j {m:02d}m" if total_detik > 0 else "-"

            html += f"""
            <tr class="{row_class}">
                <td data-label="Nama">{nama}</td>
                <td data-label="Tanggal">{tanggal}</td>
                <td data-label="Datang">{datang.strftime('%H:%M:%S') if datang else '-'}</td>
                <td data-label="Pulang">{pulang.strftime('%H:%M:%S') if pulang else '-'}</td>
                <td data-label="Status" class="{status_class}">{status or 'hadir'}</td>
                <td data-label="Alasan">{alasan or '-'}</td>
                <td data-label="Total Jam">{total_jam}</td>
            </tr>
            """

        html += "</tbody></table></body></html>"
        return html

    except Exception as e:
        return f"<h2>Error Server</h2><pre>{e}</pre>", 500

def get_db():
    return psycopg2.connect(os.getenv("SUPABASE_URL"))

def is_libur(tanggal):
    if tanggal.weekday() == 6:
        return True, "Minggu"
    result = query_db("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,), fetchone=True)
    return (True, "Libur Nasional") if result else (False, None)

def hitung_jarak(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_keyboard(status, step=None):
    if step == 'lokasi':
        keyboard = [[KeyboardButton("📍 Kirim Lokasi", request_location=True)]]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    main_btn = []
    if status == 'belum':
        main_btn = [InlineKeyboardButton("✅ Datang", callback_data='datang'), InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin')]
    elif status in ['datang', 'lembur']:
        main_btn = [InlineKeyboardButton("🚪 Pulang", callback_data='pulang'), InlineKeyboardButton("📝 Izin", callback_data='izin'), InlineKeyboardButton("🤒 Sakit", callback_data='sakit')]

    buttons = [main_btn] if main_btn else []
    buttons += [
        [InlineKeyboardButton("📊 Rekap", callback_data='rekap'), InlineKeyboardButton("📋 Saya", callback_data='saya'), InlineKeyboardButton("👥 Tim", callback_data='tim')],
        [InlineKeyboardButton("⬇️ Download", callback_data='download'), InlineKeyboardButton("👑 Admin", callback_data='admin'), InlineKeyboardButton("❌", callback_data='noop')]
    ]
    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    hari_ini = datetime.now(WIB).date()
    data = query_db("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini), fetchone=True)
    if not data:
        return 'belum'
    jam_datang, jam_pulang, status = data
    if status in ['izin', 'sakit', 'cuti', 'lembur']:
        return status
    return 'datang' if jam_datang and not jam_pulang else 'selesai' if jam_datang and jam_pulang else 'belum'

def simpan_datang(user_id, nama, lat=None, lon=None, foto_id=None):
    wib_now = datetime.now(WIB)
    hari_ini = wib_now.date()
    jam_sekarang = wib_now.time()
    telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()
    libur, jenis_libur = is_libur(hari_ini)
    status = 'lembur' if libur else 'hadir'

    sql = """
        INSERT INTO absensi (user_id, nama, tanggal, jam_datang, lat_datang, lon_datang, foto_datang, status, telat, alasan)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, tanggal) DO UPDATE SET jam_datang=%s, lat_datang=%s, lon_datang=%s, foto_datang=%s
    """
    params = (user_id, nama, hari_ini, jam_sekarang, lat, lon, foto_id, status, telat, jenis_libur, jam_sekarang, lat, lon, foto_id)
    query_db(sql, params, commit=True)
    return True, telat, libur, jenis_libur

def simpan_pulang(user_id, lat=None, lon=None, foto_id=None):
    wib_now = datetime.now(WIB)
    hari_ini = wib_now.date()
    jam_sekarang = wib_now.time()
    sql = "UPDATE absensi SET jam_pulang=%s, lat_pulang=%s, lon_pulang=%s, foto_pulang=%s WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL"
    updated = query_db(sql, (jam_sekarang, lat, lon, foto_id, user_id, hari_ini), commit=True)
    return updated > 0 if updated else False

def simpan_izin(user_id, nama, status, alasan):
    hari_ini = datetime.now(WIB).date()
    sql = """
        INSERT INTO absensi (user_id, nama, tanggal, status, alasan)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id, tanggal) DO UPDATE SET status=%s, alasan=%s
    """
    query_db(sql, (user_id, nama, hari_ini, status, alasan, status, alasan), commit=True)

def get_rekap_bulanan(user_id, bulan_str=None):
    now = datetime.now(WIB)
    tahun, bulan = map(int, bulan_str.split('-')) if bulan_str else (now.year, now.month)

    sql = """
        SELECT COUNT(*) as hari_hadir,
               COALESCE(EXTRACT(EPOCH FROM SUM(jam_pulang - jam_datang)), 0) as total_detik,
               SUM(CASE WHEN telat THEN 1 ELSE 0 END) as total_telat
        FROM absensi WHERE user_id=%s AND EXTRACT(MONTH FROM tanggal)=%s AND EXTRACT(YEAR FROM tanggal)=%s
        AND jam_pulang IS NOT NULL AND status IN ('hadir', 'lembur')
    """
    data = query_db(sql, (user_id, bulan, tahun), fetchone=True)
    if not data:
        return 0, "00j 00m", 0, "00j 00m"

    hari_hadir, total_detik, total_telat = data[0] or 0, int(data[1] or 0), data[2] or 0
    h, m = divmod(total_detik, 3600)
    total_jam_fmt = f"{h:02d}j {m//60:02d}m"
    rata_fmt = "00j 00m"
    if hari_hadir > 0:
        rh, rm = divmod(total_detik // hari_hadir, 3600)
        rata_fmt = f"{rh:02d}j {rm//60:02d}m"
    return hari_hadir, total_jam_fmt, total_telat, rata_fmt

def get_data_saya(user_id):
    hari_ini = datetime.now(WIB).date()
    tujuh_hari_lalu = hari_ini - timedelta(days=7)
    sql = """
        SELECT tanggal, jam_datang, jam_pulang, status, alasan,
        EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik
        FROM absensi WHERE user_id=%s AND tanggal >= %s ORDER BY tanggal DESC
    """
    return query_db(sql, (user_id, tujuh_hari_lalu), fetchall=True) or []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear() # reset state manual
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    wib_now = datetime.now(WIB)
    hari_ini = wib_now.strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)

    teks = f"🤖 *Absen*\n📅 {hari_ini}\n\n"
    if status == 'belum':
        teks += "Waktunya absen datang"
    elif status in ['datang', 'lembur']:
        teks += "✅ Sudah absen datang\nSilakan absen pulang"
    elif status in ['izin', 'sakit', 'cuti']:
        teks += f"📝 Status hari ini: {status}"
    else:
        data = query_db("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, wib_now.date()), fetchone=True)
        if data:
            teks += f"✅ Datang: {data[0].strftime('%H:%M:%S')}\n"
            teks += f"🚪 Pulang: {data[1].strftime('%H:%M:%S')}\n\n"
            teks += "Absensi hari ini sudah selesai"

    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    status = cek_absen(user_id)

    # Reset state kalau pencet tombol
    if button_id not in ['noop']:
        context.user_data.clear()
        if button_id == 'datang':
    if button_id == 'datang':
    if status!= 'belum':
        await query.answer("Kamu sudah absen datang", show_alert=True)
        return
        context.user_data['aksi'] = 'datang'
        context.user_data['step'] = 'tunggu_lokasi'
        keyboard = get_keyboard(status, step='lokasi')
        await query.delete_message()  # <-- hapus pesan inline
        await context.bot.send_message(user_id, "1/2 Kirim lokasi dulu", reply_markup=keyboard) # <-- kirim baru pake ReplyKeyboard
        return
    elif button_id == 'pulang':
    if status not in ['datang', 'lembur']:
        await query.answer("Kamu belum absen datang", show_alert=True)
        return
        context.user_data['aksi'] = 'pulang'
    context.user_data['step'] = 'tunggu_lokasi'
    keyboard = get_keyboard(status, step='lokasi')
    await query.delete_message()  # <-- hapus pesan inline
    await context.bot.send_message(user_id, "1/2 Kirim lokasi pulang", reply_markup=keyboard) # <-- kirim baru
    return
    
    elif button_id == 'pulang':
    if status not in ['datang', 'lembur']:
        await query.answer("Kamu belum absen datang", show_alert=True)
        return
    context.user_data['aksi'] = 'pulang'
    context.user_data['step'] = 'tunggu_lokasi'
    keyboard = get_keyboard(status, step='lokasi')
    await query.delete_message()  # <-- hapus pesan inline
    await context.bot.send_message(user_id, "1/2 Kirim lokasi pulang", reply_markup=keyboard) # <-- kirim baru
    return
 elif button_id in ['izin', 'sakit', 'cuti']:
    context.user_data['step'] = 'tunggu_alasan'
    context.user_data['status_izin'] = button_id
    await query.delete_message()
    await context.bot.send_message(user_id, f"Kirim alasan {button_id}:", reply_markup=get_keyboard(status))
    return
    elif button_id == 'rekap':
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id)
        bulan_nama = datetime.now(WIB).strftime('%B %Y')
        teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam Kerja: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))

    elif button_id == 'saya':
        data = get_data_saya(user_id)
        if not data:
            await query.edit_message_text("Belum ada data absen 7 hari terakhir.", reply_markup=get_keyboard(status))
            return
        teks = "*📋 Absen 7 Hari Terakhir*\n\n"
        for row in data:
            tanggal, datang, pulang, status, alasan, total_detik = row
            total_detik = int(total_detik) if total_detik else 0
            h, m = divmod(total_detik, 3600)
            total_jam = f"{h:02d}j {m//60:02d}m" if total_detik > 0 else "-"
            status_text = status or 'hadir'
            teks += f"*{tanggal}*\nDatang: {datang.strftime('%H:%M') if datang else '-'}\nPulang: {pulang.strftime('%H:%M') if pulang else '-'}\nStatus: {status_text}\n"
            if alasan:
                teks += f"Alasan: {alasan}\n"
            if total_jam!= "-":
                teks += f"Total: {total_jam}\n"
            teks += "\n"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))

    elif button_id == 'tim':
        hari_ini = datetime.now(WIB).date()
        hadir = query_db("SELECT nama, jam_datang, telat, status FROM absensi WHERE tanggal=%s AND jam_datang IS NOT NULL ORDER BY jam_datang", (hari_ini,), fetchall=True) or []
        belum = query_db("SELECT nama FROM absensi WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin', 'sakit', 'cuti', 'lembur')", (hari_ini,), fetchall=True) or []
        teks = f"*👥 Kehadiran Tim - {hari_ini}*\n\n✅ *Hadir ({len(hadir)} orang):*\n"
        for nama, jam, telat, status in hadir:
            telat_text = " [TELAT]" if telat else ""
            status_text = f" [{status.upper()}]" if status == 'lembur' else ""
            teks += f"- {nama}: {jam.strftime('%H:%M')}{telat_text}{status_text}\n"
        teks += f"\n❌ *Belum Absen ({len(belum)} orang):*\n"
        for nama, in belum:
            teks += f"- {nama}\n"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))

    elif button_id == 'download':
        bulan_ini = datetime.now(WIB).strftime('%Y-%m')
        await query.edit_message_text(f"📥 Download data bulan ini: `/export {bulan_ini}`\n\nAtau ketik manual: `/export YYYY-MM`\nContoh: `/export 2025-10`", reply_markup=get_keyboard(status))

    elif button_id == 'admin':
        if user_id!= ADMIN_ID:
            await query.answer("Kamu bukan admin", show_alert=True)
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Belum Absen Hari Ini", callback_data='admin_belum')],
            [InlineKeyboardButton("📅 Tambah Libur", callback_data='admin_libur')],
            [InlineKeyboardButton("❌ Tutup", callback_data='noop')]
        ])
        await query.edit_message_text("👑 *Admin Panel*", reply_markup=keyboard, parse_mode='Markdown')

    elif button_id == 'admin_belum':
        if user_id!= ADMIN_ID:
            return
        hari_ini = datetime.now(WIB).date()
        belum = query_db("SELECT nama FROM absensi WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin', 'sakit', 'cuti', 'lembur')", (hari_ini,), fetchall=True) or []
        teks = "❌ *Belum Absen Hari Ini:*\n" + "\n".join([f"- {nama}" for nama, in belum])
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))

    elif button_id == 'admin_libur':
        if user_id!= ADMIN_ID:
            return
        context.user_data['step'] = 'tunggu_tanggal_libur'
        await query.edit_message_text("Kirim tanggal libur format YYYY-MM-DD.\nContoh: 2025-12-25", reply_markup=get_keyboard(status))

    elif button_id == 'noop':
        context.user_data.clear()
        await query.edit_message_text("Menu ditutup. Ketik /start untuk buka lagi.", reply_markup=None)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nama = update.effective_user.first_name
    step = context.user_data.get('step')

    # 1. Handler lokasi
    if update.message.location and step == 'tunggu_lokasi':
        lokasi = update.message.location
        jarak = hitung_jarak(KANTOR_LAT, KANTOR_LON, lokasi.latitude, lokasi.longitude)

        if lokasi.accuracy > 100:
            await update.message.reply_text("❌ GPS akurasi jelek >100m. Matikan Fake GPS", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
            return
        if jarak > RADIUS_METER:
            await update.message.reply_text(f"❌ Kejauhan {int(jarak)}m dari kantor", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
            return

        context.user_data['lat'] = lokasi.latitude
        context.user_data['lon'] = lokasi.longitude
        context.user_data['step'] = 'tunggu_foto'
        await update.message.reply_text("2/2 Sekarang kirim selfie wajah", reply_markup=ReplyKeyboardRemove())
        return

    # 2. Handler foto
    if update.message.photo and step == 'tunggu_foto':
        foto = update.message.photo[-1]
        foto_id = foto.file_id
        lat = context.user_data.get('lat')
        lon = context.user_data.get('lon')
        aksi = context.user_data.get('aksi')
        jam_server = datetime.now(WIB).strftime('%H:%M:%S')

        if aksi == 'datang':
            simpan_datang(user_id, nama, lat, lon, foto_id)
            await update.message.reply_text(f"✅ Absen datang berhasil jam {jam_server}\nFoto + lokasi tersimpan")
        else:
            simpan_pulang(user_id, lat, lon, foto_id)
            await update.message.reply_text(f"✅ Absen pulang berhasil jam {jam_server}")

        context.user_data.clear()
        await start(update, context)
        return

    # 3. Handler alasan izin
    if update.message.text and step == 'tunggu_alasan':
        teks = update.message.text.strip()
        status = context.user_data.get('status_izin')
        simpan_izin(user_id, nama, status, teks)
        context.user_data.clear()
        await update.message.reply_text(f"✅ Status {status} berhasil disimpan.\nAlasan: {teks}", reply_markup=get_keyboard(cek_absen(user_id)))
        return

    # 4. Handler admin tambah libur
    if update.message.text and step == 'tunggu_tanggal_libur' and user_id == ADMIN_ID:
        try:
            tanggal = datetime.strptime(update.message.text.strip(), '%Y-%m-%d').date()
            query_db("INSERT INTO libur_nasional (tanggal) VALUES (%s) ON CONFLICT DO NOTHING", (tanggal,), commit=True)
            await update.message.reply_text(f"✅ Tanggal {tanggal} ditandai sebagai libur nasional", reply_markup=get_keyboard(cek_absen(user_id)))
        except ValueError:
            await update.message.reply_text("Format salah. Gunakan YYYY-MM-DD\nContoh: 2025-12-25", reply_markup=get_keyboard(cek_absen(user_id)))
        context.user_data.clear()
        return

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")

    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN dan SUPABASE_URL harus diset")
        return

    query_db("""
        CREATE TABLE IF NOT EXISTS absensi (
            id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, nama TEXT, tanggal DATE NOT NULL,
            jam_datang TIME, jam_pulang TIME, lat_datang DOUBLE PRECISION, lon_datang DOUBLE PRECISION,
            lat_pulang DOUBLE PRECISION, lon_pulang DOUBLE PRECISION, foto_datang TEXT, foto_pulang TEXT,
            status TEXT DEFAULT 'hadir', alasan TEXT, telat BOOLEAN DEFAULT false, UNIQUE(user_id, tanggal)
        )
    """, commit=True)
    query_db("CREATE TABLE IF NOT EXISTS libur_nasional (tanggal DATE PRIMARY KEY)", commit=True)
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.LOCATION | filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot jalan...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
