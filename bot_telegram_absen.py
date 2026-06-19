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
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

KANTOR_LAT = float(os.getenv("KANTOR_LAT", "0"))
KANTOR_LON = float(os.getenv("KANTOR_LON", "0"))
RADIUS_METER = int(os.getenv("RADIUS_METER", "500"))

REASON = 1
AWAITING_LOCATION = 2

@app_flask.route('/')
def home():
    try:
        tanggal = request.args.get('tanggal')
        conn = get_db()
        cur = conn.cursor()

        if tanggal:
            cur.execute("""
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
                EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
                CASE
                    WHEN jam_datang > TIME '09:00:00' THEN true
                    ELSE false
                END as telat_flag
                FROM absensi
                WHERE tanggal=%s
                ORDER BY jam_datang DESC
            """, (tanggal,))
        else:
            cur.execute("""
                SELECT nama, tanggal, jam_datang, jam_pulang, status, alasan, telat,
                EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik,
                CASE
                    WHEN jam_datang > TIME '09:00:00' THEN true
                    ELSE false
                END as telat_flag
                FROM absensi
                ORDER BY tanggal DESC, jam_datang DESC
                LIMIT 100
            """)

        data = cur.fetchall()
        conn.close()

        html = """
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
                    td:before {{
                        content: attr(data-label);
                        position: absolute;
                        left: 10px;
                        font-weight: bold;
                    }}
                }}
            </style>
        </head>
        <body>
            <h2>📋 Data Absensi</h2>
            <div class="filter">
                <form method="get">
                    <input type="date" name="tanggal" value="{tgl}">
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
        """.format(tgl=tanggal if tanggal else "")

        for row in data:
            nama, tanggal, datang, pulang, status, alasan, telat_db, total_detik, telat_flag = row
            row_class = "telat" if telat_flag else ""
            status_class = f"status-{status}" if status else ""

            total_detik = int(total_detik) if total_detik else 0
            h = total_detik // 3600
            m = (total_detik % 3600) // 60
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

        html += """
                </tbody>
            </table>
        </body>
        </html>
        """
        return html

    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

def get_db():
    return psycopg2.connect(os.getenv("SUPABASE_URL"))

