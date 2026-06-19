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
    MessageHandler, ConversationHandler, ContextTypes, filters
)

app_flask = Flask(__name__)
WIB = ZoneInfo("Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Ambil dari Environment Variable saja. Tidak ada default.
KANTOR_LAT = float(os.getenv("KANTOR_LAT"))
KANTOR_LON = float(os.getenv("KANTOR_LON"))
RADIUS_METER = int(os.getenv("RADIUS_METER", "500"))

REASON = 1

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
        input,button{{padding:8px;font-size:16px;}}@media(max-width:600px){{table,thead,tbody,th,td,tr{{display:block;}}
        th{{display:none;}}td{{border:none;position:relative;padding-left:50%;}}td:before{{content:attr(data-label);
        position:absolute;left:10px;font-weight:bold;}}}}</style></head><body>
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
            html += f"""<tr class="{row_class}"><td data-label="Nama">{nama}</td><td data-label="Tanggal">{tanggal}</td>
            <td data-label="Datang">{datang.strftime('%H:%M:%S') if datang else '-'}</td>
            <td data-label="Pulang">{pulang.strftime('%H:%M:%S') if pulang else '-'}</td>
            <td data-label="Status" class="{status_class}">{status or 'hadir'}</td>
            <td data-label="Alasan">{alasan or '-'}</td><td data-label="Total Jam">{total_jam}</td></tr>"""

        html += "</tbody></table></body></html>"
        return html
    except Exception as e:
        return f"<h2>Error Koneksi DB</h2><pre>{e}</pre>", 500

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
        result = cur.fetchone()
    if result:
        return True, "Libur Nasional"
    return False, None

def hitung_jarak_meter(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_keyboard(status):
    buttons = []
    if status == 'belum':
        buttons.append([
            InlineKeyboardButton("📍 Absen Datang", callback_data='minta_lokasi_datang'),
            InlineKeyboardButton("📝 Izin", callback_data='izin')
        ])
    elif status in ['datang', 'lembur']:
        buttons.append([
            InlineKeyboardButton("📍 Absen Pulang", callback_data='minta_lokasi_pulang'),
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
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        cur.execute("SELECT jam_datang, jam_pulang, status FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
        data = cur.fetchone()
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
    with get_db() as conn:
        cur = conn.cursor()
        wib = datetime.now(WIB)
        hari_ini = wib.date()
        jam_sekarang = wib.time()
        telat = jam_sekarang > datetime.strptime('09:00:00', '%H:%M:%S').time()
        libur, jenis_libur = is_libur(hari_ini)
        status = 'lembur' if libur else 'hadir'
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang, lat_datang, lon_datang, status, telat, alasan)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, tanggal) DO NOTHING
        """, (user_id, nama, hari_ini, jam_sekarang, lat, lon, status, telat, jenis_libur))
        conn.commit()
        return True, telat, libur, jenis_libur

def simpan_pulang(user_id, lat, lon):
    with get_db() as conn:
        cur = conn.cursor()
        wib = datetime.now(WIB)
        hari_ini = wib.date()
        jam_sekarang = wib.time()
        cur.execute("""
            UPDATE absensi SET jam_pulang=%s, lat_pulang=%s, lon_pulang=%s
            WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL
        """, (jam_sekarang, lat, lon, user_id, hari_ini))
        updated = cur.rowcount > 0
        conn.commit()
        return updated

def simpan_izin(user_id, nama, status, alasan):
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, status, alasan)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, tanggal)
            DO UPDATE SET status=%s, alasan=%s
        """, (user_id, nama, hari_ini, status, alasan, status, alasan))
        conn.commit()

def get_rekap_bulanan(user_id, bulan_str=None):
    with get_db() as conn:
        cur = conn.cursor()
        now = datetime.now(WIB)
        if bulan_str:
            tahun, bulan = map(int, bulan_str.split('-'))
        else:
            tahun, bulan = now.year, now.month
        cur.execute("""
            SELECT COUNT(*) as hari_hadir,
                   COALESCE(EXTRACT(EPOCH FROM SUM(jam_pulang - jam_datang)), 0) as total_detik,
                   SUM(CASE WHEN telat THEN 1 ELSE 0 END) as total_telat
            FROM absensi
            WHERE user_id=%s AND EXTRACT(MONTH FROM tanggal) = %s
            AND EXTRACT(YEAR FROM tanggal) = %s AND jam_pulang IS NOT NULL
            AND status IN ('hadir', 'lembur')
        """, (user_id, bulan, tahun))
        data = cur.fetchone()
    hari_hadir = data[0] if data[0] else 0
    total_detik = int(data[1]) if data[1] else 0
    total_telat = data[2] if data[2] else 0
    h = total_detik // 3600
    m = (total_detik % 3600) // 60
    total_jam_fmt = f"{h:02d}j {m:02d}m"
    if hari_hadir > 0:
        rata_detik = total_detik // hari_hadir
        rh = rata_detik // 3600
        rm = (rata_detik % 3600) // 60
        rata_fmt = f"{rh:02d}j {rm:02d}m"
    else:
        rata_fmt = "00j 00m"
    return hari_hadir, total_jam_fmt, total_telat, rata_fmt

def get_data_saya(user_id):
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        tujuh_hari_lalu = hari_ini - timedelta(days=7)
        cur.execute("""
            SELECT tanggal, jam_datang, jam_pulang, status, alasan,
            EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik
            FROM absensi WHERE user_id=%s AND tanggal >= %s ORDER BY tanggal DESC
        """, (user_id, tujuh_hari_lalu))
        data = cur.fetchall()
    return data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status = cek_absen(user_id)
    hari_ini = datetime.now(WIB).strftime('%d/%m/%Y')
    keyboard = get_keyboard(status)
    teks = f"🤖 *Absensi Karyawan*\n📅 {hari_ini}\n\n"
    if status == 'belum':
        teks += "Waktunya absen datang"
    elif status in ['datang', 'lembur']:
        teks += "✅ Sudah absen datang\nSilakan absen pulang"
    elif status in ['izin', 'sakit', 'cuti']:
        teks += f"📝 Status hari ini: {status}"
    else:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT jam_datang, jam_pulang FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, datetime.now(WIB).date()))
            data = cur.fetchone()
        teks += f"✅ Datang: {data[0].strftime('%H:%M:%S')}\n"
        teks += f"🚪 Pulang: {data[1].strftime('%H:%M:%S')}\n\nAbsensi hari ini sudah selesai"
    await update.message.reply_text(teks, reply_markup=keyboard, parse_mode='Markdown')

