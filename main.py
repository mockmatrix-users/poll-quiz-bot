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

# Enable logging for debugging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ---------------- CONFIG ----------------

BOT_TOKEN = "8792417044:AAFhz54pXi1TViE-xRaeRVAqE041OUL5o-M"

MAX_Q_LEN = 300
MAX_OPT_LEN = 100
MAX_EXPL_LEN = 200

USER_SESSIONS = {}

# Robust Regex Patterns
OPTION_START_RE = re.compile(r"^\(?[a-e]\)|^[a-e][\.\)]", re.IGNORECASE)
ANSWER_FLAG_RE = re.compile(r"^answer:\s*([a-e])", re.IGNORECASE)
EXPLANATION_RE = re.compile(r"^ex:", re.IGNORECASE)
BLOCK_SPLIT_RE = re.compile(r"\n\s*\n\s*\n") # Handles triple newlines with varying spaces

# ---------------- COMMANDS ----------------

async def annon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SESSIONS[update.effective_user.id] = []
    await update.message.reply_text(
        "🚀 **Advanced Poll Bot Active**\n\n"
        "1. Send questions (Text or .txt file)\n"
        "2. Use ✅ or `Answer: a` for the correct choice\n"
        "3. Use `ex:` for explanations\n"
        "4. Separate questions with **3 blank lines**\n"
        "5. Send /done when finished."
    )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USER_SESSIONS or not USER_SESSIONS[uid]:
        await update.message.reply_text("❌ No questions in queue!")
        return

    blocks = USER_SESSIONS[uid]
    success, fail = 0, 0
    error_log = []

    await update.message.reply_text(f"⏳ Processing {len(blocks)} questions...")

    for i, block in enumerate(blocks, start=1):
        try:
            qdata = parse_question_block(block)
            await send_quiz(update, qdata)
            success += 1
        except Exception as e:
            fail += 1
            error_log.append(f"Block {i}: {str(e)}")

    summary = f"✅ Created: {success}\n❌ Failed: {fail}"
    if error_log:
        summary += "\n\n**Error Details:**\n" + "\n".join(error_log)
    
    await update.message.reply_text(summary)
    USER_SESSIONS[uid] = [] # Clear session after processing

# ---------------- PARSER ----------------

def parse_question_block(block: str):
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    if not lines:
        raise ValueError("Empty block")

    q_text_parts = []
    options = []
    explanation = ""
    correct_idx = None
    
    mode = "question" # modes: question, options, explanation

    for line in lines:
        # 1. Check for Explanation Flag
        if EXPLANATION_RE.match(line):
            mode = "explanation"
            explanation = line[3:].strip()
            continue
        
        # 2. Check for Answer Flag
        ans_match = ANSWER_FLAG_RE.match(line)
        if ans_match:
            correct_idx = ord(ans_match.group(1).lower()) - ord('a')
            continue

        # 3. Check for Option Start
        if OPTION_START_RE.match(line):
            mode = "options"
            if "✅" in line:
                correct_idx = len(options)
            
            clean_opt = re.sub(r"^\(?[a-e]\)|^[a-e][\.\)]\s*", "", line.replace("✅", "")).strip()
            options.append(clean_opt)
            continue

        # 4. Handle Content based on current mode
        if mode == "question":
            q_text_parts.append(line)
        elif mode == "options" and options:
            # Multiline option continuation (Only if not a new flag)
            if "✅" in line:
                correct_idx = len(options) - 1
            options[-1] += " " + line.replace("✅", "").strip()
        elif mode == "explanation":
            explanation += " " + line

    # Validations
    q_final = "\n".join(q_text_parts)
    if not q_final: raise ValueError("Missing question text")
    if len(options) < 2: raise ValueError(f"Need 2+ options (Found {len(options)})")
    if correct_idx is None: raise ValueError("No correct answer marked (✅ or Answer: x)")
    if correct_idx >= len(options): raise ValueError(f"Answer key '{chr(97+correct_idx)}' out of range")

    return {
        "question": q_final,
        "options": options,
        "correct": correct_idx,
        "explanation": explanation.strip(),
        "original_text": block
    }

# ---------------- SENDER ----------------

async def send_quiz(update: Update, qdata: dict):
    q = qdata["question"]
    opts = qdata["options"]
    idx = qdata["correct"]
    ex = qdata["explanation"]

    # Logic to check if Native Poll is possible
    is_multiline = "\n" in qdata["original_text"] # Basic check
    too_long = len(q) > MAX_Q_LEN or any(len(o) > MAX_OPT_LEN for o in opts)
    ex_valid = ex if (ex and len(ex) <= MAX_EXPL_LEN) else None

    if not too_long:
        try:
            await update.message.reply_poll(
                question=q[:MAX_Q_LEN],
                options=opts,
                type="quiz",
                correct_option_id=idx,
                explanation=ex_valid,
                is_anonymous=True
            )
            return
        except Exception:
            pass # Fallback if poll fails for any other reason

    # FALLBACK SYSTEM
    # Clean text: Remove ticks and Answer flags for the message
    clean_text = re.sub(ANSWER_FLAG_RE, "", qdata["original_text"], flags=re.I)
    clean_text = clean_text.replace("✅", "").strip()

    sent_msg = await update.message.reply_text(clean_text)
    
    # Send simplified poll linked to message
    alpha_opts = [f"Option {chr(65+i)}" for i in range(len(opts))]
    await update.message.reply_poll(
        question="Select the correct answer below:",
        options=alpha_opts,
        type="quiz",
        correct_option_id=idx,
        explanation=ex_valid,
        is_anonymous=True,
        reply_to_message_id=sent_msg.message_id
    )

# ---------------- INPUT HANDLER ----------------

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USER_SESSIONS:
        return

    content = ""
    if update.message.document:
        if update.message.document.file_name.lower().endswith('.txt'):
            file = await context.bot.get_file(update.message.document.file_id)
            buf = io.BytesIO()
            await file.download_to_memory(buf)
            content = buf.getvalue().decode('utf-8')
        else:
            await update.message.reply_text("❌ Please send a .txt file.")
            return
    else:
        content = update.message.text

    # Split into blocks using the advanced regex
    new_blocks = [b.strip() for b in BLOCK_SPLIT_RE.split(content) if b.strip()]
    USER_SESSIONS[uid].extend(new_blocks)
    
    await update.message.reply_text(f"📥 Added {len(new_blocks)} questions to queue. (Total: {len(USER_SESSIONS[uid])})\nSend /done to finish.")

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("annon", annon))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input))
    
    print("🤖 Advanced Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