def hitung_jarak_meter(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def is_libur(tanggal):
    if tanggal.weekday() == 6:
        return True, "Minggu"

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM libur_nasional WHERE tanggal=%s", (tanggal,))
    result = cur.fetchone()
    conn.close()
    if result:
        return True, "Libur Nasional"

    return False, None

def get_keyboard(status):
    buttons = []

    if status == 'belum':
        buttons.append([
            InlineKeyboardButton("✅ Datang", callback_data='minta_lokasi_datang'), # ganti
            InlineKeyboardButton("📝 Izin", callback_data='izin')
        ])
    elif status in ['datang', 'lembur']:
        buttons.append([
            InlineKeyboardButton("🚪 Pulang", callback_data='minta_lokasi_pulang'), # ganti
            InlineKeyboardButton("📝 Izin", callback_data='izin'),
            InlineKeyboardButton("🤒 Sakit", callback_data='sakit')
        ])

    buttons.append([
        InlineKeyboardButton("📊 Rekap", callback_data='rekap'),
        InlineKeyboardButton("📋 Saya", callback_data='saya'),
        InlineKeyboardButton("👥 Tim", callback_data='tim')
    ])
    buttons.append([
        InlineKeyboardButton("⬇️ Download", callback_data='download'),
        InlineKeyboardButton("👑 Admin", callback_data='admin'),
        InlineKeyboardButton("❌", callback_data='noop')
    ])

    return InlineKeyboardMarkup(buttons)

def cek_absen(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if not data:
        return 'belum'
    if data[2] in ['izin', 'sakit', 'cuti', 'lembur']:
        return data[2]
    if data[0] and not data[1]:
        return 'datang'
    if data[0] and data[1]:
        return 'selesai'
    return 'belum'

def simpan_datang(user_id, nama, lat, lon):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()

    libur, jenis_libur = is_libur(hari_ini)
    status = 'lembur' if libur else 'hadir'

    try:
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang, lat_datang, lon_datang, status, telat, alasan)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, tanggal) DO NOTHING
        """, (user_id, nama, hari_ini, jam_sekarang, lat, lon, status, telat, jenis_libur))
        conn.commit()
        return True, telat, libur, jenis_libur
    except Exception as e:
        print("Error simpan_datang:", e)
        return False, False, False, None
    finally:
        conn.close()

def simpan_pulang(user_id, lat, lon):
    conn = get_db()
    cur = conn.cursor()
    wib = datetime.now(WIB)
    hari_ini = wib.date()
    jam_sekarang = wib.time()
    cur.execute("""
        UPDATE absensi SET jam_pulang=%s, lat_pulang=%s, lon_pulang=%s
        WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL
    """, (jam_sekarang, lat, lon, user_id, hari_ini))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated

def simpan_izin(user_id, nama, status, alasan):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now(WIB).date()
    cur.execute("""
        INSERT INTO absensi (user_id, nama, tanggal, status, alasan)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id, tanggal)
        DO UPDATE SET status=%s, alasan=%s
    """, (user_id, nama, hari_ini, status, alasan, status, alasan))
    conn.commit()
    conn.close()

#... fungsi get_rekap_bulanan, get_data_saya, dll tetap sama...

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)

    teks = f"🤖 *Absen*\n📅 {hari_ini}\n\n"
    if status == 'belum':
        teks += "Waktunya absen datang"
    elif status in ['datang', 'lembur']:
        teks += "✅ Sudah absen datang\nSilakan absen pulang"
    elif status in ['izin', 'sakit', 'cuti']:
        teks += f"📝 Status hari ini: {status}"
    else:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, datetime.now(WIB).date()))
        data = cur.fetchone()
        conn.close()
        teks += f"✅ Datang: {data[0].strftime('%H:%M:%S')}\n"
        teks += f"🚪 Pulang: {data[1].strftime('%H:%M:%S')}\n\n"
        teks += "Absensi hari ini sudah selesai"

    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def minta_lokasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['aksi_absen'] = query.data # simpan mau datang atau pulang

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Kirim Lokasi Saya", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await query.edit_message_text(
        f"📍 Kirim lokasi Anda sekarang.\nPastikan GPS aktif dan berada dalam radius {RADIUS_METER} meter dari kantor.",
        reply_markup=keyboard
    )
    return AWAITING_LOCATION

async def terima_lokasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nama = update.effective_user.first_name
    aksi = context.user_data.get('aksi_absen')
    lokasi = update.message.location

    jarak = hitung_jarak_meter(KANTOR_LAT, KANTOR_LON, lokasi.latitude, lokasi.longitude)

    if jarak > RADIUS_METER:
        await update.message.reply_text(
            f"❌ Gagal absen. Jarak Anda {int(jarak)} meter dari kantor. Maksimal {RADIUS_METER} meter.",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.pop('aksi_absen', None)
        return ConversationHandler.END

    wib = datetime.now(WIB)
    jam = wib.strftime('%H:%M:%S')
    hari_ini = wib.strftime('%d/%m/%Y')

    if aksi == 'minta_lokasi_datang':
        if cek_absen(user_id)!= 'belum':
            await update.message.reply_text("Kamu sudah absen datang", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END

        success, telat, libur, jenis_libur = simpan_datang(user_id, nama, lokasi.latitude, lokasi.longitude)
        if success:
            teks = f"✅ Absen datang berhasil!\nWaktu: {jam}\nJarak: {int(jarak)} meter"
            if libur:
                teks += f"\n💜 *LEMBUR* - {jenis_libur}"
            if telat:
                teks += "\n⚠️ *Kamu telat!*"
            teks += "\n\nSilakan absen pulang"
            await update.message.reply_text(teks, reply_markup=ReplyKeyboardRemove())

    elif aksi == 'minta_lokasi_pulang':
        if cek_absen(user_id) not in ['datang', 'lembur']:
            await update.message.reply_text("Kamu belum absen datang", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END

        if simpan_pulang(user_id, lokasi.latitude, lokasi.longitude):
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT jam_datang, jam_pulang, status,
                EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik
                FROM absensi
                WHERE user_id=%s AND tanggal=%s
            """, (user_id, wib.date()))
            data = cur.fetchone()
            conn.close()

            jam_datang_str = data[0].strftime('%H:%M:%S')
            jam_pulang_str = data[1].strftime('%H:%M:%S')
            status_akhir = data[2]
            total_detik = int(data[3]) if data[3] else 0

            h = total_detik // 3600
            m = (total_detik % 3600) // 60
            total_jam = f"{h:02d}j {m:02d}m"

            teks = f"🤖 *Absen Selesai*\n📅 {hari_ini}\n"
            teks += f"━━━━━━━━━━━━━━\n"
            teks += f"✅ Datang: {jam_datang_str}\n"
            teks += f"🚪 Pulang: {jam_pulang_str}\n"
            teks += f"⏱️ Total Jam Kerja: {total_jam}\n"
            teks += f"📍 Jarak pulang: {int(jarak)} meter\n"
            if status_akhir == 'lembur':
                teks += f"💜 Status: LEMBUR\n"
            teks += f"Absen hari ini sudah selesai terimakasih\n"
            teks += f"**Tetap semangat**"

            await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())

    context.user_data.pop('aksi_absen', None)
    await start(update, context)
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    button_id = query.data
    status = cek_absen(user_id)

    if button_id == 'minta_lokasi_datang' or button_id == 'minta_lokasi_pulang':
        return await minta_lokasi(update, context)

    #... sisanya button_handler kamu tetap sama, copy dari kode lama...
    # untuk button 'izin', 'sakit', 'rekap', 'saya', 'tim', 'download', 'admin', dll