async def minta_lokasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['aksi_absen'] = query.data
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Kirim Lokasi Saya", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await query.edit_message_text(
        f"Silakan kirim lokasi Anda. Pastikan GPS aktif dan berada dalam radius {RADIUS_METER} meter dari kantor.",
        reply_markup=keyboard
    )

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

    if aksi == 'minta_lokasi_datang':
        if cek_absen(user_id)!= 'belum':
            await update.message.reply_text("Anda sudah absen datang hari ini.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        success, telat, libur, jenis_libur = simpan_datang(user_id, nama, lokasi.latitude, lokasi.longitude)
        if success:
            teks = f"✅ Absen datang berhasil!\nWaktu: {datetime.now(WIB).strftime('%H:%M:%S')}\nJarak: {int(jarak)} meter"
            if libur: teks += f"\n💜 *LEMBUR* - {jenis_libur}"
            if telat: teks += "\n⚠️ *Kamu telat!*"
            await update.message.reply_text(teks, reply_markup=ReplyKeyboardRemove())

    elif aksi == 'minta_lokasi_pulang':
        if cek_absen(user_id) not in ['datang', 'lembur']:
            await update.message.reply_text("Anda belum absen datang.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        success = simpan_pulang(user_id, lokasi.latitude, lokasi.longitude)
        if success:
            await update.message.reply_text(f"🚪 Absen pulang berhasil!\nJarak: {int(jarak)} meter", reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("Gagal absen pulang.", reply_markup=ReplyKeyboardRemove())

    context.user_data.pop('aksi_absen', None)
    await start(update, context)
    return ConversationHandler.END

async def rekap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bulan_str = context.args[0] if context.args else None
    try:
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id, bulan_str)
        bulan_nama = datetime.strptime(bulan_str, '%Y-%m').strftime('%B %Y') if bulan_str else datetime.now(WIB).strftime('%B %Y')
    except:
        await update.message.reply_text("Format salah. Contoh: `/rekap 2025-10`", parse_mode='Markdown')
        return
    teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam Kerja: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
    await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(cek_absen(user_id)))

async def saya_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = get_data_saya(user_id)
    if not data:
        await update.message.reply_text("Belum ada data absen 7 hari terakhir.", reply_markup=get_keyboard(cek_absen(user_id)))
        return
    teks = "*📋 Absen 7 Hari Terakhir*\n\n"
    for row in data:
        tanggal, datang, pulang, status, alasan, total_detik = row
        total_detik = int(total_detik) if total_detik else 0
        h = total_detik // 3600
        m = (total_detik % 3600) // 60
        total_jam = f"{h:02d}j {m:02d}m" if total_detik > 0 else "-"
        status_text = status or 'hadir'
        teks += f"*{tanggal}*\nDatang: {datang.strftime('%H:%M') if datang else '-'}\nPulang: {pulang.strftime('%H:%M') if pulang else '-'}\nStatus: {status_text}\n"
        if alasan: teks += f"Alasan: {alasan}\n"
        if total_jam!= "-": teks += f"Total: {total_jam}\n"
        teks += "\n"
    await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(cek_absen(user_id)))

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args)!= 1:
        await update.message.reply_text("Format: `/export 2025-10`", parse_mode='Markdown')
        return
    try:
        tahun, bulan = map(int, context.args[0].split('-'))
    except:
        await update.message.reply_text("Format salah. Contoh: `/export 2025-10`")
        return
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT tanggal, jam_datang, jam_pulang, status, alasan,
            EXTRACT(EPOCH FROM jam_pulang - jam_datang) as total_detik
            FROM absensi WHERE user_id=%s
            AND EXTRACT(MONTH FROM tanggal) = %s
            AND EXTRACT(YEAR FROM tanggal) = %s ORDER BY tanggal
        """, (user_id, bulan, tahun))
        data = cur.fetchall()
    if not data:
        await update.message.reply_text("Tidak ada data untuk bulan ini.")
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tanggal', 'Jam Datang', 'Jam Pulang', 'Status', 'Alasan', 'Total Jam'])
    for row in data:
        tanggal, datang, pulang, status, alasan, total_detik = row
        total_detik = int(total_detik) if total_detik else 0
        h = total_detik // 3600
        m = (total_detik % 3600) // 60
        total_jam = f"{h:02d}j {m:02d}m" if total_detik > 0 else "-"
        writer.writerow([tanggal, datang, pulang, status, alasan, total_jam])
    output.seek(0)
    await update.message.reply_document(
        document=InputFile(io.BytesIO(output.getvalue().encode()), filename=f"absen_{context.args[0]}.csv"),
        caption="📄 Data absen bulan ini"
    )

async def tim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        cur = conn.cursor()
        hari_ini = datetime.now(WIB).date()
        cur.execute("SELECT nama, jam_datang, telat, status FROM absensi WHERE tanggal=%s AND jam_datang IS NOT NULL ORDER BY jam_datang", (hari_ini,))
        hadir = cur.fetchall()
        cur.execute("SELECT nama FROM absensi WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin', 'sakit', 'cuti', 'lembur')", (hari_ini,))
        belum = cur.fetchall()
    teks = f"*👥 Kehadiran Tim - {hari_ini}*\n\n✅ *Hadir ({len(hadir)} orang):*\n"
    for nama, jam, telat, status in hadir:
        telat_text = " [TELAT]" if telat else ""
        status_text = f" [{status.upper()}]" if status == 'lembur' else ""
        teks += f"- {nama}: {jam.strftime('%H:%M')}{telat_text}{status_text}\n"
    teks += f"\n❌ *Belum Absen ({len(belum)} orang):*\n"
    for nama, in belum:
        teks += f"- {nama}\n"
    await update.message.reply_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(cek_absen(update.effective_user.id)))

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id!= ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Belum Absen Hari Ini", callback_data='admin_belum')],
        [InlineKeyboardButton("📅 Tambah Libur", callback_data='admin_libur')],
        [InlineKeyboardButton("❌ Tutup", callback_data='noop')]
    ])
    await update.message.reply_text("👑 *Admin Panel*", reply_markup=keyboard, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    status = cek_absen(user_id)

    if button_id in ['izin', 'sakit', 'cuti']:
        context.user_data['status_izin'] = button_id
        await query.edit_message_text(f"Kirim alasan {button_id}:")
        return REASON
    elif button_id == 'rekap':
        hari_hadir, total_jam, total_telat, rata_rata = get_rekap_bulanan(user_id)
        bulan_nama = datetime.now(WIB).strftime('%B %Y')
        teks = f"📊 *Rekap {bulan_nama}*\n\n📅 Hari Hadir: {hari_hadir} hari\n⏱️ Total Jam Kerja: {total_jam}\n⚠️ Telat: {total_telat} kali\nRata-rata: {rata_rata}/hari"
        await query.edit_message_text(teks, parse_mode='Markdown', reply_markup=get_keyboard(status))
    elif button_id == 'saya':
        await saya_command(update, context)
    elif button_id == 'tim':
        await tim_command(update, context)
    elif button_id == 'download':
        bulan_ini = datetime.now(WIB).strftime('%Y-%m')
        await query.edit_message_text(f"📥 Download data bulan ini: `/export {bulan_ini}`\n\nAtau ketik manual: `/export YYYY-MM`")
    elif button_id == 'admin':
        await admin_command(update, context)
    elif button_id == 'admin_belum':
        if user_id!= ADMIN_ID: return
        hari_ini = datetime.now(WIB).date()
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT nama FROM absensi WHERE tanggal=%s AND jam_datang IS NULL AND status NOT IN ('izin', 'sakit', 'cuti', 'lembur')", (hari_ini,))
            belum = cur.fetchall()
        teks = "❌ *Belum Absen Hari Ini:*\n" + "\n".join([f"- {nama}" for nama, in belum]) if belum else "✅ Semua sudah absen"
        await query.edit_message_text(teks, parse_mode='Markdown')
    elif button_id == 'admin_libur':
        if user_id!= ADMIN_ID: return
        await query.edit_message_text("Kirim tanggal libur format YYYY-MM-DD. Contoh: 2025-12-25")
        return REASON
    elif button_id == 'noop':
        await query.edit_message_text("Menu ditutup. Ketik /start untuk buka lagi.")

async def terima_alasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = update.message.text.strip()
    status = context.user_data.get('status_izin')

    if status:
        user_id = update.effective_user.id
        nama = update.effective_user.first_name
        simpan_izin(user_id, nama, status, teks)
        context.user_data.pop('status_izin', None)
        await update.message.reply_text(f"✅ Status {status} berhasil disimpan.\nAlasan: {teks}", reply_markup=get_keyboard(cek_absen(user_id)))
        return ConversationHandler.END

    if update.effective_user.id == ADMIN_ID:
        try:
            tanggal = datetime.strptime(teks, '%Y-%m-%d').date()
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("INSERT INTO libur_nasional (tanggal) VALUES (%s) ON CONFLICT DO NOTHING", (tanggal,))
                conn.commit()
            await update.message.reply_text(f"✅ Tanggal {tanggal} ditandai sebagai libur nasional", reply_markup=get_keyboard(cek_absen(update.effective_user.id)))
        except ValueError:
            await update.message.reply_text("Format salah. Gunakan YYYY-MM-DD. Contoh: 2025-12-25", reply_markup=get_keyboard(cek_absen(update.effective_user.id)))
        return ConversationHandler.END

    return ConversationHandler.END

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def main():
    TOKEN = os.getenv("TOKEN")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    KANTOR_LAT_ENV = os.getenv("KANTOR_LAT")
    KANTOR_LON_ENV = os.getenv("KANTOR_LON")

    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN dan SUPABASE_URL harus diset")
        return
    if not KANTOR_LAT_ENV or not KANTOR_LON_ENV:
        print("Error: KANTOR_LAT dan KANTOR_LON harus diset di Environment Variable")
        return

    with get_db() as conn:
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
        cur.execute("CREATE TABLE IF NOT EXISTS libur_nasional (tanggal DATE PRIMARY KEY)")
        conn.commit()
    print("Database siap")

    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()

    button_pattern = '^(izin|sakit|cuti|rekap|saya|tim|download|admin|admin_belum|admin_libur|noop)$'

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern=button_pattern)],
        states={REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, terima_alasan)]},
        fallbacks=[]
    )

    app.add_handler(CallbackQueryHandler(minta_lokasi, pattern='^minta_lokasi_'))
    app.add_handler(MessageHandler(filters.LOCATION, terima_lokasi))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rekap", rekap_command))
    app.add_handler(CommandHandler("saya", saya_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("tim", tim_command))
    app.add_handler(CommandHandler("admin", admin_command))

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler, pattern=button_pattern))

    print("Bot berjalan...")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    main()
