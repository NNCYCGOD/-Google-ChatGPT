import os
from dotenv import load_dotenv

load_dotenv()

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import openai
import asyncio
import re

# Параметры
SCOPES = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS_FILE = os.getenv("CREDS_FILE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY
# Авторизация
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

def parse_date_str(s):
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            continue
    return None

def get_date_columns(headers, start_date, end_date):
    cols = []
    for i, h in enumerate(headers):
        d = parse_date_str(h)
        if d and start_date <= d <= end_date:
            cols.append(i)
    return cols

def is_date(text):
    return bool(re.match(r'^\d{1,2}\.\d{1,2}\.\d{2,4}$', text))

def format_block(title, data_dict):
    lines = [title]
    for k,v in data_dict.items():
        lines.append(f"{k} {v}")
    return "\n".join(lines)

def ask_chatgpt_sync(question: str) -> str:
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты помощник по логистике."},
                {"role": "user", "content": question}
            ],
            max_tokens=300,
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка ChatGPT: {str(e)}"

async def ask_chatgpt(question: str) -> str:
    return await asyncio.to_thread(ask_chatgpt_sync, question)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    data = sheet.get_all_values()
    headers = data[0]
    rows = data[1:]

    if is_date(text):
        req_date = parse_date_str(text)
        if not req_date:
            await update.message.reply_text("Дата не распознана. Формат: дд.мм.гг или дд.мм.гггг")
            return

        try:
            date_col_index = headers.index(text)
        except ValueError:
            date_col_index = None
            for i, h in enumerate(headers):
                if parse_date_str(h) == req_date:
                    date_col_index = i
                    break
            if date_col_index is None:
                await update.message.reply_text(f"Данные за дату {text} не найдены.")
                return

        reply_lines = []
        i = 0
        while i < len(rows):
            fio = rows[i][0]
            block = {}
            j = i + 1
            while j < len(rows) and rows[j][0].strip() != '' and not re.search(r'[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+', rows[j][0].strip()):
                j += 1

            total = 0
            for k in range(i, j):
                label = rows[k][0]
                try:
                    val_str = rows[k][date_col_index]
                    val = int(val_str) if val_str.isdigit() else 0
                except IndexError:
                    val = 0
                block[label] = val
                if label.lower() != 'кузьмин леонид':
                    total += val
            block['Всего обработано'] = total
            reply_lines.append(format_block(fio, block))
            i = j
        await update.message.reply_text("\n\n".join(reply_lines))
        return

    surname = text.lower()
    today = datetime.today().date()
    start_date = today - timedelta(days=6)

    date_cols = get_date_columns(headers, start_date, today)
    if not date_cols:
        await update.message.reply_text("Нет данных за последние 7 дней.")
        return

    reply_lines = []
    i = 0
    while i < len(rows):
        fio = rows[i][0]
        if surname not in fio.lower():
            j = i + 1
            while j < len(rows) and rows[j][0].strip() != '' and not re.search(r'[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+', rows[j][0].strip()):
                j += 1
            i = j
            continue

        j = i + 1
        while j < len(rows) and rows[j][0].strip() != '' and not re.search(r'[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+', rows[j][0].strip()):
            j += 1

        reply_lines.append(fio)
        for col_idx in date_cols:
            date_str = headers[col_idx]
            reply_lines.append(date_str)
            total = 0
            for k in range(i, j):
                label = rows[k][0]
                try:
                    val_str = rows[k][col_idx]
                    val = int(val_str) if val_str.isdigit() else 0
                except IndexError:
                    val = 0
                if label.lower() != fio.lower():
                    reply_lines.append(f"{label} {val}")
                    total += val
            reply_lines.append(f"Всего обработано {total}\n")

        i = j

    if not reply_lines:
        reply_lines = [await ask_chatgpt(text)]

    await update.message.reply_text("\n".join(reply_lines))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь фамилию или дату (дд.мм.гг) для получения данных.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
