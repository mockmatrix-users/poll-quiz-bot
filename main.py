import re
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

WAITING_USERS = set()

# Detect real options only: a) (a) a.
OPTION_START_RE = re.compile(r"^\(?[a-e]\)|^[a-e]\.")

# ---------------- COMMAND ----------------

async def annon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    WAITING_USERS.add(update.effective_user.id)
    await update.message.reply_text(
        "📩 Send all questions in ONE message.\n\n"
        "Rules:\n"
        "• Options: a) / (a) / a.\n"
        "• Mark correct option with ✅\n"
        "• Explanation must start with ex:\n"
        "• One blank line between questions"
    )

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
        line = raw_line.rstrip()
        if not line.strip():
            continue

        low = line.lower()

        # Explanation
        if low.startswith("ex:"):
            mode = "explanation"
            explanation_lines.append(line[3:].strip())
            continue

        # Option start
        if OPTION_START_RE.match(line.strip()):
            mode = "options"

            is_correct = "✅" in line
            clean = re.sub(
                r"^\(?[a-e]\)|^[a-e]\.\s*",
                "",
                line.replace("✅", "")
            ).strip()

            options.append(clean)
            if is_correct:
                correct_index = len(options) - 1

            continue

        # Multiline option continuation
        if mode == "options" and options:
            has_multiline_option = True
            if "✅" in line:
                correct_index = len(options) - 1
            options[-1] += " " + line.replace("✅", "").strip()
            continue

        # Explanation continuation
        if mode == "explanation":
            explanation_lines.append(line)
            continue

        # Question text
        question_lines.append(line)

    if not question_lines:
        raise ValueError("Question text missing")
    if len(options) < 2:
        raise ValueError("Minimum 2 options required")
    if correct_index is None:
        raise ValueError("No correct option marked with ✅")

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
    option_over = (
        any(len(o) > MAX_OPT_LEN for o in options)
        or qdata["has_multiline_option"]
    )

    explanation_ok = explanation and len(explanation) <= MAX_EXPL_LEN

    # Normal quiz
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

    # Fallback MESSAGE (CRITICAL FIX)
    if qdata["has_multiline_option"]:
        clean_text = qdata["original_text"].replace("✅", "")
        sent_msg = await update.message.reply_text(
            clean_text
        )
    else:
        msg_parts = [question]
        for idx, opt in enumerate(options):
            msg_parts.append(f"{chr(97+idx)}) {opt}")
        sent_msg = await update.message.reply_text(
            "\n\n".join(msg_parts)
        )

    # Fallback POLL
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

# ---------------- HANDLER ----------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in WAITING_USERS:
        return

    WAITING_USERS.remove(uid)

    raw = update.message.text.strip()
    blocks = [b.strip() for b in raw.split("\n\n\n") if b.strip()]

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

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("annon", annon))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
