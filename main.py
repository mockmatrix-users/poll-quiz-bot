import re
import io
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

# Stores blocks for each user until /done is called
USER_SESSIONS = {}

# Detect real options only: a) (a) a.
OPTION_START_RE = re.compile(r"^\(?[a-e]\)|^[a-e]\.")
# Detect Answer: a/b/c/d/e
ANSWER_RE = re.compile(r"^answer:\s*([a-e])", re.IGNORECASE)

# ---------------- COMMANDS ----------------

async def annon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SESSIONS[update.effective_user.id] = []
    await update.message.reply_text(
        "📩 Send questions via message or .txt file.\n\n"
        "Rules:\n"
        "• Mark correct option with ✅ OR 'Answer: a'\n"
        "• Explanation starts with ex:\n"
        "• Once finished, send /done to generate polls."
    )

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USER_SESSIONS or not USER_SESSIONS[uid]:
        await update.message.reply_text("❌ No questions found. Send some first!")
        return

    blocks = USER_SESSIONS[uid]
    success = 0
    errors = []

    for i, block in enumerate(blocks, start=1):
        try:
            qdata = parse_question_block(block)
            await send_quiz(update, qdata)
            success += 1
        except Exception as e:
            errors.append(f"Q{i}: {e}")

    msg = f"✅ {success} quiz poll(s) created."
    if errors:
        msg += "\n\n❌ Errors:\n" + "\n".join(errors)

    await update.message.reply_text(msg)
    del USER_SESSIONS[uid]

# ---------------- PARSER ----------------

def parse_question_block(block: str):
    original_text = block.strip()
    lines = block.split("\n")

    question_lines = []
    options = []
    explanation_lines = []

    correct_index = None
    mode = "question"
    has_multiline_option = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        low = line.lower()

        # Check for Answer: a/b/c format
        ans_match = ANSWER_RE.match(low)
        if ans_match:
            letter = ans_match.group(1)
            correct_index = ord(letter) - ord('a')
            continue

        # Explanation
        if low.startswith("ex:"):
            mode = "explanation"
            explanation_lines.append(line[3:].strip())
            continue

        # Option start
        if OPTION_START_RE.match(line):
            mode = "options"
            is_correct = "✅" in line
            
            clean = re.sub(r"^\(?[a-e]\)|^[a-e]\.\s*", "", line.replace("✅", "")).strip()
            options.append(clean)
            
            if is_correct:
                correct_index = len(options) - 1
            continue

        # Multiline option continuation
        if mode == "options" and options:
            if "✅" in line:
                correct_index = len(options) - 1
            
            if not ANSWER_RE.match(low): # Ensure Answer: a isn't appended to options
                has_multiline_option = True
                options[-1] += " " + line.replace("✅", "").strip()
            continue

        # Explanation continuation
        if mode == "explanation":
            explanation_lines.append(line)
            continue

        # Question text
        if mode == "question":
            question_lines.append(line)

    if not question_lines:
        raise ValueError("Question text missing")
    if len(options) < 2:
        raise ValueError("Minimum 2 options required")
    if correct_index is None or correct_index >= len(options):
        raise ValueError("No valid correct option marked (use ✅ or Answer: a)")

    return {
        "question": "\n".join(question_lines),
        "options": options,
        "correct": correct_index,
        "explanation": "\n".join(explanation_lines).strip(),
        "has_multiline_option": has_multiline_option,
        "original_text": original_text
    }

# ---------------- SENDER ----------------

async def send_quiz(update, qdata):
    question = qdata["question"]
    options = qdata["options"]
    correct = qdata["correct"]
    explanation = qdata["explanation"]

    question_over = len(question) > MAX_Q_LEN
    option_over = any(len(o) > MAX_OPT_LEN for o in options) or qdata["has_multiline_option"]
    explanation_ok = explanation and len(explanation) <= MAX_EXPL_LEN

    if not question_over and not option_over:
        await update.message.reply_poll(
            question=question,
            options=options,
            type="quiz",
            correct_option_id=correct,
            explanation=explanation if explanation_ok else None,
            is_anonymous=True
        )
        return

    # Fallback logic preserved
    if qdata["has_multiline_option"]:
        # Clean text for display by removing the "Answer: x" or ticks
        display_text = re.sub(ANSWER_RE, "", qdata["original_text"], flags=re.I).replace("✅", "").strip()
        sent_msg = await update.message.reply_text(display_text)
    else:
        msg_parts = [question]
        for idx, opt in enumerate(options):
            msg_parts.append(f"{chr(97+idx)}) {opt}")
        sent_msg = await update.message.reply_text("\n\n".join(msg_parts))

    poll_options = [chr(65+i) for i in range(len(options))]
    await update.message.reply_poll(
        question="Choose the correct option",
        options=poll_options,
        type="quiz",
        correct_option_id=correct,
        explanation=explanation if explanation_ok else None,
        is_anonymous=True,
        reply_to_message_id=sent_msg.message_id
    )

# ---------------- HANDLERS ----------------

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USER_SESSIONS:
        return

    content = ""
    if update.message.document:
        if update.message.document.file_name.endswith('.txt'):
            file = await context.bot.get_file(update.message.document.file_id)
            out = io.BytesIO()
            await file.download_to_memory(out)
            content = out.getvalue().decode('utf-8')
        else:
            await update.message.reply_text("❌ Only .txt files are supported.")
            return
    else:
        content = update.message.text

    blocks = [b.strip() for b in content.split("\n\n\n") if b.strip()]
    USER_SESSIONS[uid].extend(blocks)
    await update.message.reply_text(f"📥 Added {len(blocks)} blocks. Send more or use /done.")

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("annon", annon))
    app.add_handler(CommandHandler("done", done))
    # Handle both text and txt files
    app.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_input))
    
    print("🤖 Bot running with Answer: x support and /done command...")
    app.run_polling()

if __name__ == "__main__":
    main()
      