async def terima_alasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    status = context.user_data.get('status_izin')

    if status:
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        simpan_izin(user_id, nama, status, teks)
        context.user_data.pop('status_izin', None)
        await update.message.reply_text(
            f"✅ Status {status} berhasil disimpan.\nAlasan: {teks}",
            reply_markup=get_keyboard(cek_absen(user_id))
        )
        return ConversationHandler.END

    if update.effective_user.id == ADMIN_ID:
        try:
            tanggal = datetime.strptime(teks, '%Y-%m-%d').date()
            conn = get_db()
            cur = conn.cursor()
            cur.execute("INSERT INTO libur_nasional (tanggal) VALUES (%s) ON CONFLICT DO NOTHING", (tanggal,))
            conn.commit()
            conn.close()
            await update.message.reply_text(
                f"✅ Tanggal {tanggal} ditandai sebagai libur nasional",
                reply_markup=get_keyboard(cek_absen(update.effective_user.id))
            )
        except ValueError:
            await update.message.reply_text(
                "Format salah. Gunakan YYYY-MM-DD\nContoh: 2025-12-25",
                reply_markup=get_keyboard(cek_absen(update.effective_user.id))
            )
        return ConversationHandler.END

    return ConversationHandler.END

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")

    if not TOKEN or not SUPABASE_URL or KANTOR_LAT == 0 or KANTOR_LON == 0:
        print("Error: TOKEN, SUPABASE_URL, KANTOR_LAT, KANTOR_LON harus diset")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS absensi (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            nama TEXT,
            tanggal DATE NOT NULL,
            jam_datang TIME,
            jam_pulang TIME,
            lat_datang DOUBLE PRECISION,
            lon_datang DOUBLE PRECISION,
            lat_pulang DOUBLE PRECISION,
            lon_pulang DOUBLE PRECISION,
            status TEXT DEFAULT 'hadir',
            alasan TEXT,
            telat BOOLEAN DEFAULT false,
            UNIQUE(user_id, tanggal)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS libur_nasional (
            tanggal DATE PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, terima_alasan)],
            AWAITING_LOCATION: [MessageHandler(filters.LOCATION, terima_lokasi)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rekap", rekap_command))
    app.add_handler(CommandHandler("saya", saya_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("tim", tim_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.LOCATION, terima_lokasi))

    print("Bot jalan...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
