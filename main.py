import re
import io
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ---------------- CONFIG ----------------

BOT_TOKEN = "8792417044:AAFhz54pXi1TViE-xRaeRVAqE041OUL5o-M"

MAX_Q_LEN = 300
MAX_OPT_LEN = 100
MAX_EXPL_LEN = 200

USER_SESSIONS = {}

# Strict Regex Patterns
OPTION_RE = re.compile(r"^\(?[a-e]\)|^[a-e][\.\)]", re.IGNORECASE)
ANSWER_RE = re.compile(r"^answer:\s*([a-e])", re.IGNORECASE)
EX_RE = re.compile(r"^ex:", re.IGNORECASE)

# ---------------- BLOCK SPLITTER (Advanced Logic) ----------------

def get_blocks(text):
    """
    Splits text by identifying the end of a question.
    Priority order to trigger a split:
    1. After an 'ex:' line.
    2. After an 'Answer:' line.
    3. After an option 'd' or 'e' line IF no Answer/Ex follows.
    """
    lines = [line.rstrip() for line in text.split('\n')]
    blocks = []
    current_block = []
    
    for i, line in enumerate(lines):
        clean_line = line.strip().lower()
        current_block.append(line)
        
        should_split = False
        
        # Priority 1 & 2: Flags exist
        if EX_RE.match(clean_line) or ANSWER_RE.match(clean_line):
            should_split = True
        
        # Priority 3: No flags, split after option d/e
        elif OPTION_RE.match(clean_line):
            # Check if it's option d or e
            if any(clean_line.startswith(prefix) for prefix in ['d', 'e', '(d', '(e']):
                # Look ahead: if next 3 lines don't have Answer/Ex, split here
                remaining = "\n".join(lines[i+1:i+4]).lower()
                if "answer:" not in remaining and "ex:" not in remaining:
                    should_split = True

        # Execute split if we hit a blank line after a trigger
        if should_split:
            if i + 1 < len(lines) and lines[i+1].strip() == "":
                blocks.append("\n".join(current_block))
                current_block = []
                
    if current_block:
        blocks.append("\n".join(current_block))
    return [b.strip() for b in blocks if b.strip()]

# ---------------- PARSER ----------------

def parse_question_block(block):
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    q_parts, opts, expl, correct_idx, mode = [], [], "", None, "question"

    for line in lines:
        low = line.lower()
        
        if EX_RE.match(low):
            mode = "explanation"
            expl = line[3:].strip()
            continue
            
        ans_m = ANSWER_RE.match(low)
        if ans_m:
            correct_idx = ord(ans_m.group(1)) - ord('a')
            continue
            
        if OPTION_RE.match(low):
            mode = "options"
            if "✅" in line:
                correct_idx = len(opts)
            
            clean_opt = re.sub(r"^\(?[a-e]\)|^[a-e][\.\)]\s*", "", line.replace("✅", "")).strip()
            opts.append(clean_opt)
            continue
        
        if mode == "question":
            q_parts.append(line)
        elif mode == "options":
            if "✅" in line:
                correct_idx = len(opts) - 1
            opts[-1] += " " + line.replace("✅", "").strip()
        else:
            expl += " " + line

    if not q_parts:
        raise ValueError("Question text missing")
    if len(opts) < 2:
        raise ValueError(f"Only {len(opts)} options found. Check spacing.")
    if correct_idx is None:
        raise ValueError("Correct answer not found (Need ✅ or Answer: x)")

    return {
        "question": "\n".join(q_parts),
        "options": opts,
        "correct": correct_idx,
        "explanation": expl.strip(),
        "original_text": block
    }

# ---------------- SENDER ----------------

async def send_quiz(update: Update, qdata: dict):
    q = qdata["question"]
    opts = qdata["options"]
    idx = qdata["correct"]
    ex = qdata["explanation"]

    # Trigger fallback if too long or contains manual formatting/multiline
    too_long = len(q) > MAX_Q_LEN or any(len(o) > MAX_OPT_LEN for o in opts)
    
    if not too_long:
        try:
            await update.message.reply_poll(
                question=q,
                options=opts,
                type="quiz",
                correct_option_id=idx,
                explanation=ex[:MAX_EXPL_LEN] if ex else None,
                is_anonymous=True
            )
            return
        except Exception:
            pass

    # Clean Fallback Message
    clean_text = re.sub(ANSWER_RE, "", qdata["original_text"], flags=re.I).replace("✅", "").strip()
    sent_msg = await update.message.reply_text(clean_text)
    
    await update.message.reply_poll(
        question="Choose the correct option:",
        options=[f"Option {chr(65+i)}" for i in range(len(opts))],
        type="quiz",
        correct_option_id=idx,
        explanation=ex[:MAX_EXPL_LEN] if ex else None,
        is_anonymous=True,
        reply_to_message_id=sent_msg.message_id
    )

# ---------------- HANDLERS ----------------

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USER_SESSIONS:
        return

    if update.message.document and update.message.document.file_name.lower().endswith('.txt'):
        file = await context.bot.get_file(update.message.document.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        content = buf.getvalue().decode('utf-8')
    else:
        content = update.message.text

    blocks = get_blocks(content)
    USER_SESSIONS[uid].extend(blocks)
    await update.message.reply_text(f"📥 Queued {len(blocks)} questions. Send more or /done.")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USER_SESSIONS or not USER_SESSIONS[uid]:
        await update.message.reply_text("❌ No questions in session.")
        return

    await update.message.reply_text(f"⚙️ Processing {len(USER_SESSIONS[uid])} polls...")
    
    for block in USER_SESSIONS[uid]:
        try:
            qdata = parse_question_block(block)
            await send_quiz(update, qdata)
        except Exception as e:
            await update.message.reply_text(f"⚠️ Failed block: {str(e)}")
            
    USER_SESSIONS[uid] = []

async def annon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SESSIONS[update.effective_user.id] = []
    await update.message.reply_text("📩 Send questions/files. Send /done when finished.")

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("annon", annon))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
