import asyncio
import os
import psycopg2
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("8429562249:AAG5xo5IkAqtxnoG62-ocjDnyc3Jvq3u5cE")
SUPABASE_URL = os.getenv("postgresql://postgres.awvntmatecqendshveeh:Azizan0104@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres")

def get_db():
    return psycopg2.connect(SUPABASE_URL)

def init_db():
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
            UNIQUE(user_id, tanggal)
        )
    """)
    conn.commit()
    conn.close()

def cek_absen(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now().date()
    cur.execute("SELECT * FROM absensi WHERE user_id=%s AND tanggal=%s", (user_id, hari_ini))
    data = cur.fetchone()
    conn.close()
    if data:
        return {'jam_datang': data[4], 'jam_pulang': data[5]}
    return None

def simpan_datang(user_id, nama):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now().date()
    jam_sekarang = datetime.now().time()
    try:
        cur.execute("""
            INSERT INTO absensi (user_id, nama, tanggal, jam_datang)
            VALUES (%s, %s, %s, %s)
        """, (user_id, nama, hari_ini, jam_sekarang))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def simpan_pulang(user_id):
    conn = get_db()
    cur = conn.cursor()
    hari_ini = datetime.now().date()
    jam_sekarang = datetime.now().time()
    cur.execute("""
        UPDATE absensi SET jam_pulang=%s
        WHERE user_id=%s AND tanggal=%s AND jam_datang IS NOT NULL AND jam_pulang IS NULL
    """, (jam_sekarang, user_id, hari_ini))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nama = update.effective_user.first_name
    data = cek_absen(user_id)
    hari_ini = datetime.now().strftime('%d/%m/%Y')

    if data and data['jam_datang'] and data['jam_pulang']:
        await update.message.reply_text(
            f"🤖 *Absen Selesai*\n📅 {hari_ini}\n"
            f"━━━━━━━━━━━━━━\n"
            f"✅ Datang: {data['jam_datang']}\n"
            f"🚪 Pulang: {data['jam_pulang']}\n\n"
            f"Absensi hari ini sudah lengkap.",
            parse_mode='Markdown'
        )
        return

    keyboard = [
        [InlineKeyboardButton("✅ Datang", callback_data='datang'),
         InlineKeyboardButton("🚪 Pulang", callback_data='pulang')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    teks = f"🤖 *Absen*\n📅 {hari_ini}\n\n"
    if data and data['jam_datang']:
        teks += f"✅ Sudah datang: {data['jam_datang']}\n\nSilakan absen pulang"
    else:
        teks += "Waktunya absen datang"

    await update.message.reply_text(teks, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    nama = query.from_user.first_name
    button_id = query.data
    data = cek_absen(user_id)

    if button_id == 'datang':
        if data and data['jam_datang']:
            await query.edit_message_text("⚠️ Kamu sudah absen datang hari ini.")
            return
        if simpan_datang(user_id, nama):
            jam = datetime.now().strftime('%H:%M:%S')
            await query.edit_message_text(f"✅ Absen datang berhasil!\nWaktu: {jam}")
        else:
            await query.edit_message_text("❌ Gagal absen datang.")

    elif button_id == 'pulang':
        if not data or not data['jam_datang']:
            await query.edit_message_text("❌ Kamu belum absen datang hari ini.")
            return
        if data['jam_pulang']:
            await query.edit_message_text(f"⚠️ Kamu sudah absen pulang jam {data['jam_pulang']}")
            return
        if simpan_pulang(user_id):
            jam_pulang = datetime.now().strftime('%H:%M:%S')
            jam_datang = data['jam_datang']
            teks = f"🤖 *Absen Selesai*\n📅 {datetime.now().strftime('%d/%m/%Y')}\n"
            teks += "━━━━━━━━━━━━━━\n"
            teks += f"✅ Datang: {jam_datang}\n"
            teks += f"🚪 Pulang: {jam_pulang}\n\n"
            teks += "Absensi hari ini sudah lengkap. Sampai jumpa besok!"
            await query.edit_message_text(teks, parse_mode='Markdown')

async def main():
    print("TOKEN:", "ADA" if os.getenv("TOKEN") else "KOSONG")
    print("SUPABASE_URL:", "ADA" if os.getenv("SUPABASE_URL") else "KOSONG")
    
    if not TOKEN or not SUPABASE_URL:
        print("Error: TOKEN dan SUPABASE_URL harus diset di Environment Variables")
        return

    init_db()
    print("Database siap")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot jalan...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
